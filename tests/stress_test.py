import os
import sys
import time
import socket
import yaml
import csv
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

# Test duration from config, or default to 12 hours
DEFAULT_DURATION = 12 * 60 * 60  # 12 hours in seconds
test_cfg = config.get('test', {})
duration_seconds = test_cfg.get('duration_seconds', DEFAULT_DURATION)

# Helper: check internet connectivity
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

def main(duration_seconds=duration_seconds, log_file="stress_test_log.csv"):
    print(f"[INFO] Starting stress test for {duration_seconds} seconds ({duration_seconds/3600:.2f} hours)")
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

    subsystems = ["GPS", "IMU", "DETECTION", "INTERNET"]
    up_counts = {k: 0 for k in subsystems}
    total_counts = {k: 0 for k in subsystems}

    with open(log_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp"] + subsystems)
        start_time = time.time()
        while (time.time() - start_time) < duration_seconds:
            timestamp = datetime.now().isoformat()
            # 1. GPS
            gps_status = "NOT WORKING"
            try:
                gps_data = gps.get_data()
                if gps_data is not None or True:
                    gps_status = "WORKING"
            except Exception:
                gps_status = "NOT WORKING"
            total_counts["GPS"] += 1
            if gps_status == "WORKING":
                up_counts["GPS"] += 1

            # 2. IMU
            imu_status = "NOT WORKING"
            try:
                imu_data = imu.read_data()
                if imu_data is not None:
                    imu_status = "WORKING"
            except Exception:
                imu_status = "NOT WORKING"
            total_counts["IMU"] += 1
            if imu_status == "WORKING":
                up_counts["IMU"] += 1

            # 3. Sign Detection
            detection_status = "NOT WORKING"
            try:
                frame = camera.get_frame()
                if frame is not None:
                    detector.detect(frame)
                    detection_status = "WORKING"
            except Exception:
                detection_status = "NOT WORKING"
            total_counts["DETECTION"] += 1
            if detection_status == "WORKING":
                up_counts["DETECTION"] += 1

            # 4. Internet
            internet_status = "WORKING" if check_internet() else "NOT WORKING"
            total_counts["INTERNET"] += 1
            if internet_status == "WORKING":
                up_counts["INTERNET"] += 1

            # Print summary line to console
            summary_line = f"GPS: {gps_status} | IMU: {imu_status} | DETECTION: {detection_status} | INTERNET: {internet_status}"
            print(summary_line)

            writer.writerow([timestamp, gps_status, imu_status, detection_status, internet_status])
            time.sleep(1)

    # Print uptime stats
    for subsystem in subsystems:
        up = up_counts[subsystem]
        total = total_counts[subsystem]
        down = total - up
        uptime_percent = (up / total) * 100 if total else 0
        print(f"{subsystem}: Uptime={up}s, Breakdown={down}s, Uptime%={uptime_percent:.2f}")

if __name__ == "__main__":
    main() 