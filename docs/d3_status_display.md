# TOPST D3 #2 상태 표시 보드

TOPST D3 #2는 UART로 JSON 상태 메시지를 받아 표시만 하는 보드다. 체스 규칙
검사와 Mirobot 제어는 하지 않는다. PC, FastAPI 서버, 또는 터미널 테스트
도구가 한 줄짜리 JSON 메시지를 보내면, D3 #2는 `payload.cmd`를 명령어로 해석해
LCD 문구, LED 상태, 부저 패턴을 갱신하고 가능하면 `OK`를 응답한다.
기존 plain-text 명령도 수동 테스트 호환용으로 계속 받을 수 있다.

## D3 #2에서 실행

D3 보드에서 직접 실행할 때는 TOPST UART 장치, I2C LCD, sysfs GPIO를 함께 사용한다.
실물 확인 기준 설정은 다음과 같다.

- LCD: 1602A + I2C backpack
- I2C: `/dev/i2c-1`, address `0x27`
- LCD width: `16`
- LCD pinmap: `p0_rs_p2_en`
- Green LED: sysfs GPIO `112`
- Yellow LED: sysfs GPIO `113`
- Red LED: sysfs GPIO `114`
- Buzzer: sysfs GPIO `121`

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

LCD 단독 테스트:

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

`i2cdetect`가 없거나 Python 패키지 설치가 어려운 환경에서는 내장 scanner를 쓴다.

```bash
sudo python3 src/d3/i2c_scan.py --bus 1
```

PC에서 GPIO 없이 동작만 확인할 때는 mock 모드를 쓴다.

```bash
printf "READY\nREQ A2 A4 pawn\nMOVING A2 A4\nDONE A2 A4 NEXT black\n" | \
  python3 src/d3/d3_status_display.py --input stdin --mock-gpio
```

D3 #2가 Docker/PC 호스트에 `/dev/ttyUSB6`으로 잡혔다면 한 줄 테스트는 다음처럼 보낼 수 있다.

```bash
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json READY
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json REQ A2 A4 pawn
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json DONE A2 A4 NEXT black
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 --json INVALID PATH_BLOCKED
```

## Linux 패키지 fallback

D3 #2 보드 Python 환경에서 별도 패키지가 없어도 돌아가도록 fallback이 들어 있다.

- `smbus2`/`smbus`가 없으면 `/dev/i2c-*` 직접 접근을 사용한다.
- `fcntl` 없이도 `ctypes` 기반 ioctl로 I2C slave address를 설정한다.
- `gpiod`가 없으면 sysfs GPIO를 사용한다.
- `pyserial`이 없으면 `termios` 기반 UART를 사용한다.

최신 파일이 맞는지 D3 보드에서 빠르게 확인할 때:

```bash
grep -n "ctypes" src/d3/d3_status_display.py
grep -n "SysfsGpio" src/d3/d3_status_display.py
grep -n "termios" src/d3/d3_status_display.py
grep -n "lcd-pinmap" src/d3/d3_status_display.py
```

## JSON 메시지

```json
{"type":"d3_status","payload":{"cmd":"REQ","start":"A2","end":"A4","piece":"pawn"}}
{"type":"d3_status","payload":{"cmd":"DONE","start":"A2","end":"A4","next":"black"}}
{"type":"d3_status","payload":{"cmd":"INVALID","reason":"PATH_BLOCKED"}}
```

## 명령별 표시

| 명령 | LCD 1줄 | LCD 2줄 | LED | 부저 |
| --- | --- | --- | --- | --- |
| `READY` | `READY` | `TURN WHITE` | 초록 | 없음 |
| `TURN white` | `TURN` | `white` | 초록 | 없음 |
| `REQ A2 A4 pawn` | `REQ pawn` | `A2 -> A4` | 노랑 점멸 | 짧게 1번 |
| `MOVING A2 A4` | `MOVING...` | `A2 -> A4` | 노랑 점멸 | 없음 |
| `DONE A2 A4 NEXT black` | `MOVE DONE` | `NEXT black` | 초록 | 짧게 2번 |
| `INVALID PIECE_MISMATCH actual=rook requested=bishop` | `INVALID MOVE` | `PIECE MISMATCH` | 빨강 | 길게 1번 |
| `INVALID WRONG_TURN current=black piece=white` | `WRONG TURN` | `TURN black` | 빨강 | 길게 1번 |
| `INVALID PATH_BLOCKED` | `PATH BLOCKED` | `MOVE DENIED` | 빨강 | 길게 1번 |
| `FAIL ROBOT_ERROR` | `ROBOT FAIL` | `CHECK ARM` | 빨강 점멸 | 길게 2번 |
| `CAPTURE black_pawn` | `CAPTURE` | `black_pawn` | 초록 점멸 | 짧게 3번 |
| `REMOVING D4 CAP1_1` | `REMOVING` | `D4 -> CAP1_1` | 노랑 | 없음 |
| `RESET` | `READY` | `WAITING` | 꺼짐 | 없음 |

## FastAPI 연동 위치

기존 로봇 이동 흐름 주변에서 다음 상태 메시지를 D3 #2로 보내면 된다.

1. D3 #1에 규칙 검사를 요청하기 전: `REQ {start} {end} {piece}`.
2. D3 #1이 이동을 거부했을 때: `INVALID {reason...}`.
3. D3 #1이 `OK ... PENDING`을 반환했을 때: `MOVING {start} {end}`.
4. capture가 있으면 제거 이동 전에: `CAPTURE {captured_piece}`,
   `REMOVING {target} {capture_slot}`.
5. 로봇 이동 성공 후 D3 #1에 COMMIT까지 끝났을 때:
   `DONE {start} {end} NEXT {turn}`.
6. 로봇 스크립트가 실패했을 때: `FAIL ROBOT_ERROR`.

D3 #2 표시 보드는 줄 단위 JSON 프로토콜을 사용한다. 한 줄마다 JSON object 하나를 보내고 끝에 newline을 붙인다.
