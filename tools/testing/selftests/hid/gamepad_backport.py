#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Host-side regression checks; these do not substitute for controller tests."""

import os
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[4]
HID = ROOT / "drivers/hid"


class GamepadBackport(unittest.TestCase):
    def test_special_driver_routing(self):
        quirks = (HID / "hid-quirks.c").read_text()
        drivers = {
            "HID_PLAYSTATION": ("hid-playstation.c", "ps_devices"),
            "HID_NINTENDO": ("hid-nintendo.c", "nintendo_hid_devices"),
            "HID_SONY": ("hid-sony.c", "sony_devices"),
            "HID_MICROSOFT": ("hid-microsoft.c", "ms_devices"),
        }
        pattern = r"HID_(?:USB|BLUETOOTH)_DEVICE\(\s*(\w+),\s*(\w+)\s*\)"
        tables = {}
        for config, (filename, table) in drivers.items():
            source = (HID / filename).read_text()
            source = source.split("static const struct hid_device_id " + table + "[]", 1)[1]
            source = source.split("};", 1)[0]
            entries = {re.sub(r"\s+", "", m.group(0))
                       for m in re.finditer(pattern, source)}
            block = quirks.split("#if IS_ENABLED(CONFIG_" + config + ")", 1)[1]
            block = block.split("#endif", 1)[0]
            routed = {re.sub(r"\s+", "", m.group(0))
                      for m in re.finditer(pattern, block)}
            self.assertFalse(entries - routed, (config, entries - routed))
            tables[config] = entries
        self.assertFalse(tables["HID_PLAYSTATION"] & tables["HID_SONY"])

    def test_required_ids_exist(self):
        ids = (HID / "hid-ids.h").read_text()
        defined = set(re.findall(r"^#define\s+(USB_(?:DEVICE|VENDOR)_ID_\w+)", ids, re.M))
        for filename in ("playstation", "nintendo", "nintendo-switch2-usb", "microsoft", "sony"):
            used = set(re.findall(r"\bUSB_(?:DEVICE|VENDOR)_ID_\w+", (HID / ("hid-" + filename + ".c")).read_text()))
            self.assertFalse(used - defined, used - defined)

    def test_edge_capabilities_precede_registration(self):
        source = (HID / "hid-playstation.c").read_text()
        create = source.split("ps_gamepad_create(struct hid_device *hdev,", 1)[1]
        create = create.split("return gamepad;", 1)[0]
        register = create.index("input_register_device(gamepad)")
        for button in range(1, 5):
            self.assertLess(create.index("BTN_TRIGGER_HAPPY" + str(button)), register)

    def test_config_fragment(self):
        fragment = (ROOT / "arch/arm64/configs/vendor/gamepad-backport.config").read_text()
        for symbol in ("HID_PLAYSTATION", "HID_NINTENDO", "HID_MICROSOFT", "HID_SONY",
                       "NINTENDO_FF", "PLAYSTATION_FF", "SONY_FF",
                       "LEDS_CLASS_MULTICOLOR", "INPUT_FF_MEMLESS"):
            self.assertIn("CONFIG_" + symbol + "=y\n", fragment)
        self.assertNotIn("CONFIG_MODULE_SIG", fragment)
        self.assertNotIn("CONFIG_KSU", fragment)

    def test_adaptive_trigger_effects(self):
        spec = importlib.util.spec_from_file_location("triggers", ROOT / "tools/gamepad/dualsense-trigger.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.effect("off", []), bytes([5]) + bytes(10))
        self.assertEqual(module.effect("feedback", [3, 4]).hex(), "21f80300b66d1b00000000")
        self.assertEqual(module.effect("weapon", [2, 4, 3]).hex(), "2514000200000000000000")
        self.assertEqual(module.effect("bow", [1, 4, 3, 5]).hex(), "2212002200000000000000")
        cases = [("galloping", [1, 4, 1, 3, 4]), ("machine", [1, 4, 2, 3, 4, 5]),
                 ("vibration", [2, 4, 100]), ("feedback-raw", [8] * 10),
                 ("vibration-raw", [1] * 10 + [50])]
        for mode, values in cases:
            self.assertEqual(len(module.effect(mode, values)), 11)
        for mode, values in [("feedback", [-1, 2]), ("feedback", [2, 9]),
                             ("weapon", [4, 3, 4]), ("vibration", [2, 4, 0]),
                             ("galloping", [1, 4, 3, 2, 5]), ("off", [1])]:
            with self.assertRaises(ValueError):
                module.effect(mode, values)

    def test_extended_kernel_wiring(self):
        nintendo = (HID / "hid-nintendo.c").read_text()
        playstation = (HID / "hid-playstation.c").read_text()
        fragment = (ROOT / "arch/arm64/configs/vendor/gamepad-backport.config").read_text()
        self.assertIn("CONFIG_INPUT_UINPUT=y", fragment)
        self.assertIn("hid_is_using_ll_driver(hdev, &uhid_hid_driver)", nintendo)
        self.assertIn('strncmp(hdev->phys, "ns2-gatt-v1/", 12)', nintendo)
        self.assertNotIn("hdev->ll_driver =", nintendo)
        self.assertIn("return switch2_set_report_format(ns2, NS2_REPORT_UNIFIED)", nintendo)
        effects = playstation.split("static bool dualsense_trigger_mode_valid", 1)[1].split("static ssize_t adaptive_triggers_store", 1)[0]
        self.assertEqual(set(re.findall(r"case (0x[0-9a-f]+):", effects)),
                         {"0x05", "0x21", "0x22", "0x23", "0x25", "0x26", "0x27"})
        worker = playstation.split("static void dualsense_output_worker", 1)[1].split("static int dualsense_parse_report", 1)[0]
        self.assertNotIn("common->valid_flag0 =", worker)
        self.assertNotIn("common->valid_flag1 =", worker)

    def test_switch2_decoder(self):
        header = (HID / "hid-gamepad-protocol.h").read_text()
        prelude = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef int16_t s16;
static u16 get_unaligned_le16(const void *p) { const u8 *b=p; return b[0] | ((u16)b[1]<<8); }
static u32 get_unaligned_le32(const void *p) { const u8 *b=p; return get_unaligned_le16(b) | ((u32)get_unaligned_le16(b+2)<<16); }
static void put16(u8 *p, u16 v) { p[0]=v; p[1]=v>>8; }
'''
        tests = r'''
int main(void) {
    u8 report[64] = {5}; struct gamepad_ns2_sample sample = {0};
    size_t i;
    for(i=0;i<64;i++) assert(gamepad_ns2_decode(report,i,&sample)==-EINVAL);
    put16(report+0x31, 0x8000); put16(report+0x33, 4096); put16(report+0x35,0x7fff);
    put16(report+0x37,0xffff); put16(report+0x39,123); put16(report+0x3b,456);
    put16(report+0x1a,0xfffe); put16(report+0x1c,2); put16(report+0x1e,3);
    put16(report+0x20,3850); put16(report+0x11,65534); put16(report+0x13,2);
    put16(report+0x2f,127); put16(report+0x2b,0x1234); put16(report+0x2d,0xabcd);
    assert(gamepad_ns2_decode(report,64,&sample)==0);
    assert(sample.accel[0]==-32768 && sample.accel[1]==4096 && sample.accel[2]==32767);
    assert(sample.gyro[0]==-1 && sample.gyro[1]==123 && sample.gyro[2]==456);
    assert(sample.magnetometer[0]==-2 && sample.voltage_mv==3850 && sample.temperature==127);
    assert(sample.timestamp==0xabcd1234 && sample.mouse_x==65534 && sample.mouse_y==2);
    assert(gamepad_ns2_mouse_delta(2,65534)==4 && gamepad_ns2_mouse_delta(65534,2)==-4);
    report[0]=9; assert(gamepad_ns2_decode(report,64,&sample)==-EINVAL);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ns2-decoder-") as directory:
            source = Path(directory) / "decoder.c"
            binary = Path(directory) / "decoder"
            source.write_text(prelude + header + tests)
            subprocess.run([os.environ.get("HOSTCC", "gcc"), "-std=gnu11", "-O2",
                            "-Wall", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_dualsense_report_layout(self):
        source_text = (HID / "hid-playstation.c").read_text()
        layout = source_text.split("struct dualsense_output_report_common {", 1)[1].split("} __packed;", 1)[0]
        code = "#include <stddef.h>\n#include <stdint.h>\ntypedef uint8_t u8;\n"
        code += "struct report {" + layout + "} __attribute__((packed));\n"
        code += '_Static_assert(sizeof(struct report)==47,"size");\n'
        code += '_Static_assert(offsetof(struct report,trigger_right)==10,"right");\n'
        code += '_Static_assert(offsetof(struct report,trigger_left)==21,"left");\n'
        code += '_Static_assert(offsetof(struct report,valid_flag2)==38,"flags");\nint main(void){return 0;}\n'
        with tempfile.TemporaryDirectory(prefix="ds-layout-") as directory:
            source = Path(directory) / "layout.c"
            source.write_text(code)
            subprocess.run([os.environ.get("HOSTCC", "gcc"), "-std=gnu11", "-Wall", "-Werror",
                            str(source), "-o", str(Path(directory) / "layout")], check=True)

    def test_uhid_relay_framing(self):
        relay = ROOT / "tools/gamepad/android-switch2-bridge/relay.c"
        code = '#define main relay_main\n#include "' + str(relay) + '"\n#undef main\n#include <assert.h>\n'
        code += r'''
int main(void) {
    int fd[2]; struct uhid_event ev; char line[300];
    assert(pipe(fd)==0);
    strcpy(line,"I a 0102ff\n"); assert(parse_input(fd[1],line)==0);
    assert(read(fd[0],&ev,sizeof(ev))==sizeof(ev));
    assert(ev.type==UHID_INPUT2 && ev.u.input2.size==6);
    assert(ev.u.input2.data[0]==1 && ev.u.input2.data[1]==10 && ev.u.input2.data[2]==0);
    assert(ev.u.input2.data[3]==1 && ev.u.input2.data[5]==255);
    strcpy(line,"I 10000 01\n"); assert(parse_input(fd[1],line)<0);
    strcpy(line,"I a 0g\n"); assert(parse_input(fd[1],line)<0);
    strcpy(line,"I a 1\n"); assert(parse_input(fd[1],line)<0);
    strcpy(line,"I a \n"); assert(parse_input(fd[1],line)<0);
    strcpy(line,"X a 00\n"); assert(parse_input(fd[1],line)<0);
    strcpy(line,"I 1a "); memset(line+5,'0',256); line[261]='\n'; line[262]=0;
    assert(parse_input(fd[1],line)==0);
    assert(read(fd[0],&ev,sizeof(ev))==sizeof(ev) && ev.u.input2.size==131);
    assert(descriptor[16]==0x95 && descriptor[17]==0x82); /* 130-byte payload */
    close(fd[0]); close(fd[1]); return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="ns2-relay-") as directory:
            source = Path(directory) / "relay.c"
            binary = Path(directory) / "relay"
            source.write_text(code)
            subprocess.run([os.environ.get("HOSTCC", "gcc"), "-std=gnu11", "-O2",
                            "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_cleanup_guards(self):
        # Compile the actual guard implementation, with host-side lock stubs.
        header = (HID / "hid-gamepad-compat.h").read_text()
        guards = header.split("struct gamepad_guard {", 1)[1]
        guards = "struct gamepad_guard {" + guards.split("#define timer_container_of", 1)[0]
        prelude = r'''
#include <assert.h>
#include <stdbool.h>
#define __maybe_unused __attribute__((__unused__))
#define __PASTE(a, b) __PASTE_1(a, b)
#define __PASTE_1(a, b) a##b
struct mutex { int held; };
typedef struct { int held; } spinlock_t;
static int rcu_depth;
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held++; }
static void mutex_unlock(struct mutex *m) { assert(m->held == 1); m->held--; }
#define spin_lock_irqsave(p, flags) do { assert(!(p)->held); (p)->held++; (flags) = 42; } while (0)
#define spin_unlock_irqrestore(p, flags) do { assert((p)->held == 1); assert((flags) == 42); (p)->held--; } while (0)
static void rcu_read_lock(void) { rcu_depth++; }
static void rcu_read_unlock(void) { assert(rcu_depth); rcu_depth--; }
'''
        tests = r'''
static int early_return(struct mutex *m, spinlock_t *s)
{
    guard(mutex)(m);
    guard(spinlock_irqsave)(s);
    guard(rcu)();
    assert(m->held && s->held && rcu_depth == 1);
    return 7;
}
static void scopes(struct mutex *m, spinlock_t *s)
{
    int n = 0;
    guard(mutex)(m);
    scoped_guard(spinlock_irqsave, s) { assert(s->held); n++; }
    assert(!s->held && n == 1);
    scoped_guard(spinlock_irqsave, s) { continue; }
    assert(!s->held);
    scoped_guard(spinlock_irqsave, s) { break; }
    assert(!s->held);
    scoped_guard(spinlock_irqsave, s) { goto out; }
out:
    assert(!s->held && m->held);
}
static void bare_scope(spinlock_t *s)
{
    scoped_guard(spinlock_irqsave, s)
        assert(s->held);
    assert(!s->held);
}
int main(void)
{
    struct mutex m = { 0 };
    spinlock_t s = { 0 };
    assert(early_return(&m, &s) == 7);
    assert(!m.held && !s.held && !rcu_depth);
    scopes(&m, &s);
    bare_scope(&s);
    assert(!m.held && !s.held);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="gamepad-guards-") as directory:
            source = Path(directory) / "guards.c"
            binary = Path(directory) / "guards"
            source.write_text(prelude + guards + tests)
            subprocess.run([os.environ.get("HOSTCC", "gcc"), "-std=gnu11", "-O2",
                            "-Wall", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_multicolor_values(self):
        source_text = (ROOT / "drivers/leds/led-class-multicolor.c").read_text()
        calculation = source_text.split("int led_mc_calc_color_components", 1)[1]
        calculation = "int led_mc_calc_color_components" + calculation.split("EXPORT_SYMBOL_GPL", 1)[0]
        store = source_text.split("static ssize_t multi_intensity_store", 1)[1]
        store = "static ssize_t multi_intensity_store" + store.split("static ssize_t multi_intensity_show", 1)[0]
        prelude = r'''
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#define LED_COLOR_ID_MAX 10
enum led_brightness { LED_OFF, LED_FULL = 255 };
struct mutex { int held; };
struct device { void *data; };
struct device_attribute { int unused; };
struct mc_subled { unsigned int color_index, brightness, intensity; };
struct led_classdev { unsigned int max_brightness, brightness; struct mutex led_access; };
struct led_classdev_mc { struct led_classdev led_cdev; unsigned int num_colors; struct mc_subled *subled_info; };
static void *dev_get_drvdata(struct device *d) { return d->data; }
static struct led_classdev_mc *lcdev_to_mccdev(struct led_classdev *d) { return (struct led_classdev_mc *)d; }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held++; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held--; }
static void led_set_brightness(struct led_classdev *d, unsigned int b) { d->brightness = b; }
'''
        tests = r'''
int main(void)
{
    struct mc_subled channels[3] = { { 0 } };
    struct led_classdev_mc rgb = { .led_cdev = { .max_brightness = 255, .brightness = 128 }, .num_colors = 3, .subled_info = channels };
    struct device dev = { .data = &rgb.led_cdev };
    const char *valid = "255 128 0\n";
    const char *bad[] = { "256 0 0\n", "-1 0 0\n", "1 2\n", "1 2 3 4\n", "1 2 3x\n", "", "a 2 3\n" };
    size_t i;
    assert(multi_intensity_store(&dev, NULL, valid, strlen(valid)) == (ssize_t)strlen(valid));
    assert(led_mc_calc_color_components(&rgb, 128) == 0);
    assert(channels[0].brightness == 128 && channels[1].brightness == 64 && channels[2].brightness == 0);
    for (i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        assert(multi_intensity_store(&dev, NULL, bad[i], strlen(bad[i])) == -EINVAL);
        assert(!rgb.led_cdev.led_access.held);
        assert(channels[0].intensity == 255 && channels[1].intensity == 128 && channels[2].intensity == 0);
    }
    rgb.led_cdev.max_brightness = 0;
    assert(led_mc_calc_color_components(&rgb, 128) == -EINVAL);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="gamepad-leds-") as directory:
            source = Path(directory) / "leds.c"
            binary = Path(directory) / "leds"
            source.write_text(prelude + calculation + store + tests)
            subprocess.run([os.environ.get("HOSTCC", "gcc"), "-std=gnu11", "-O2",
                            "-Wall", "-Werror", str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
