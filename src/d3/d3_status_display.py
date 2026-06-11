#!/usr/bin/env python3
"""TOPST D3 #2 status display.

Receives one plain-text status command per line from stdin or UART, then updates
an HD44780-compatible I2C LCD plus LED/buzzer GPIO outputs.
"""

from __future__ import annotations

import argparse
import errno
import json
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Protocol, TextIO


DEFAULT_TURN = "WHITE"
SELF_TEST_LINES = (
    '{"type":"d3_status","payload":{"cmd":"READY"}}',
    '{"type":"d3_status","payload":{"cmd":"REQ","start":"A2","end":"A4","piece":"pawn"}}',
    '{"type":"d3_status","payload":{"cmd":"MOVING","start":"A2","end":"A4"}}',
    '{"type":"d3_status","payload":{"cmd":"DONE","start":"A2","end":"A4","next":"black"}}',
    '{"type":"d3_status","payload":{"cmd":"INVALID","reason":"PATH_BLOCKED"}}',
    '{"type":"d3_status","payload":{"cmd":"FAIL","reason":"ROBOT_ERROR"}}',
)


@dataclass(frozen=True)
class GpioConfig:
    chip: str = "/dev/gpiochip0"
    green_line: int | None = None
    yellow_line: int | None = None
    red_line: int | None = None
    buzzer_line: int | None = None


class ConsoleGpio:
    def set_leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        print(f"[gpio] green={green} yellow={yellow} red={red}")

    def set_buzzer(self, on: bool) -> None:
        print(f"[gpio] buzzer={on}")

    def close(self) -> None:
        pass


class NoopGpio:
    def set_leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        pass

    def set_buzzer(self, on: bool) -> None:
        pass

    def close(self) -> None:
        pass


class LinuxGpio:
    def __init__(self, config: GpioConfig) -> None:
        try:
            import gpiod
        except ImportError as exc:
            raise RuntimeError("python gpiod package is required, or run with --mock-gpio") from exc

        self.config = config
        self.lines = [
            line
            for line in (config.green_line, config.yellow_line, config.red_line, config.buzzer_line)
            if line is not None
        ]
        self.values: dict[int, int] = {line: 0 for line in self.lines}
        self.request = gpiod.request_lines(
            config.chip,
            consumer="chess-d3-status-display",
            config={line: gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT) for line in self.lines},
        )
        self.set_leds()
        self.set_buzzer(False)

    def _set_line(self, line: int | None, value: bool) -> None:
        if line is None:
            return
        self.values[line] = int(value)
        self.request.set_value(line, int(value))

    def set_leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        self._set_line(self.config.green_line, green)
        self._set_line(self.config.yellow_line, yellow)
        self._set_line(self.config.red_line, red)

    def set_buzzer(self, on: bool) -> None:
        self._set_line(self.config.buzzer_line, on)

    def close(self) -> None:
        self.set_leds()
        self.set_buzzer(False)
        release = getattr(self.request, "release", None)
        if callable(release):
            release()


class SysfsGpio:
    def __init__(self, config: GpioConfig) -> None:
        self.config = config
        self.lines = [
            line
            for line in (config.green_line, config.yellow_line, config.red_line, config.buzzer_line)
            if line is not None
        ]
        for line in self.lines:
            self._export(line)
            self._write_text(f"/sys/class/gpio/gpio{line}/direction", "out")
        self.set_leds()
        self.set_buzzer(False)

    @staticmethod
    def _write_text(path: str, value: str) -> None:
        with open(path, "w", encoding="ascii") as out:
            out.write(value)

    def _export(self, line: int) -> None:
        if not os_path_exists(f"/sys/class/gpio/gpio{line}"):
            self._write_text("/sys/class/gpio/export", str(line))

    def _set_line(self, line: int | None, value: bool) -> None:
        if line is None:
            return
        self._write_text(f"/sys/class/gpio/gpio{line}/value", "1" if value else "0")

    def set_leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        self._set_line(self.config.green_line, green)
        self._set_line(self.config.yellow_line, yellow)
        self._set_line(self.config.red_line, red)

    def set_buzzer(self, on: bool) -> None:
        self._set_line(self.config.buzzer_line, on)

    def close(self) -> None:
        self.set_leds()
        self.set_buzzer(False)


