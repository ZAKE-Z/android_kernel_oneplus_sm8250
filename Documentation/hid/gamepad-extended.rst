Extended gamepad backport (experimental)
=======================================

This adds controller-specific functionality beyond the selected mainline
snapshot. No physical controller or OPPO Pad has been tested. Compilation,
packet-layout and host-side tests do not establish functional hardware support.
Nothing is installed on a device or flashed by the build scripts.

DualSense / DualSense Edge adaptive triggers
------------------------------------------

The HID device directory exposes ``adaptive_triggers`` only on DS5/Edge,
not DS4. Its mode is 0644; writes require root or a deliberately configured
privileged policy. Do not make controller control nodes world-writable.

The value is 44 hexadecimal characters: eleven bytes for left L2 followed
by eleven for right R2. Each effect is a mode byte and ten parameters.
One trailing newline is permitted. Updates to both sides are atomic and
queued through the same worker as rumble/LED/audio, preserving Bluetooth
sequence and CRC handling. Audio flags are ORed instead of replacing
unrelated flags. Effects default to off, are not persisted across reconnect,
and are best-effort cleared during driver removal. This is not a promise
that physical cable removal will deliver an off packet.

Recognized mode bytes: 05 (off), 21 (feedback), 22 (bow), 23 (galloping),
25 (weapon), 26 (vibration), 27 (machine). Other modes are rejected. The
raw interface validates mode/length; use the helper for parameter-range
validation. Readback shows the requested state, not hardware acknowledgement.

``tools/gamepad/dualsense-trigger.py`` encodes effects using the GPL-2.0+
``nowrep/dualsensectl`` protocol. It needs Python 3 (e.g. a suitable Android
shell environment). Examples after identifying the exact controller:

.. code-block:: text

   python3 dualsense-trigger.py both feedback 3 4 --dry-run
   python3 dualsense-trigger.py left weapon 2 4 3 --device /sys/bus/hid/devices/DEVICE
   python3 dualsense-trigger.py both off --device /sys/bus/hid/devices/DEVICE

Supported helper effects: off, feedback, weapon, bow, galloping, machine,
vibration, feedback-raw (ten zone strengths) and vibration-raw (ten strengths
then frequency). ``--dry-run`` never touches hardware. Test weak effects
first, do not force the trigger mechanically, and stop if it heats or behaves
unexpectedly. A game's ordinary FF_RUMBLE is not automatically translated to
adaptive-trigger effects. A game, streaming client or explicit userspace
integration must request effects. Raw HID clients remain available and can
race the kernel's requested state; use one controller-output owner.

This does not implement the separate Bluetooth audio/Opus haptic streaming
protocol, ALSA routing changes, firmware updates or arbitrary vendor commands.
Those are independent of adaptive trigger motor profiles and are not declared
supported simply because the hidraw transport exists.

Switch 2 sensors and wired operation
-----------------------------------

The initialization selects report 05 and enables the documented raw IMU,
magnetometer and, for Joy-Con 2, optical mouse features. The existing mainline
gamepad and rumble implementation is retained. Report length is checked before
accessing fields. Raw signed accel/gyro and magnetometer samples are separate
evdev input devices; ``MSC_TIMESTAMP`` carries the controller's documented
motion timestamp. Joy-Con 2 mouse motion uses signed wraparound differences
of 16-bit absolute counters and suppresses movement for the first sample.
Mouse buttons can be supplied by userspace mappings; no fixed button remapping
is forced by this driver.

The IMU device intentionally does not advertise an unverified physical-unit
resolution: community implementations disagree on firmware-dependent gyro
scale. Validate sign, axes, scale, timestamp behavior and bias on each device
before motion aiming. The magnetometer is raw, not calibrated heading. No
Android Sensor HAL is installed. Emulators may need an evdev-to-DSU bridge or
an application that reads these sensors explicitly.

Battery voltage is exposed through power_supply ``voltage_now`` (microvolts).
No guessed percentage/charging status is fabricated. ``switch2_status`` in
the HID device directory reports initialization state, retries, voltage and
raw temperature. ``ready=1`` means the protocol state machine completed, not
that sensors have been calibrated or hardware support certified.

Unproven on hardware: availability of unified report 05 after USB setup on
all firmwares, simultaneous features, magnetometer validity, optical lift-off
behavior and raw IMU timing. Packed motion reports 07/08/09/0a are not falsely
decoded as signed raw samples. They remain input-compatible but only report
05 supplies the new raw sensors. Do not replace one format with guessed bytes.

Switch 2 BLE transport and Android application
---------------------------------------------

