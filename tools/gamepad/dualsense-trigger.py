#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build DualSense effects and submit through the serialized kernel sysfs ABI.

Protocol and effect packing: nowrep/dualsensectl, main.c (GPL-2.0-or-later),
snapshot d3ae2fa272e1bf9a5c08a0ded3f374b40f7c73ac. No firmware/flash writes.
"""
import argparse
from pathlib import Path


def bounded(value, minimum, maximum):
    value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"value must be {minimum}..{maximum}, got {value}")
    return value


def effect(mode, params):
    def args(*ranges):
        if len(params) != len(ranges):
            raise ValueError(f"{mode} expects {len(ranges)} parameters")
        return [bounded(v, *r) for v, r in zip(params, ranges)]

    def zones(values, frequency=0, code=0x21):
        active = sum(1 << i for i, v in enumerate(values) if v)
        packed = sum((v - 1) << (i * 3) for i, v in enumerate(values) if v)
        return bytes([code]) + active.to_bytes(2, "little") + packed.to_bytes(4, "little") + bytes([0, 0, frequency, 0])

    if mode == "off":
        args()
        return bytes([5]) + bytes(10)
    if mode in ("feedback", "vibration"):
        ranges = [(0, 9), (1, 8)] + ([(1, 255)] if mode == "vibration" else [])
        values = args(*ranges)
        pos, strength = values[:2]
        return zones([0] * pos + [strength] * (10 - pos),
                     values[2] if mode == "vibration" else 0,
                     0x26 if mode == "vibration" else 0x21)
    if mode in ("feedback-raw", "vibration-raw"):
        values = args(*([(0, 8)] * 10 + ([(1, 255)] if mode == "vibration-raw" else [])))
        return zones(values[:10], values[10] if len(values) == 11 else 0,
                     0x26 if mode == "vibration-raw" else 0x21)
    if mode == "weapon":
        start, stop, strength = args((2, 7), (3, 8), (1, 8))
        rest, code = [strength - 1], 0x25
    elif mode == "bow":
        start, stop, strength, snap = args((1, 8), (2, 8), (1, 8), (1, 8))
        rest, code = [(strength - 1) | ((snap - 1) << 3)], 0x22
    elif mode == "galloping":
        start, stop, first, second, freq = args((0, 8), (1, 9), (0, 6), (1, 7), (1, 255))
        if second <= first:
            raise ValueError("second foot must be greater than first")
        rest, code = [second | (first << 3), freq], 0x23
    elif mode == "machine":
        start, stop, a, b, freq, period = args((1, 8), (2, 9), (0, 7), (0, 7), (1, 255), (0, 255))
        rest, code = [a | (b << 3), freq, period], 0x27
    else:
        raise ValueError("unknown effect")
    if stop <= start:
        raise ValueError("stop must be greater than start")
    body = ((1 << start) | (1 << stop)).to_bytes(2, "little") + bytes(rest)
    return bytes([code]) + body + bytes(10 - len(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("side", choices=["left", "right", "both"])
    parser.add_argument("mode", choices=["off", "feedback", "weapon", "bow", "galloping", "machine", "vibration", "feedback-raw", "vibration-raw"])
    parser.add_argument("params", nargs="*", type=int)
    parser.add_argument("--device", type=Path, help="exact HID device directory or adaptive_triggers file")
    parser.add_argument("--dry-run", action="store_true", help="print 22-byte hex update without accessing a device")
    ns = parser.parse_args()
    try:
        value = effect(ns.mode, ns.params)
        if ns.dry_run:
            off = effect("off", [])
            print(((value if ns.side != "right" else off) + (value if ns.side != "left" else off)).hex())
            return
        paths = [ns.device] if ns.device else list(Path("/sys/bus/hid/devices").glob("*/adaptive_triggers"))
        paths = [p / "adaptive_triggers" if p.is_dir() else p for p in paths]
        if len(paths) != 1:
            raise ValueError("choose exactly one controller with --device")
        path = paths[0]
        # Read/modify/write of one side is not atomic across different clients.
        # The kernel update itself atomically submits both effects.
        previous = bytes.fromhex(path.read_text().strip())
        if len(previous) != 22:
            raise ValueError("unexpected kernel ABI")
        update = (value if ns.side != "right" else previous[:11]) + (value if ns.side != "left" else previous[11:])
        path.write_text(update.hex() + "\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