class GpioOutput(Protocol):
    def set_leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        ...

    def set_buzzer(self, on: bool) -> None:
        ...

    def close(self) -> None:
        ...


class OutputEffects:
    def __init__(self, gpio: GpioOutput, activity_color: str = "yellow") -> None:
        self.gpio = gpio
        self.activity_color = activity_color
        self._blink_stop = threading.Event()
        self._blink_thread: threading.Thread | None = None

    def stop_blink(self) -> None:
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_stop.set()
            self._blink_thread.join(timeout=1.0)
        self._blink_thread = None
        self._blink_stop = threading.Event()

    def leds(self, green: bool = False, yellow: bool = False, red: bool = False) -> None:
        self.stop_blink()
        self.gpio.set_leds(green=green, yellow=yellow, red=red)

    def blink(self, color: str, interval: float = 0.35) -> None:
        self.stop_blink()

        def loop() -> None:
            on = False
            while not self._blink_stop.is_set():
                on = not on
                self.gpio.set_leds(
                    green=on and color == "green",
                    yellow=on and color == "yellow",
                    red=on and color == "red",
                )
                time.sleep(interval)

        self._blink_thread = threading.Thread(target=loop, daemon=True)
        self._blink_thread.start()

    def flash(self, color: str, count: int = 1, interval: float = 0.12) -> None:
        self.stop_blink()
        for _ in range(count):
            self.gpio.set_leds(
                green=color == "green",
                yellow=color == "yellow",
                red=color == "red",
            )
            time.sleep(interval)
            self.gpio.set_leds()
            time.sleep(interval)

    def beep(self, count: int = 1, duration: float = 0.08, gap: float = 0.08) -> None:
        for _ in range(count):
            self.gpio.set_buzzer(True)
            time.sleep(duration)
            self.gpio.set_buzzer(False)
            time.sleep(gap)

    def close(self) -> None:
        self.stop_blink()
        self.gpio.close()


class LcdDisplay:
    def __init__(self, width: int = 16) -> None:
        self.width = width

    def show(self, line1: str, line2: str = "") -> None:
        print(f"[lcd] {line1[:self.width]:<{self.width}} | {line2[:self.width]:<{self.width}}")

    def close(self) -> None:
        pass


class NoopDisplay(LcdDisplay):
    def show(self, line1: str, line2: str = "") -> None:
        pass