``CONFIG_NINTENDO_SWITCH2_BLE`` adds a private GATT-to-UHID bridge protocol
inside hid-nintendo. It requires UHID. This is not native HOGP pairing support:
Switch 2 controllers use proprietary GATT characteristics. Android Bluetooth
settings alone still cannot bind them. Android's stack is not BlueZ.

The privileged relay must create a BUS_BLUETOOTH UHID device with the genuine
controller product ID and phys prefix ``ns2-gatt-v1/``. The driver rejects
this ABI on non-UHID transports and does not replace ``hdev->ll_driver``.
Its report-ID-1 input payload is a 16-bit little-endian symbolic routing key
followed by GATT data. The symbolic keys are **not** actual ATT handles:

- 0000: READY (one dummy byte), only after the relay can receive output.
- 000a: unified report-05 payload (63 bytes, no report ID).
- 000e: controller-specific payload (63 bytes, no report ID).
- 001a: command reply header+payload (at least eight bytes).

Kernel output contains a two-byte key followed by characteristic data:
0014 for basic commands, 0012 for rumble. The userspace transport resolves
UUIDs on each connection; actual handles can change with firmware. The kernel
defers init until READY, skips USB-only finishing commands on BLE, and emits
42-byte BLE rumble packets with report ID zero. BLE rumble is rate-limited
to about 15 ms rather than the USB worker's 4 ms. No pairing keys, flash or
firmware writes are implemented. Initializing over BLE is experimental; all
command handshakes must be confirmed on real devices.

``tools/gamepad/android-switch2-bridge`` contains an original minimal Android
GATT application plus an ARM64 root UHID relay. It is a **lab harness**, not
a production connection manager. The build script generates a locally signed
``Switch2-BLE-Lab-UNTESTED.apk`` without installing it. The lab key is not a
production trust identity. The app requests Nearby Devices permission and
explicit su authorization, connects only to a controller selected by the user,
discovers UUIDs, queues CCCD/writes, forwards input and ACKs, and fails closed
on timeouts/backpressure. Press its Kernel Status button to inspect init.

Limitations: one device, foreground Activity only, SYNC before connection,
no bond persistence, no background service, no wake/reconnect guarantees,
no USB accessory handling, no automatic game mappings or DSU server. Root
SELinux may prohibit the relay; permission is not weakened automatically.
The helper does not replace Android's Bluetooth service or toggle adapter
privacy settings. The app is compatible only with this private kernel ABI.

For a more developed Android userspace alternative, inspect
``https://github.com/JoeGeC/joycon2android`` (GPL-3.0). It provides its own
uinput virtual pads, motion DSU, multi-player and mouse support without this
private kernel transport. It was cloned for research, not copied into the
GPLv2 kernel. It is neither bundled nor silently installed. Its protocol docs
explicitly describe Android privacy-address and SYNC limitations.

Other capabilities and pending work
----------------------------------

Existing DS4/DS5 touchpad, gyro, acceleration, microphone mute, audio-jack
detection, battery, LED and Edge buttons remain enabled. Switch 1 IMU,
calibration, rumble and supported NSO models remain intact. DS4 has no adaptive
trigger actuators. Xbox triggers/haptics are restricted to the hid-microsoft
protocol; USB xpad, xpadneo, nonstandard vendor profiles, NFC, IR cameras,
speaker/audio streaming and authentication require separate implementations
or userspace support, not just new Kconfig values.

These features have not been abandoned because of kernel version. Unfinished
items are marked pending protocol/hardware/Android integration, rather than
claimed impossible or silently implemented with stubs. Deploy only after a
known-good Pad baseline, recovery method and controller hardware are available.

Sources
-------

- torvalds/linux: 9d66f26fefacebfeed15de31c1123451a17ff119.
- nowrep/dualsensectl: d3ae2fa272e1bf9a5c08a0ded3f374b40f7c73ac, GPL-2.0+.
- martin-bts/hid-switch2-dkms: 61f16e00cb71f51d4b1b29d893438097de2839be,
  GPL-2.0+, GATT/UHID framing reference; not copied wholesale.
- ndeadly/switch2_controller_research:
  a3306b473acff0d6844fb1e288883a3940df0baf, protocol documentation only.
- trevlars/switch2-controllers-linux: MIT-licensed decoder reference.
  Commit a0a36e6b88ed5500f60cac29815aabad0d8956bd.
  The applicable MIT notice is preserved in tools/gamepad/LICENSE.trevlars.
- JoeGeC/joycon2android: 8a1ed9495d869f5dfdfd4406cbdb4d24768fa1d8,
  GPL-3.0, separately inspected Android reference, not kernel source.
