import os
import sys
import time
import csv
import socket
import yaml
from datetime import datetime

# Ensure src is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from sign_detection import SignDetector
from camera import Camera
from gps import GPS
from imu import IMU

# Load config
with open(os.path.join(os.path.dirname(__file__), '../config/config.yaml'), 'r') as f:
    config = yaml.safe_load(f)

# Camera config
camera_cfg = config['camera']
# YOLO config for sign detection
sign_cfg = config['yolo']
# GPS config
gps_cfg = config['gps']
# IMU config
imu_cfg = config['imu']

# Helper: check internet connectivity
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

def main(duration_seconds=3600, csv_file="stress_test_log.csv"):
    # Initialize subsystems
    detector = SignDetector(config_path=os.path.join(os.path.dirname(__file__), '../config/config.yaml'))
    camera = Camera(
        device_id=camera_cfg.get('device_id', 0),
        width=camera_cfg.get('width', 640),
        height=camera_cfg.get('height', 360),
        fps=camera_cfg.get('fps', 30)
    )
    camera.initialize()
    gps = GPS(
        port=gps_cfg['port'],
        baudrate=gps_cfg['baudrate'],
        timeout=gps_cfg['timeout'],
        power_delay=gps_cfg['power_delay'],
        agps_delay=gps_cfg['agps_delay']
    )
    gps.initialize()
    imu = IMU(
        i2c_bus=imu_cfg['i2c_bus'],
        i2c_addresses=imu_cfg['i2c_addresses'],
        sample_rate=imu_cfg['sample_rate'],
        accel_range=imu_cfg['accel_range'],
        gyro_range=imu_cfg['gyro_range']
    )
    imu.initialize()

    subsystems = ["sign_detection", "internet", "gps", "imu"]
    status_log = []

    start_time = time.time()
    while (time.time() - start_time) < duration_seconds:
        timestamp = datetime.now().isoformat()
        # 1. Sign Detection
        try:
            frame = camera.get_frame()
            if frame is not None:
                detector.detect(frame)
                status_log.append([timestamp, "sign_detection", "working"])
            else:
                status_log.append([timestamp, "sign_detection", "not working"])
        except Exception:
            status_log.append([timestamp, "sign_detection", "not working"])
        # 2. Internet
        if check_internet():
            status_log.append([timestamp, "internet", "working"])
        else:
            status_log.append([timestamp, "internet", "not working"])
        # 3. GPS
        try:
            gps_data = gps.get_data()
            # Accept None if CGNSSINFO is empty (see your GPS logic)
            status_log.append([timestamp, "gps", "working"])
        except Exception:
            status_log.append([timestamp, "gps", "not working"])
        # 4. IMU
        try:
            imu_data = imu.read_data()
            if imu_data is not None:
                status_log.append([timestamp, "imu", "working"])
            else:
                status_log.append([timestamp, "imu", "not working"])
        except Exception:
            status_log.append([timestamp, "imu", "not working"])
        time.sleep(1)

    # Write to CSV
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "subsystem", "status"])
        writer.writerows(status_log)

    # Calculate and print uptime stats
    for subsystem in subsystems:
        total = sum(1 for row in status_log if row[1] == subsystem)
        up = sum(1 for row in status_log if row[1] == subsystem and row[2] == "working")
        down = total - up
        uptime_percent = (up / total) * 100 if total else 0
        print(f"{subsystem}: Uptime={up}s, Breakdown={down}s, Uptime%={uptime_percent:.2f}")

if __name__ == "__main__":
    main() 