class Hd44780I2cDisplay(LcdDisplay):
    I2C_SLAVE = 0x0703
    LCD_CHR = 0x01
    LCD_CMD = 0x00
    LINE_ADDR = (0x80, 0xC0, 0x94, 0xD4)
    PINMAPS = {
        "p0_rs_p2_en": {"rs": 0x01, "en": 0x04, "bl": 0x08, "data": "high"},
        "p4_rs_p6_en": {"rs": 0x10, "en": 0x40, "bl": 0x80, "data": "low"},
    }

    def __init__(
        self,
        bus: int,
        address: int | None,
        width: int = 16,
        backlight: bool = True,
        pinmap: str = "p0_rs_p2_en",
    ) -> None:
        super().__init__(width=width)
        if pinmap not in self.PINMAPS:
            raise RuntimeError(f"unsupported LCD pinmap: {pinmap}")
        self.bus_no = bus
        self.address = address
        self.pinmap = self.PINMAPS[pinmap]
        self.backlight = self.pinmap["bl"] if backlight else 0x00
        self.bus = self._open_bus(bus)
        if self.address is None:
            self.address = self._detect_address()
        self._init_lcd()

    @staticmethod
    def _open_bus(bus: int):
        try:
            from smbus2 import SMBus
            return SMBus(bus)
        except ImportError:
            try:
                from smbus import SMBus  # type: ignore
                return SMBus(bus)
            except ImportError as exc:
                return LinuxI2cBus(bus)

    def _detect_address(self) -> int:
        candidates = tuple(range(0x20, 0x28)) + tuple(range(0x38, 0x40))
        for candidate in candidates:
            try:
                self.bus.read_byte(candidate)
                return candidate
            except OSError:
                continue
        raise RuntimeError(
            "No HD44780 I2C backpack found in 0x20-0x27 or 0x38-0x3F. "
            "Check with i2cdetect and pass --lcd-address."
        )

    def _write_byte(self, value: int) -> None:
        assert self.address is not None
        self.bus.write_byte(self.address, value | self.backlight)

    def _toggle_enable(self, value: int) -> None:
        enable = int(self.pinmap["en"])
        time.sleep(0.0005)
        self._write_byte(value | enable)
        time.sleep(0.0005)
        self._write_byte(value & ~enable)
        time.sleep(0.0001)

    def _write4(self, bits: int, mode: int) -> None:
        if self.pinmap["data"] == "low":
            value = (bits >> 4) & 0x0F
        else:
            value = bits & 0xF0
        if mode == self.LCD_CHR:
            value |= int(self.pinmap["rs"])
        self._write_byte(value)
        self._toggle_enable(value)

    def _send(self, value: int, mode: int) -> None:
        self._write4(value & 0xF0, mode)
        self._write4((value << 4) & 0xF0, mode)

    def _init_lcd(self) -> None:
        time.sleep(0.05)
        for value in (0x33, 0x32, 0x28, 0x0C, 0x06, 0x01):
            self._send(value, self.LCD_CMD)
            time.sleep(0.005)

    def show(self, line1: str, line2: str = "") -> None:
        for row, text in enumerate((line1, line2)):
            self._send(self.LINE_ADDR[row], self.LCD_CMD)
            padded = text[: self.width].ljust(self.width)
            for char in padded:
                self._send(ord(char), self.LCD_CHR)

    def close(self) -> None:
        try:
            self.show("", "")
        finally:
            close = getattr(self.bus, "close", None)
            if callable(close):
                close()


class LinuxI2cBus:
    """Minimal /dev/i2c-* fallback when smbus/smbus2 is unavailable."""

    def __init__(self, bus: int) -> None:
        import ctypes
        import os

        self._os = os
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._ctypes = ctypes
        self._fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)

    def _select(self, address: int) -> None:
        result = self._libc.ioctl(self._fd, Hd44780I2cDisplay.I2C_SLAVE, address)
        if result < 0:
            errno = self._ctypes.get_errno()
            raise OSError(errno, self._os.strerror(errno))

    def read_byte(self, address: int) -> int:
        self._select(address)
        self._write_with_retry(b"\x00")
        return 0

    def write_byte(self, address: int, value: int) -> None:
        self._select(address)
        self._write_with_retry(bytes([value & 0xFF]))

    def _write_with_retry(self, data: bytes) -> None:
        for _ in range(5):
            try:
                self._os.write(self._fd, data)
                return
            except BlockingIOError:
                time.sleep(0.01)
            except OSError as exc:
                if exc.errno != errno.EAGAIN:
                    raise
                time.sleep(0.01)
        self._os.write(self._fd, data)

    def close(self) -> None:
        self._os.close(self._fd)


