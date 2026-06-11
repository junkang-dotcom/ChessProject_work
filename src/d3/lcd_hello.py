#!/usr/bin/env python3
"""Standalone HD44780 I2C LCD smoke test for TOPST D3 #2."""

from __future__ import annotations

import argparse
import time

from d3_status_display import Hd44780I2cDisplay, parse_int_auto


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a two-line hello message to the D3 #2 I2C LCD")
    parser.add_argument("--i2c-bus", type=int, default=1)
    parser.add_argument("--lcd-address", type=parse_int_auto, default=None, help="LCD I2C address, e.g. 0x27")
    parser.add_argument("--lcd-width", type=int, default=16)
    parser.add_argument("--lcd-pinmap", choices=tuple(Hd44780I2cDisplay.PINMAPS), default="p0_rs_p2_en")
    parser.add_argument("--no-backlight", action="store_true")
    parser.add_argument("--line1", default="D3 #2 LCD OK")
    parser.add_argument("--line2", default="CHESS STATUS")
    parser.add_argument("--hold", type=float, default=5.0, help="Seconds to keep the message before clearing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lcd = Hd44780I2cDisplay(
        bus=args.i2c_bus,
        address=args.lcd_address,
        width=args.lcd_width,
        backlight=not args.no_backlight,
        pinmap=args.lcd_pinmap,
    )
    try:
        lcd.show(args.line1, args.line2)
        time.sleep(args.hold)
    finally:
        lcd.close()


if __name__ == "__main__":
    main()
