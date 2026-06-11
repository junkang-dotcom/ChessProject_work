#!/usr/bin/env python3
"""Send one status JSON or plain-text line to TOPST D3 #2 over UART."""

from __future__ import annotations

import argparse
import json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", nargs="+", help="status command, for example: REQ A2 A4 pawn")
    parser.add_argument("--serial-port", default="/dev/ttyUSB6")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--no-wait-ok", action="store_true")
    parser.add_argument("--json", action="store_true", help="wrap the command as a d3_status JSON message")
    parser.add_argument("--raw-json", action="store_true", help="send message as an already-formed JSON object")
    parser.add_argument("--print-only", action="store_true", help="print the line that would be sent, then exit")
    return parser.parse_args()


def command_to_payload(parts: list[str]) -> dict[str, object]:
    cmd = parts[0].upper()
    if cmd in {"READY", "RESET"}:
        return {"cmd": cmd}
    if cmd == "TURN" and len(parts) >= 2:
        return {"cmd": cmd, "turn": parts[1]}
    if cmd == "REQ" and len(parts) >= 4:
        return {"cmd": cmd, "start": parts[1], "end": parts[2], "piece": parts[3]}
    if cmd == "MOVING" and len(parts) >= 3:
        return {"cmd": cmd, "start": parts[1], "end": parts[2]}
    if cmd == "DONE" and len(parts) >= 3:
        payload: dict[str, object] = {"cmd": cmd, "start": parts[1], "end": parts[2]}
        if "NEXT" in parts:
            next_index = parts.index("NEXT") + 1
            if next_index < len(parts):
                payload["next"] = parts[next_index]
        return payload
    if cmd == "INVALID":
        payload = {"cmd": cmd, "reason": parts[1] if len(parts) >= 2 else "UNKNOWN"}
        for token in parts[2:]:
            if "=" in token:
                key, value = token.split("=", 1)
                payload[key] = value
        return payload
    if cmd == "FAIL":
        return {"cmd": cmd, "reason": parts[1] if len(parts) >= 2 else "ROBOT_ERROR"}
    if cmd == "CAPTURE":
        return {"cmd": cmd, "captured": parts[1] if len(parts) >= 2 else "piece"}
    if cmd == "REMOVING" and len(parts) >= 3:
        return {"cmd": cmd, "square": parts[1], "slot": parts[2]}
    return {"line": " ".join(parts)}


def build_line(args: argparse.Namespace) -> str:
    if args.raw_json:
        line = " ".join(args.message).strip()
        json.loads(line)
        return line
    if args.json:
        message = {"type": "d3_status", "payload": command_to_payload(args.message)}
        return json.dumps(message, separators=(",", ":"), ensure_ascii=False)
    return " ".join(args.message).strip()


def main() -> None:
    args = parse_args()
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required for UART. Install with: pip3 install pyserial") from exc

    line = build_line(args)
    if not line:
        raise SystemExit("message must not be empty")
    if args.print_only:
        print(line)
        return

    with serial.Serial(args.serial_port, args.baud, timeout=args.timeout_s) as port:
        port.write((line + "\n").encode("utf-8"))
        port.flush()
        print(f"sent: {line}")
        if not args.no_wait_ok:
            reply = port.readline().decode("utf-8", errors="replace").strip()
            print(f"reply: {reply or '<timeout>'}")


if __name__ == "__main__":
    main()