def normalize_status_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line.startswith("{"):
        return line

    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(message, dict):
        raise ValueError("JSON message must be an object")

    payload = message.get("payload", message)
    if not isinstance(payload, dict):
        raise ValueError("JSON payload must be an object")

    if "line" in payload:
        return str(payload["line"]).strip()
    if "message" in payload:
        return str(payload["message"]).strip()
    if "status" in payload and "cmd" not in payload and "command" not in payload:
        return str(payload["status"]).strip()

    cmd = str(payload.get("cmd", payload.get("command", ""))).strip().upper()
    if not cmd:
        raise ValueError("JSON payload requires cmd or command")

    if cmd in {"READY", "RESET"}:
        return cmd
    if cmd == "TURN":
        return f"TURN {payload.get('turn', '')}".strip()
    if cmd == "REQ":
        return f"REQ {payload.get('start', '')} {payload.get('end', '')} {payload.get('piece', '')}".strip()
    if cmd == "MOVING":
        return f"MOVING {payload.get('start', '')} {payload.get('end', '')}".strip()
    if cmd == "DONE":
        base = f"DONE {payload.get('start', '')} {payload.get('end', '')}".strip()
        next_turn = payload.get("next", payload.get("next_turn"))
        return f"{base} NEXT {next_turn}".strip() if next_turn else base
    if cmd == "INVALID":
        reason = str(payload.get("reason", "UNKNOWN")).upper()
        extras = []
        for key in ("actual", "requested", "current", "piece"):
            if key in payload:
                extras.append(f"{key}={payload[key]}")
        return " ".join(["INVALID", reason, *extras]).strip()
    if cmd == "FAIL":
        return f"FAIL {payload.get('reason', 'ROBOT_ERROR')}".strip()
    if cmd == "CAPTURE":
        return f"CAPTURE {payload.get('captured', payload.get('piece', 'piece'))}".strip()
    if cmd == "REMOVING":
        return f"REMOVING {payload.get('square', payload.get('start', ''))} {payload.get('slot', payload.get('end', ''))}".strip()
    raise ValueError(f"unknown JSON cmd: {cmd}")


def parse_status_line(raw_line: str) -> tuple[str, str]:
    tokens = normalize_status_line(raw_line).split()
    if not tokens:
        return "", ""

    command = tokens[0].upper()
    if command == "READY":
        return "READY", f"TURN {DEFAULT_TURN}"
    if command == "TURN" and len(tokens) >= 2:
        return "TURN", tokens[1]
    if command == "REQ" and len(tokens) >= 4:
        return f"REQ {tokens[3]}", f"{tokens[1]} -> {tokens[2]}"
    if command == "MOVING" and len(tokens) >= 3:
        return "MOVING...", f"{tokens[1]} -> {tokens[2]}"
    if command == "DONE":
        next_turn = tokens[tokens.index("NEXT") + 1] if "NEXT" in tokens and tokens.index("NEXT") + 1 < len(tokens) else ""
        return "MOVE DONE", f"NEXT {next_turn}".strip()
    if command == "INVALID":
        reason = tokens[1].upper() if len(tokens) >= 2 else ""
        if reason == "PIECE_MISMATCH":
            return "INVALID MOVE", "PIECE MISMATCH"
        if reason == "WRONG_TURN":
            current = _kv_value(tokens[2:], "current") or ""
            return "WRONG TURN", f"TURN {current}".strip()
        if reason == "PATH_BLOCKED":
            return "PATH BLOCKED", "MOVE DENIED"
        return "INVALID MOVE", reason.replace("_", " ")
    if command == "FAIL":
        reason = tokens[1].upper() if len(tokens) >= 2 else ""
        if reason == "ROBOT_ERROR":
            return "ROBOT FAIL", "CHECK ARM"
        return "FAIL", reason.replace("_", " ")
    if command == "CAPTURE" and len(tokens) >= 2:
        return "CAPTURE", tokens[1]
    if command == "REMOVING" and len(tokens) >= 3:
        return "REMOVING", f"{tokens[1]} -> {tokens[2]}"
    if command == "RESET":
        return "RESET", "TURN WHITE"
    return command, " ".join(tokens[1:])


def _kv_value(tokens: Iterable[str], key: str) -> str | None:
    prefix = f"{key}="
    for token in tokens:
        if token.startswith(prefix):
            return token[len(prefix) :]
    return None


def apply_effects(raw_line: str, effects: OutputEffects) -> None:
    tokens = normalize_status_line(raw_line).split()
    command = tokens[0].upper() if tokens else ""
    reason = tokens[1].upper() if len(tokens) >= 2 else ""

    if command in {"READY", "RESET", "TURN"}:
        effects.leds(green=command == "READY")
    elif command == "REQ":
        effects.flash(effects.activity_color, count=1)
        effects.beep(count=1, duration=0.08)
    elif command == "MOVING":
        effects.blink(effects.activity_color)
    elif command == "DONE":
        effects.leds(green=True)
        effects.beep(count=2, duration=0.08)
    elif command == "INVALID":
        effects.leds(red=True)
        effects.beep(count=1, duration=0.35)
    elif command == "FAIL":
        effects.blink("red")
        effects.beep(count=2, duration=0.35, gap=0.12)
    elif command == "CAPTURE":
        effects.flash("green", count=3)
        effects.beep(count=3, duration=0.08)
    elif command == "REMOVING":
        effects.blink("green")
    else:
        effects.leds(red=reason != "")


