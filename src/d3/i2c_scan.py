#!/usr/bin/env python3
"""Dependency-free I2C address scanner for TOPST D3 bring-up."""

from __future__ import annotations

import argparse
import ctypes
import errno
import os
import time
from pathlib import Path


I2C_SLAVE = 0x0703


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan Linux /dev/i2c-* buses for responding addresses")
    parser.add_argument("--bus", type=int, default=None, help="scan only one bus, e.g. 1 for /dev/i2c-1")
    parser.add_argument("--start", type=lambda value: int(value, 0), default=0x03)
    parser.add_argument("--end", type=lambda value: int(value, 0), default=0x77)
    return parser.parse_args()


def bus_paths(bus: int | None) -> list[Path]:
    if bus is not None:
        return [Path(f"/dev/i2c-{bus}")]
    return sorted(Path("/dev").glob("i2c-*"), key=lambda path: int(path.name.split("-")[-1]))


def scan_bus(path: Path, start: int, end: int) -> list[int]:
    found: list[int] = []
    libc = ctypes.CDLL(None, use_errno=True)
    fd = os.open(str(path), os.O_RDWR)
    try:
        for addr in range(start, end + 1):
            try:
                result = libc.ioctl(fd, I2C_SLAVE, addr)
                if result < 0:
                    continue
                write_with_retry(fd, bytes([0]))
            except OSError:
                continue
            found.append(addr)
    finally:
        os.close(fd)
    return found


def write_with_retry(fd: int, data: bytes) -> None:
    for _ in range(3):
        try:
            os.write(fd, data)
            return
        except BlockingIOError:
            time.sleep(0.01)
        except OSError as exc:
            if exc.errno != errno.EAGAIN:
                raise
            time.sleep(0.01)
    os.write(fd, data)


def main() -> None:
    args = parse_args()
    for path in bus_paths(args.bus):
        if not path.exists():
            print(f"{path}: missing")
            continue
        try:
            found = scan_bus(path, args.start, args.end)
        except PermissionError:
            print(f"{path}: permission denied, run with sudo")
            continue
        except OSError as exc:
            print(f"{path}: {exc}")
            continue

        addresses = " ".join(f"0x{addr:02x}" for addr in found)
        print(f"{path}: {addresses if addresses else 'no devices'}")


if __name__ == "__main__":
    main()
