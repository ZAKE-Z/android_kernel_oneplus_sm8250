#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
# Build validation only: never packages device trees or flashes a device.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
OUT_DIR="${OUT_DIR:-$HOME/kbuild/oppo-pad-gamepad}"
DEFCONFIG="${DEFCONFIG:-vendor/kona-perf_defconfig}"
JOBS="${JOBS:-4}"
KALLSYMS_EXTRA_PASS="${KALLSYMS_EXTRA_PASS:-1}"
MODE="${1:-objects}"

case "$MODE" in
objects|image) ;;
*) echo "Usage: $0 [objects|image]" >&2; exit 2 ;;
esac

export ARCH=arm64
export CROSS_COMPILE="${CROSS_COMPILE:-aarch64-linux-gnu-}"
export CROSS_COMPILE_ARM32="${CROSS_COMPILE_ARM32:-arm-linux-gnueabi-}"

mkdir -p -- "$OUT_DIR"
OUT_DIR="$(cd -- "$OUT_DIR" && pwd -P)"
cd "$ROOT"

if [[ ! -f "$OUT_DIR/.config" ]]; then
	if [[ -n "${KERNEL_CONFIG:-}" ]]; then
		cp -- "$KERNEL_CONFIG" "$OUT_DIR/.config"
	else
		make O="$OUT_DIR" CC=clang "$DEFCONFIG"
	fi
fi

ARCH=arm64 KCONFIG_CONFIG="$OUT_DIR/.config" \
	scripts/kconfig/merge_config.sh -m -O "$OUT_DIR" \
	"$OUT_DIR/.config" arch/arm64/configs/vendor/gamepad-backport.config
make O="$OUT_DIR" CC=clang olddefconfig

# Kconfig may silently drop requested features when dependencies are missing.
while IFS= read -r setting; do
	[[ "$setting" == CONFIG_*=y ]] || continue
	if ! grep -Fxq "$setting" "$OUT_DIR/.config"; then
		echo "Required controller setting was not enabled: $setting" >&2
		exit 1
	fi
done < arch/arm64/configs/vendor/gamepad-backport.config

python3 tools/testing/selftests/hid/gamepad_backport.py
make O="$OUT_DIR" CC=clang -j"$JOBS" \
	drivers/hid/hid-playstation.o drivers/hid/hid-nintendo.o \
	drivers/hid/hid-microsoft.o \
	drivers/hid/hid-sony.o drivers/hid/hid-quirks.o \
	drivers/leds/led-class-multicolor.o

if [[ "$MODE" == image ]]; then
	make O="$OUT_DIR" CC=clang KALLSYMS_EXTRA_PASS="$KALLSYMS_EXTRA_PASS" -j"$JOBS" Image
	echo "Built kernel Image: $OUT_DIR/arch/arm64/boot/Image"
	echo "Note: external KernelSU integration and boot.img repacking are not included in this helper."
fi