def iter_stdin_lines(stream: TextIO) -> Iterable[str]:
    for line in stream:
        yield line


def iter_serial_lines(port: str, baud: int) -> Iterable[str]:
    try:
        import serial
    except ImportError as exc:
        yield from iter_termios_serial_lines(port, baud)
        return

    with serial.Serial(port, baudrate=baud, timeout=1) as ser:
        while True:
            line = ser.readline()
            if not line:
                continue
            yield line.decode("utf-8", errors="replace")


def baud_to_termios(baud: int) -> int:
    import termios

    mapping = {
        9600: termios.B9600,
        19200: termios.B19200,
        38400: termios.B38400,
        57600: termios.B57600,
        115200: termios.B115200,
    }
    if baud not in mapping:
        raise RuntimeError(f"unsupported baud for termios fallback: {baud}")
    return mapping[baud]


def configure_termios(fd: int, baud: int) -> None:
    import termios

    attrs = termios.tcgetattr(fd)
    speed = baud_to_termios(baud)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = speed
    attrs[5] = speed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def iter_termios_serial_lines(port: str, baud: int) -> Iterable[str]:
    import os

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        configure_termios(fd, baud)
        buffer = bytearray()
        while True:
            chunk = os.read(fd, 1)
            if not chunk:
                continue
            if chunk == b"\n":
                yield buffer.decode("utf-8", errors="replace")
                buffer.clear()
            elif chunk != b"\r":
                buffer.extend(chunk)
    finally:
        os.close(fd)


def run_display_loop(lines: Iterable[str], lcd: LcdDisplay, effects: OutputEffects, reply: TextIO) -> None:
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            line1, line2 = parse_status_line(line)
            lcd.show(line1, line2)
            apply_effects(line, effects)
            print("OK", file=reply, flush=True)
        except ValueError as exc:
            lcd.show("JSON ERROR", str(exc)[:16])
            effects.leds(red=True)
            effects.beep(count=1, duration=0.35)
            print(f"ERR {exc}", file=reply, flush=True)


def run_serial_display_loop(port: str, baud: int, lcd: LcdDisplay, effects: OutputEffects) -> None:
    try:
        import serial
    except ImportError:
        run_termios_serial_display_loop(port, baud, lcd, effects)
        return

    with serial.Serial(port, baudrate=baud, timeout=1) as ser:
        while True:
            raw_line = ser.readline()
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                line1, line2 = parse_status_line(line)
                lcd.show(line1, line2)
                apply_effects(line, effects)
                ser.write(b"OK\n")
            except ValueError as exc:
                lcd.show("JSON ERROR", str(exc)[:16])
                effects.leds(red=True)
                effects.beep(count=1, duration=0.35)
                ser.write(f"ERR {exc}\n".encode("utf-8"))
            ser.flush()


def run_termios_serial_display_loop(port: str, baud: int, lcd: LcdDisplay, effects: OutputEffects) -> None:
    import os

    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    try:
        configure_termios(fd, baud)
        buffer = bytearray()
        while True:
            chunk = os.read(fd, 1)
            if not chunk:
                continue
            if chunk == b"\n":
                line = buffer.decode("utf-8", errors="replace").strip()
                buffer.clear()
                if not line:
                    continue
                try:
                    line1, line2 = parse_status_line(line)
                    lcd.show(line1, line2)
                    apply_effects(line, effects)
                    os.write(fd, b"OK\n")
                except ValueError as exc:
                    lcd.show("JSON ERROR", str(exc)[:16])
                    effects.leds(red=True)
                    effects.beep(count=1, duration=0.35)
                    os.write(fd, f"ERR {exc}\n".encode("utf-8"))
            elif chunk != b"\r":
                buffer.extend(chunk)
    finally:
        os.close(fd)


