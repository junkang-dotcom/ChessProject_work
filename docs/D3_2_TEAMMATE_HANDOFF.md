# D3 #2 시연용 전달 코드/명령어

## Git에 올릴 파일

```text
src/d3/d3_status_display.py
src/d3/send_status_line.py
src/d3/lcd_hello.py
src/d3/i2c_scan.py
docs/D3_2_TEAMMATE_HANDOFF.md
docs/d3_status_display.md
```

## D3 #2 JSON 메시지 형식

```json
{"type":"d3_status","payload":{"cmd":"READY"}}
{"type":"d3_status","payload":{"cmd":"TURN","turn":"white"}}
{"type":"d3_status","payload":{"cmd":"REQ","start":"A2","end":"A4","piece":"pawn"}}
{"type":"d3_status","payload":{"cmd":"MOVING","start":"A2","end":"A4"}}
{"type":"d3_status","payload":{"cmd":"DONE","start":"A2","end":"A4","next":"black"}}
{"type":"d3_status","payload":{"cmd":"INVALID","reason":"PIECE_MISMATCH","actual":"rook","requested":"bishop"}}
{"type":"d3_status","payload":{"cmd":"INVALID","reason":"WRONG_TURN","current":"black","piece":"white"}}
{"type":"d3_status","payload":{"cmd":"INVALID","reason":"PATH_BLOCKED"}}
{"type":"d3_status","payload":{"cmd":"CAPTURE","captured":"black_pawn"}}
{"type":"d3_status","payload":{"cmd":"REMOVING","square":"D4","slot":"CAP1_1"}}
{"type":"d3_status","payload":{"cmd":"FAIL","reason":"ROBOT_ERROR"}}
{"type":"d3_status","payload":{"cmd":"RESET"}}
```

## D3 #2 LCD 단독 테스트

```bash
cd ~/ChessProject_work
sudo python3 src/d3/lcd_hello.py \
  --i2c-bus 1 \
  --lcd-address 0x27 \
  --lcd-width 16 \
  --lcd-pinmap p0_rs_p2_en \
  --line1 "LCD OK" \
  --line2 "D3 STATUS"
```

## D3 #2 I2C scan

```bash
cd ~/ChessProject_work
sudo python3 src/d3/i2c_scan.py --bus 1
```

## D3 #2 시연 실행 명령

```bash
cd ~/ChessProject_work
sudo python3 src/d3/d3_status_display.py \
  --input serial \
  --serial-port /dev/ttyAMA2 \
  --baud 115200 \
  --lcd i2c \
  --i2c-bus 1 \
  --lcd-address 0x27 \
  --lcd-pinmap p0_rs_p2_en \
  --gpio-mode sysfs \
  --green-line 112 \
  --yellow-line 113 \
  --red-line 114 \
  --buzzer-line 121
```

## 팀원 PC 송신 테스트

```bash
cd ~/ChessProject_work
python3 src/d3/send_status_line.py --json REQ A2 A4 pawn --print-only

python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json READY
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json REQ A2 A4 pawn
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json MOVING A2 A4
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json DONE A2 A4 NEXT black
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json INVALID PATH_BLOCKED
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json FAIL ROBOT_ERROR
```

## raw JSON 직접 송신 테스트

```bash
python3 src/d3/send_status_line.py \
  --serial-port /dev/ttyUSB6 \
  --raw-json \
  '{"type":"d3_status","payload":{"cmd":"REQ","start":"A2","end":"A4","piece":"pawn"}}'
```

## PC에서 보드 없이 mock 테스트

```bash
printf '%s\n' \
  '{"type":"d3_status","payload":{"cmd":"READY"}}' \
  '{"type":"d3_status","payload":{"cmd":"REQ","start":"A2","end":"A4","piece":"pawn"}}' \
  '{"type":"d3_status","payload":{"cmd":"DONE","start":"A2","end":"A4","next":"black"}}' \
  '{"type":"d3_status","payload":{"cmd":"INVALID","reason":"PATH_BLOCKED"}}' | \
  python3 src/d3/d3_status_display.py --input stdin --lcd console --mock-gpio
```

## FastAPI에서 보낼 JSON 예시 코드

```python
import json
import serial


def send_d3_status(port, payload, baud=115200):
    message = {"type": "d3_status", "payload": payload}
    port.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
    port.flush()
    return port.readline().decode("utf-8", errors="replace").strip()


with serial.Serial("/dev/ttyUSB6", 115200, timeout=1) as d3_2:
    send_d3_status(d3_2, {"cmd": "REQ", "start": "A2", "end": "A4", "piece": "pawn"})
    send_d3_status(d3_2, {"cmd": "MOVING", "start": "A2", "end": "A4"})
    send_d3_status(d3_2, {"cmd": "DONE", "start": "A2", "end": "A4", "next": "black"})
```

## D3 #2 최신 코드 확인

```bash
grep -n "json" src/d3/d3_status_display.py
grep -n "normalize_status_line" src/d3/d3_status_display.py
grep -n "SysfsGpio" src/d3/d3_status_display.py
grep -n "termios" src/d3/d3_status_display.py
grep -n "lcd-pinmap" src/d3/d3_status_display.py
```
