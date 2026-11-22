# android_kernel_oneplus_sm8250（OPPO Pad OPD2101）

[中文说明](#中文说明) | [English](#english)

---

## 中文说明

### 项目定位

本仓库是 [`toraidl/android_kernel_oneplus_sm8250`](https://github.com/toraidl/android_kernel_oneplus_sm8250) 的 **fork**，上游分支为 `bpf-5.15-backport`，基准提交为 `302ad90819725ae7040524e75c293b493b4b751c`（Linux `4.19.325`）。

- 目标设备：OPPO Pad **OPD2101**（`kona` / SM8250），运行第三方 ColorOS 17 移植系统（原厂最高支持 ColorOS 14）。
- 本仓库包含手柄和浏览器兼容性改动，以及实验性的充电、电量代码移植。实验性 boot 镜像通过 Release 附件提供。
- **真机测试范围仅限 OPPO Pad OPD2101**；不能据此推断其他设备兼容。新移植的充电代码及对应 boot 镜像尚未确认通过真机测试，不能保证修复充电问题。
- 设备实际 ROM 内核源码并未公开；本 fork **不声称**与设备出厂或 ROM 作者内核完全一致。所有运行结论以真机验证为准。

### 修改内容

#### 1. 现代游戏手柄驱动回移与多色 LED 支持

从 Linux 上游快照（`torvalds/linux` `7.4-rc2`，提交 `9d66f26fefacebfeed15de31c1123451a17ff119`）与 Linux `v5.10` LED 子系统移植适配到 `4.19`：

- **PlayStation 手柄**（`drivers/hid/hid-playstation.c`、`drivers/hid/hid-sony.c`）
  - PS4（USB / 蓝牙 / Sony USB 适配器）、PS5 DualSense 与 DualSense Edge：输入、触控板、陀螺仪/加速度计、电量、灯条与振动。
  - DualSense Edge 额外背键/Fn 键编码，`include/uapi/linux/input-event-codes.h` 新增 `BTN_GRIPL` / `BTN_GRIPR` / `BTN_GRIPL2` / `BTN_GRIPR2`。
  - 实验性 `adaptive_triggers` sysfs 接口与配套工具 `tools/gamepad/dualsense-trigger.py`（不自动下发，需显式写入）。
  - PS4 设备路由统一交由 `hid-playstation`，避免与 `hid-sony` 重复绑定。
- **Nintendo Switch / Switch 2 手柄**（`drivers/hid/hid-nintendo.c`、`hid-nintendo.h`、`hid-nintendo-switch2-usb.c`）
  - Switch 1 Joy-Con、Pro 手柄、充电握把与已支持的 NSO 手柄：校准、IMU、电量、LED、振动及休眠恢复修复。
  - Switch 2 有线 USB（`CONFIG_NINTENDO_SWITCH2_USB`）与实验性用户态 BLE GATT-to-UHID 桥（`CONFIG_NINTENDO_SWITCH2_BLE`）；说明见 `Documentation/hid/gamepad-extended.rst`，实验工程见 `tools/gamepad/android-switch2-bridge/`。
- **Microsoft 与路由 / 4.19 兼容层**
  - 更新 `hid-microsoft.c`、`hid-ids.h`、`hid-quirks.c`：补充设备 ID、蓝牙 Xbox 兼容振动与特殊驱动路由表。
  - 新增 `hid-gamepad-compat.h`、`hid-gamepad-protocol.h`，在不改动 4.19 HID 核心 ABI 的前提下提供驱动局部 cleanup scope 与协议解码。
  - `drivers/hid/Kconfig`、`drivers/hid/Makefile` 仅对回移文件启用 `-std=gnu11`。
- **多色 LED 类**（`drivers/leds/led-class-multicolor.c`、`drivers/leds/Kconfig`、`drivers/leds/Makefile`、`include/linux/led-class-multicolor.h`、`include/dt-bindings/leds/common.h`）
  - 将 Linux `v5.10` 的 `LEDS_CLASS_MULTICOLOR` 适配到 `4.19` LED 注册接口，用于 PlayStation 手柄 RGB 灯条。
- **配置与回归测试**（`arch/arm64/configs/vendor/kona-perf_defconfig`、`gamepad-backport.config`、`tools/testing/selftests/hid/gamepad_backport.py`）
  - 默认 defconfig 启用 `CONFIG_NINTENDO_FF=y`、`CONFIG_NINTENDO_SWITCH2_USB=y`、`CONFIG_NINTENDO_SWITCH2_BLE=y`。

#### 2. Android 17 原生 App Zygote 能力兼容修复（浏览器无法启动）

- **原因**：Android 17 的原生 App Zygote（`zygote_next` / `libzygote`）在隔离沙箱子进程初始化时，会查询 capability 边界集直到编号 `40`（`CAP_CHECKPOINT_RESTORE`）。原 4.19 内核上界只有 `39`（`CAP_BPF`），`prctl(PR_CAPBSET_READ, 40)` 返回 `-EINVAL`，Zygote 子进程随即 `SIGABRT`；Chromium 的沙箱 / GPU 子进程无法拉起，Chrome、Edge 等浏览器卡启动或闪退，失败重试还会占用 `system_server` 的公共进程启动线程，导致其他应用启动排队变慢。
- **修复**：
  - `include/uapi/linux/capability.h`：定义 `CAP_CHECKPOINT_RESTORE`（`40`），`CAP_LAST_CAP` 更新为 `CAP_CHECKPOINT_RESTORE`。
  - `include/linux/capability.h`：新增 `checkpoint_restore_ns_capable()`。
  - `security/selinux/include/classmap.h`：`COMMON_CAP2_PERMS` 增加 `"checkpoint_restore"`，并同步编译期上界断言。

#### 3. 充电与电量代码移植（实验性）

- 从 [`ZAKE-Z/android_kernel_OPPO_sm8250_GamepadDriver`](https://github.com/ZAKE-Z/android_kernel_OPPO_sm8250_GamepadDriver) 的 `stock/13.1`（`30b6a4f19`）引入 `drivers/power/oplus/` 对应文件，并移植 `drivers/power/supply/qcom/qpnp-fg-gen4.c`；目标树独有文件未删除。
- 充电、电量计、VOOC 等关键驱动已随设备配置编译；这不代表硬件、设备树、充电协议或电量显示已经验证，也不证明已修复此前异常。
- 模块支持 `CONFIG_MODULES=y` 原已启用，本构建保留强制模块签名。新生成的签名密钥与设备已有模块可能不兼容。
- 本次构建的 PS5 驱动与 Linux 7.3.5 稳定版作过对照，保留了仓库已有的 4.19 兼容层及自适应扳机、Edge 按键等定制。

### 已知问题 / 风险提示

- **充电异常（未确认原因）**：在 OPD2101 真机上曾出现过一次**无法充电、电量一直显示 1%**，之后又自行恢复。原因尚未定位，**不排除与内核的电源管理 / 充电 IC 驱动 / ColorOS 移植适配有关**；这是单次观察，不代表必然发生，也不等于已经确认由本 fork 改动导致。
- 建议：保留可回退的 boot 备份；若再次出现，记录发生时间、充电器与线材，并抓取 `dmesg` 以及 `/sys/class/power_supply/` 下的充电相关信息，便于后续定位。
- 手柄的 Switch 2 BLE、DualSense 自适应扳机等扩展功能均为实验性实现，**未经真机验证**，不应视为完整硬件支持。
- 实验构建存在 5 条未解析 BTF ID 警告、设备树输出目录缺失提示和 `depmod` 警告，尚未确认这些警告的来源及影响。

### 构建与测试

```bash
# 宿主机回归测试（11 项，含路由表、协议解码、LED 与 cleanup scope 检查）
python3 tools/testing/selftests/hid/gamepad_backport.py

# 编译手柄驱动目标文件 / 完整内核 Image（需要 aarch64 交叉工具链与 Clang）
OUT_DIR=$HOME/kbuild/opd2101-out bash build-gamepad.sh objects
OUT_DIR=$HOME/kbuild/opd2101-out bash build-gamepad.sh image
```

> 实验性 `boot.img` 基于设备上已有的 `boot-gamepad-cap40.img` 打包，保留其 ramdisk 与 DTB；与当前设备固件的匹配关系尚未独立核实。此仓库不包含 KernelSU 等第三方 Root 框架源码。

### 来源与许可

- 上游：[`toraidl/android_kernel_oneplus_sm8250`](https://github.com/toraidl/android_kernel_oneplus_sm8250)（`bpf-5.15-backport`，提交 `302ad9081`），GPL-2.0。
- HID 驱动快照与多色 LED 参考：`torvalds/linux`，GPL-2.0。
- 其他协议与解码参考列于 `Documentation/hid/gamepad-extended.rst`、`tools/testing/selftests/hid/gamepad-provenance.json` 与 `tools/gamepad/LICENSE.trevlars`（MIT）。

---

## English

### Scope

This repository is a **fork** of [`toraidl/android_kernel_oneplus_sm8250`](https://github.com/toraidl/android_kernel_oneplus_sm8250), from the `bpf-5.15-backport` branch at commit `302ad90819725ae7040524e75c293b493b4b751c` (Linux `4.19.325`).

- Target device: OPPO Pad **OPD2101** (`kona` / SM8250), running a third-party ColorOS 17 port (the stock device only officially supports up to ColorOS 14).
- This fork carries gamepad and browser compatibility changes and an experimental charging/battery backport. An experimental boot image is supplied as a Release asset.
- **Hardware testing has only been performed on OPPO Pad OPD2101**; compatibility with other devices is not established. The new charging backport and corresponding boot image have not yet been confirmed on hardware.
- The actual ROM kernel source for the device is not public. This fork makes **no claim** of being identical to the vendor or ROM author's kernel; all runtime conclusions require on-device verification.

### Changes

#### 1. Modern Gamepad Drivers & Multicolor LED Backports

Backported from an upstream Linux snapshot (`torvalds/linux` `7.4-rc2`, commit `9d66f26fefacebfeed15de31c1123451a17ff119`) and Linux `v5.10` LED support onto `4.19`:

- **PlayStation** (`drivers/hid/hid-playstation.c`, `drivers/hid/hid-sony.c`)
  - PS4 (USB / Bluetooth / Sony USB adapter), PS5 DualSense and DualSense Edge: input, touchpad, IMU, battery, lightbar, rumble.
  - DualSense Edge paddle/Fn key codes (new `BTN_GRIPL`, `BTN_GRIPR`, `BTN_GRIPL2`, `BTN_GRIPR2`).
  - Experimental `adaptive_triggers` sysfs interface with `tools/gamepad/dualsense-trigger.py`.
  - PS4 devices are routed through `hid-playstation` instead of `hid-sony` to avoid duplicate binding.
- **Nintendo Switch / Switch 2** (`drivers/hid/hid-nintendo.c`, `hid-nintendo.h`, `hid-nintendo-switch2-usb.c`)
  - Switch 1 Joy-Cons, Pro Controller, charging grip and supported NSO controllers with calibration, IMU, battery, LEDs, rumble and suspend/resume fixes.
  - Wired Switch 2 USB (`CONFIG_NINTENDO_SWITCH2_USB`) and an experimental userspace BLE GATT-to-UHID bridge (`CONFIG_NINTENDO_SWITCH2_BLE`); see `Documentation/hid/gamepad-extended.rst` and `tools/gamepad/android-switch2-bridge/`.
- **Microsoft, routing and 4.19 compatibility glue**
  - `hid-microsoft.c`, `hid-ids.h`, `hid-quirks.c`: additional device IDs, Bluetooth Xbox-compatible rumble and special-driver routing entries.
  - New `hid-gamepad-compat.h` and `hid-gamepad-protocol.h` provide driver-local cleanup scopes and protocol decoding without changing core 4.19 HID ABIs.
  - `drivers/hid/Kconfig` and `drivers/hid/Makefile` enable `-std=gnu11` only for the backported drivers.
- **Multicolor LED class** (`drivers/leds/led-class-multicolor.c`, `drivers/leds/Kconfig`, `drivers/leds/Makefile`, `include/linux/led-class-multicolor.h`, `include/dt-bindings/leds/common.h`)
  - Linux `v5.10` `LEDS_CLASS_MULTICOLOR` adapted to the `4.19` LED registration API for PlayStation RGB lightbars.
- **Configuration and tests** (`arch/arm64/configs/vendor/kona-perf_defconfig`, `gamepad-backport.config`, `tools/testing/selftests/hid/gamepad_backport.py`)
  - `CONFIG_NINTENDO_FF=y`, `CONFIG_NINTENDO_SWITCH2_USB=y` and `CONFIG_NINTENDO_SWITCH2_BLE=y` enabled in the default defconfig.

#### 2. Android 17 Native App Zygote Capability Fix (browser startup)

- **Cause**: Android 17's native App Zygote (`zygote_next` / `libzygote`) inspects capability bounding-set entries up to `40` (`CAP_CHECKPOINT_RESTORE`) during isolated child initialization. With a `4.19` kernel capped at `39` (`CAP_BPF`), `prctl(PR_CAPBSET_READ, 40)` returns `-EINVAL`, the Zygote child aborts with `SIGABRT`, Chromium sandbox/GPU children fail to start (Chrome and Edge hang or crash), and repeated failures occupy `system_server`'s shared process-start thread, slowing launches of other apps.
- **Fix**:
  - `include/uapi/linux/capability.h`: define `CAP_CHECKPOINT_RESTORE` (`40`) and bump `CAP_LAST_CAP`.
  - `include/linux/capability.h`: add `checkpoint_restore_ns_capable()`.
  - `security/selinux/include/classmap.h`: add `"checkpoint_restore"` to `COMMON_CAP2_PERMS` and update the compile-time bound check.

#### 3. Charging and battery backport (experimental)

- Import corresponding `drivers/power/oplus/` files and `drivers/power/supply/qcom/qpnp-fg-gen4.c` from [`ZAKE-Z/android_kernel_OPPO_sm8250_GamepadDriver`](https://github.com/ZAKE-Z/android_kernel_OPPO_sm8250_GamepadDriver) `stock/13.1` (`30b6a4f19`); target-only files remain in place.
- Key charger, gauge and VOOC objects compiled with the device configuration. Hardware, device-tree and charging compatibility, and any actual fix for the observed issue, remain unverified.
- `CONFIG_MODULES=y` was already enabled; forced module signatures remain enabled, so existing modules may not trust the newly generated key.
- The PS5 driver was compared with stable Linux 7.3.5 while retaining this tree's 4.19 compatibility and DualSense customizations.

### Known issues / caveats

- **Charging anomaly (cause unconfirmed)**: on the OPD2101 device, there was one observed episode where charging failed and the battery level stayed at 1%, then recovered by itself. The cause has not been identified; a kernel-related issue (power management / charging IC driver / ColorOS port adaptation) cannot be ruled out. This is a single observation and is **not** proof that this fork caused it.
- Keep a recoverable boot backup. If it recurs, note the time, charger and cable, and capture `dmesg` plus `/sys/class/power_supply/` information for debugging.
- Experimental controller features (Switch 2 BLE, DualSense adaptive triggers) are **not hardware-verified** and should not be treated as complete support.
- The experimental build emitted five unresolved BTF ID warnings, missing device-tree output directory messages, and a `depmod` warning; their origin and impact remain unconfirmed.

### Build & Test

```bash
# Host-side regression tests (11 checks: routing tables, protocol decoding, LED, cleanup scopes)
python3 tools/testing/selftests/hid/gamepad_backport.py

# Build gamepad objects or the full kernel Image (needs aarch64 cross toolchain and Clang)
OUT_DIR=$HOME/kbuild/opd2101-out bash build-gamepad.sh objects
OUT_DIR=$HOME/kbuild/opd2101-out bash build-gamepad.sh image
```

> The experimental `boot.img` was repacked using the device's existing `boot-gamepad-cap40.img`, retaining its ramdisk and DTB; a match to the currently running firmware has not been independently verified. Third-party root framework sources such as KernelSU are not included.

### Provenance & License

- Upstream: [`toraidl/android_kernel_oneplus_sm8250`](https://github.com/toraidl/android_kernel_oneplus_sm8250) (`bpf-5.15-backport`, commit `302ad9081`), GPL-2.0.
- HID driver snapshot and multicolor LED reference: `torvalds/linux`, GPL-2.0.
- Further protocol and decoder references are listed in `Documentation/hid/gamepad-extended.rst`, `tools/testing/selftests/hid/gamepad-provenance.json` and `tools/gamepad/LICENSE.trevlars` (MIT).