def run_self_test(lcd: LcdDisplay, effects: OutputEffects) -> None:
    for line in SELF_TEST_LINES:
        line1, line2 = parse_status_line(line)
        print(f"[self-test] {line}")
        lcd.show(line1, line2)
        apply_effects(line, effects)
        time.sleep(0.8)


def parse_int_auto(value: str) -> int:
    return int(value, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TOPST D3 #2 status LCD/LED/buzzer display")
    parser.add_argument("--input", choices=("stdin", "serial"), default="stdin")
    parser.add_argument("--serial-port", default="/dev/ttyAMA2")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--lcd", choices=("console", "i2c", "off"), default="console")
    parser.add_argument("--lcd-width", type=int, default=16)
    parser.add_argument("--i2c-bus", type=int, default=1)
    parser.add_argument("--lcd-address", type=parse_int_auto, default=None, help="LCD I2C address, e.g. 0x27")
    parser.add_argument("--lcd-pinmap", choices=tuple(Hd44780I2cDisplay.PINMAPS), default="p0_rs_p2_en")
    parser.add_argument("--no-backlight", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="run LCD/LED/buzzer status sequence once, then exit")
    parser.add_argument("--mock-gpio", action="store_true")
    parser.add_argument("--gpio-mode", choices=("auto", "gpiod", "sysfs"), default="auto")
    parser.add_argument("--gpiochip", default="/dev/gpiochip0")
    parser.add_argument("--green-line", type=int, default=None)
    parser.add_argument("--yellow-line", type=int, default=None)
    parser.add_argument("--red-line", type=int, default=None)
    parser.add_argument("--buzzer-line", type=int, default=None)
    return parser.parse_args()


def build_lcd(args: argparse.Namespace) -> LcdDisplay:
    if args.lcd == "off":
        return NoopDisplay(width=args.lcd_width)
    if args.lcd == "i2c":
        return Hd44780I2cDisplay(
            bus=args.i2c_bus,
            address=args.lcd_address,
            width=args.lcd_width,
            backlight=not args.no_backlight,
            pinmap=args.lcd_pinmap,
        )
    return LcdDisplay(width=args.lcd_width)


def os_path_exists(path: str) -> bool:
    try:
        import os

        return os.path.exists(path)
    except OSError:
        return False


def build_gpio(args: argparse.Namespace) -> ConsoleGpio | NoopGpio | LinuxGpio | SysfsGpio:
    config = GpioConfig(
        chip=args.gpiochip,
        green_line=args.green_line,
        yellow_line=args.yellow_line,
        red_line=args.red_line,
        buzzer_line=args.buzzer_line,
    )
    if args.mock_gpio:
        return ConsoleGpio()
    if all(line is None for line in (config.green_line, config.yellow_line, config.red_line, config.buzzer_line)):
        return NoopGpio()
    if args.gpio_mode == "sysfs":
        return SysfsGpio(config)
    if args.gpio_mode == "gpiod":
        return LinuxGpio(config)
    try:
        return LinuxGpio(config)
    except RuntimeError as exc:
        if "gpiod" not in str(exc):
            raise
        return SysfsGpio(config)


def choose_activity_color(args: argparse.Namespace) -> str:
    if args.mock_gpio or args.yellow_line is not None:
        return "yellow"
    if args.green_line is not None:
        return "green"
    return "yellow"


def main() -> None:
    args = parse_args()
    lcd = build_lcd(args)
    effects = OutputEffects(build_gpio(args), activity_color=choose_activity_color(args))

    try:
        if args.self_test:
            run_self_test(lcd, effects)
        elif args.input == "serial":
            run_serial_display_loop(args.serial_port, args.baud, lcd, effects)
        else:
            run_display_loop(iter_stdin_lines(sys.stdin), lcd, effects, sys.stdout)
    except KeyboardInterrupt:
        pass
    finally:
        effects.close()
        lcd.close()


if __name__ == "__main__":
    main()
