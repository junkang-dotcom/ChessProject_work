# ChessProject D3 GPIO and AI-G Vision Reference

This repository contains a practical reference implementation for the chess-piece automatic movement project.

## Components

- `src/d3/d3_controller.py`: D3/TOPST Linux GPIO controller.
  - Reads START and RESET buttons.
  - Drives green/yellow/red LEDs and buzzer.
  - Runs a TCP server using newline-delimited JSON.
  - Maintains the D3 state machine.
- `src/d3/d3_status_display.py`: TOPST D3 #2 status display.
  - Receives one plain-text UART command per line.
  - Shows move status on an HD44780-compatible I2C LCD, LEDs, and buzzer.
  - Includes dependency fallbacks for direct `/dev/i2c-*`, sysfs GPIO, and termios UART.
  - Does not validate chess rules or control robot arms.
- `src/d3/lcd_hello.py`: standalone D3 #2 I2C LCD smoke test.
- `src/d3/i2c_scan.py`: dependency-free Linux I2C address scanner.
- `src/d3/send_status_line.py`: PC-side helper for sending one D3 #2 test line over UART.
- `src/aig/aig_vision_node.py`: AI-G vision node.
  - Captures a USB camera frame.
  - Locates the chessboard and applies perspective correction.
  - Segments the corrected board into an 8x8 coordinate space.
  - Runs YOLO detection and maps detections to chess squares.
  - Sends `SUCCESS` or `ERROR` to D3.
- `src/aig/mock_aig_result.py`: dependency-free mock sender for testing D3 without the AI-G board.
- `src/aig/capture_dataset.py`: AI-G camera image capture tool for YOLO dataset collection.
- `src/common/protocol.py`: shared JSON message helpers.
- `cpp/gpio_buttons.cpp`: implementation-focused D3 C++ controller using `/sys/class/gpio` and TCP JSON.
- UART uses the same newline-delimited JSON as TCP; D3 default device is `/dev/ttyAMA2` at `115200 8N1`.
- `docs/message_protocol.md`: JSON message format.
- `docs/d3_status_display.md`: plain-text D3 #2 status-display protocol.
- `docs/D3_2_TEAMMATE_HANDOFF.md`: handoff guide for running the D3 #2 display board on a teammate's PC/Linux setup.
- `docs/gpio_camera_notes.md`: wiring, run commands, and integration notes.

## Quick Test on One PC

Terminal 1:

```bash
python3 src/d3/d3_controller.py --mock-gpio --host 127.0.0.1 --port 5000
```

Terminal 2:

```bash
python3 src/aig/aig_vision_node.py --d3-host 127.0.0.1 --d3-port 5000 --model chess_yolo.pt --once --preview
```

In mock GPIO mode, type `s` or `r` followed by Enter in terminal 1 to simulate START and RESET.

To verify an actual commanded move instead of only checking that pieces were detected, start D3 with an expected move:

```bash
python3 src/d3/d3_controller.py --mock-gpio --host 127.0.0.1 --port 5000 --expected-move e2e4
```

AI-G returns `SUCCESS` only when `e2` is empty and `e4` contains a detected piece. Add `--expected-piece blue_block` if the target square must contain a specific YOLO class. Add `--move-piece white_pawn` when the YOLO class is a color block but the chess rule should be validated as a pawn.

Pawn rules are also checked. Examples:

```bash
# White pawn first move: two-square advance is valid from rank 2.
python3 src/d3/d3_controller.py --mock-gpio --expected-move e2e4 --expected-piece blue_block --move-piece white_pawn

# White pawn capture: diagonal movement requires a captured target.
python3 src/d3/d3_controller.py --mock-gpio --expected-move e2f3 --expected-piece blue_block --move-piece white_pawn --expected-capture true
```

AI-G can also double-check square occupancy with OpenCV color masks:

```bash
python3 src/aig/aig_vision_node.py \
  --d3-host 127.0.0.1 \
  --d3-port 5000 \
  --model block_yolo.pt \
  --opencv-occupancy \
  --require-opencv-occupancy
```

Depth occupancy is prepared for an aligned 16-bit depth image or `.npy` frame:

```bash
python3 src/aig/aig_vision_node.py \
  --model block_yolo.pt \
  --depth-image depth_current.npy \
  --depth-baseline depth_empty_board.npy \
  --require-depth-occupancy
```

Depth frames must already be aligned to the RGB board camera view before AI-G applies the same perspective transform.

To test D3 result handling without camera/YOLO:

```bash
python3 src/aig/mock_aig_result.py --d3-host 127.0.0.1 --status SUCCESS
python3 src/aig/mock_aig_result.py --d3-host 127.0.0.1 --status ERROR
```

## Message Flow

1. D3 detects `START` and enters `WAITING_RESULT`.
2. D3 sends `d3_event`.
3. AI-G captures the board, preprocesses the image, runs YOLO, and maps pieces to squares.
4. AI-G sends `aig_result` with `status: "SUCCESS"` or `status: "ERROR"`.
5. D3 updates LEDs and buzzer according to the result.

See [docs/message_protocol.md](docs/message_protocol.md) for the exact JSON schema.

## TOPST D3 #2 Status Display

The tested D3 #2 hardware uses a 1602A LCD with I2C backpack at `/dev/i2c-1`
address `0x27`, LCD pinmap `p0_rs_p2_en`, and sysfs GPIO lines
`112/113/114/121` for green/yellow/red/buzzer.

Run on D3 #2:

```bash
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

Send a PC-side test line when D3 #2 appears as `/dev/ttyUSB6`:

```bash
python3 src/d3/send_status_line.py --serial-port /dev/ttyUSB6 REQ A2 A4 pawn
```

See [docs/d3_status_display.md](docs/d3_status_display.md) for LCD hello,
I2C scan, and the full plain-text status protocol.

## AI-G Dataset Capture

Check the camera and collect raw training images on AI-G:

```bash
ls /dev/video*
python3 src/aig/capture_dataset.py --device 2 --label chess --output-dir dataset_raw
```

See [docs/README_AIG_CAMERA.md](docs/README_AIG_CAMERA.md) for the capture, labeling, and YOLO training workflow.

## D3 C++ Build

The C++ implementation does not require `libgpiod`; it follows the GPIO sysfs style used in the class practice material.

```bash
$CXX -std=c++17 -O2 -pthread -o gpio_buttons cpp/gpio_buttons.cpp
sudo ./gpio_buttons --port 5000
```

Change GPIO numbers to match the actual D3 pin map:

```bash
sudo ./gpio_buttons \
  --start 84 --reset 85 \
  --green 112 --yellow 113 --red 114 --buzzer 121 \
  --port 5000
```

For D3-to-AI-G UART JSON:

```bash
sudo ./gpio_buttons \
  --start 84 --reset 85 \
  --green 112 --yellow 113 --red 114 --buzzer 121 \
  --uart /dev/ttyAMA2 --baud 115200 --port 0
```
