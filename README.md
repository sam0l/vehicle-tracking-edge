# Vehicle Tracking Edge

A modular Python system for robust vehicle tracking, sensor fusion, and edge AI sign detection.

---

## Project Structure

```text
vehicle-tracking-edge/
├── config/                # Configuration files (YAML)
├── models/                # ML models (e.g., YOLO ONNX)
├── src/                   # Core source code
│   ├── camera.py          # Camera interface
│   ├── gps.py             # GPS module (AT commands)
│   ├── imu.py             # IMU with dead reckoning
│   ├── sign_detection.py  # Sign detection (YOLO ONNX)
│   └── sim_monitor.py     # SIM/network monitor
├── tests/                 # Test and diagnostic scripts
│   ├── stress_test.py     # System stress/uptime test
│   └── test_sign_detection_server.py # REST API for sign detection
├── requirements.txt       # Python dependencies
├── main.py                # (Example) main application
├── config.yaml            # Main configuration
└── README.md              # This file
```

---

## Subsystems Overview

### 1. **Sign Detection**
- **File:** `src/sign_detection.py`
- **Purpose:** Detects traffic signs/lights using ONNX YOLO model.
- **Input:** Camera frames
- **Output:** Detected sign classes, bounding boxes

### 2. **GPS**
- **File:** `src/gps.py`
- **Purpose:** Reads GNSS data via AT commands (serial)
- **Output:** Latitude, longitude, speed (if available)

### 3. **IMU (with Dead Reckoning)**
- **File:** `src/imu.py`
- **Purpose:** Reads accelerometer/gyro, estimates speed, and performs dead reckoning when GPS is unavailable.
- **API:**
  - `update_gps(gps_data)` — update IMU with latest GPS
  - `get_speed()` — current speed (fused)
  - `get_position()` — current position (fused)

### 4. **Camera**
- **File:** `src/camera.py`
- **Purpose:** Captures frames for sign detection

### 5. **SIM Monitor**
- **File:** `src/sim_monitor.py`
- **Purpose:** Monitors SIM/network status, data usage

---

## Data Flow Diagram

```text
+---------+      +--------+      +-----+      +----------------+
| Camera  |----->| Sign   |----->|     |      |                |
|         |      |Detection|      |     |      |                |
+---------+      +--------+      |     |      |                |
                                 |     |      |                |
+---------+      +-----+         |     v      v                |
|  GPS    |----->| IMU |-------->|  Main Loop / App Logic      |
+---------+      +-----+         |   (Fusion, Logging, etc.)   |
                                 +-----------------------------+
| SIM/Net |----------------------------------->|
+---------+                                    |
```

- **IMU** fuses GPS and inertial data for robust speed/position.
- **Sign Detection** uses camera frames.
- **SIM Monitor** runs in parallel for connectivity.

---

## How to Run the Key Tests

### 1. **System Stress Test** (`tests/stress_test.py`)
- **Purpose:** Monitors uptime/health of all subsystems (GPS, IMU, Sign Detection, Internet)
- **Features:**
  - Logs per-second status to CSV
  - Prints summary to console
  - Supports early exit (press `x` + Enter)
  - Uses IMU's fused speed/position for health
- **Run:**
  ```bash
  python3 tests/stress_test.py
  ```
- **Config:** Duration and hardware settings in `config/config.yaml`

### 2. **Sign Detection Test Server** (`tests/test_sign_detection_server.py`)
- **Purpose:** REST API for live sign detection (for integration/UI testing)
- **Endpoints:**
  - `/health` — health check
  - `/detect` — run detection on a camera frame
  - `/video_feed` — MJPEG stream with detection boxes
- **Run:**
  ```bash
  python3 tests/test_sign_detection_server.py
  ```
- **Config:** Camera and server settings in `config/config.yaml`

---

## Configuration
- All hardware and test settings are in `config/config.yaml`.
- Edit this file to set camera device, IMU bus, GPS port, test duration, etc.

---

## Example: Subsystem Health Check (Pseudocode)

```python
# In your main loop or test:
gps_data = gps.get_data()
if gps_data:
    imu.update_gps(gps_data)
imu_data = imu.read_data()
speed = imu.get_speed()
position = imu.get_position()
```

---

## ASCII Illustration: Subsystem Interaction

```text
+--------+      +-----+      +-----+
| Camera |----->|Sign |      |     |
|        |      |Det. |      |     |
+--------+      +-----+      |     |
                             |     |
+-----+   +-----+            |     v
| GPS |-->| IMU |----------->| Main Loop
+-----+   +-----+            | (Fusion, Logging)
                             +-----+
| SIM/Net |------------------------>
+---------+
```

---

## Notes
- All code is Python 3.x.
- Designed for modularity and robustness.
- Extend or replace subsystems as needed for your hardware.

---

For more details, see code comments and each module's docstring. 