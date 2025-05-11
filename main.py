import yaml
import logging
import time
import json
import requests
import os
import cv2
import base64
import socket
from datetime import datetime
from flask import Flask, jsonify
from src.gps import GPS
from src.imu import IMU
from src.camera import Camera
from src.sign_detection import SignDetector
from src.sim_monitor import SimMonitor
import threading

app = Flask(__name__)

class VehicleTracker:
    def __init__(self, config_path):
        self.logger = logging.getLogger(__name__)
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        self.setup_logging()
        self.logger.info(f"Loaded config: {json.dumps(self.config, indent=2)}")
        self.gps = GPS(
            self.config['gps']['port'],
            self.config['gps']['baudrate'],
            self.config['gps']['timeout'],
            self.config['gps']['power_delay'],
            self.config['gps']['agps_delay']
        )
        self.imu = IMU(
            self.config['imu']['i2c_bus'],
            i2c_addresses=self.config['imu']['i2c_addresses'],
            sample_rate=self.config['imu']['sample_rate'],
            accel_range=self.config['imu']['accel_range'],
            gyro_range=self.config['imu']['gyro_range']
        )
        self.camera = Camera(
            self.config['camera']['device_id'],
            self.config['camera']['width'],
            self.config['camera']['height'],
            self.config['camera']['fps']
        )
        try:
            self.sign_detector = SignDetector(config_path)
        except Exception as e:
            self.logger.error(f"Failed to initialize SignDetector: {e}")
            self.logger.info("Continuing without sign detection")
            self.sign_detector = None
        self.offline_data = []
        self.offline_file = "offline_data.json"
        # Ensure offline file directory exists
        os.makedirs(os.path.dirname(self.offline_file) or '.', exist_ok=True)
        if not os.path.exists(self.offline_file):
            with open(self.offline_file, 'w') as f:
                json.dump([], f)
        self.camera_initialized = False
        self.sim_monitor = SimMonitor(
            port=self.config['sim']['port'],
            baudrate=self.config['sim']['baudrate'],
            check_interval=self.config['sim'].get('check_interval', 3600),
            usage_file=self.config['sim'].get('usage_file', 'data_usage.json')
        )
        self.app = app  # Store Flask app as instance variable
        self.setup_routes()

    def setup_logging(self):
        logging.basicConfig(
            level=getattr(logging, self.config['logging']['level']),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('vehicle_tracker.log'),
                logging.StreamHandler()
            ]
        )

    def initialize(self, max_retries=5, retry_delay=5):
        attempt = 0
        while attempt < max_retries:
            attempt += 1
            self.logger.info(f"Initialization attempt {attempt}/{max_retries}")
            results = {
                'gps': self.gps.initialize(),
                'imu': self.imu.initialize(),
                'camera': self.camera.initialize()
            }
            self.camera_initialized = results['camera']
            if results['gps'] and results['imu']:  # Camera is optional
                self.logger.info(f"Core components initialized successfully (IMU address: 0x{self.imu.address:02x}, Camera: {self.camera_initialized})")
                return True
            self.logger.error(f"Initialization failed: {results}")
            if attempt < max_retries:
                self.logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
        self.logger.error("Max initialization retries reached, giving up")
        return False

    def check_connectivity(self, host="8.8.8.8", port=53, timeout=3):
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            self.logger.debug("Network connectivity confirmed")
            return True
        except socket.error as e:
            self.logger.warning(f"No network connectivity: {e}")
            return False

    def send_data(self, data, frame=None):
        if not self.check_connectivity():
            self.logger.error("No network connection, skipping send")
            return False

        try:
            url = f"{self.config['backend']['url']}{self.config['backend']['endpoint_prefix']}{self.config['backend']['detection_endpoint']}"
            timestamp = datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S").isoformat()
            retries = 3
            for attempt in range(retries):
                try:
                    # Send telemetry data (GPS)
                    if data.get("gps") and data["gps"].get("latitude") and data["gps"].get("longitude"):
                        telemetry_data = {
                            "latitude": data["gps"]["latitude"],
                            "longitude": data["gps"]["longitude"],
                            "speed": data["gps"]["speed"] if data["gps"]["speed"] is not None else 0.0,
                            "timestamp": timestamp
                        }
                        self.logger.debug(f"Sending telemetry data (size: {len(json.dumps(telemetry_data))} bytes)")
                        response = requests.post(url, json=telemetry_data, timeout=30)
                        response.raise_for_status()
                        self.logger.info("Telemetry data sent successfully")
                    else:
                        self.logger.debug("No valid GPS data to send")

                    # Send detection data (signs)
                    if self.sign_detector and data.get("signs") and frame is not None:
                        image_base64 = None
                        if self.config['yolo']['send_images']:
                            _, buffer = cv2.imencode('.jpg', frame)
                            image_base64 = base64.b64encode(buffer).decode('utf-8')
                        for sign in data["signs"]:
                            detection_data = {
                                "latitude": data["gps"]["latitude"] if data.get("gps") and data["gps"].get("latitude") else 0.0,
                                "longitude": data["gps"]["longitude"] if data.get("gps") and data["gps"].get("longitude") else 0.0,
                                "speed": data["gps"]["speed"] if data.get("gps") and data["gps"].get("speed") else 0.0,
                                "timestamp": timestamp,
                                "sign_type": sign["label"],
                                "confidence": sign["confidence"]
                            }
                            if image_base64:
                                detection_data["image"] = image_base64
                            print(f"[DEBUG] Sending detection payload: {detection_data}")
                            self.logger.debug(f"Sending detection data (size: {len(json.dumps(detection_data))} bytes)")
                            response = requests.post(url, json=detection_data, timeout=30)
                            response.raise_for_status()
                        self.logger.info("Detection data sent successfully")

                    return True
                except requests.RequestException as e:
                    self.logger.warning(f"Attempt {attempt+1}/{retries} failed: {e}")
                    if attempt < retries - 1:
                        time.sleep(2)
                    continue
            self.logger.error("All retry attempts failed")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error sending data: {e}")
            return False

    def log_offline(self, data):
        self.offline_data.append(data)
        try:
            with open(self.offline_file, 'w') as f:
                json.dump(self.offline_data, f, indent=2)
            self.logger.info("Data logged offline")
        except Exception as e:
            self.logger.error(f"Error logging offline data: {e}")

    def send_offline_data(self):
        if not self.offline_data:
            return
        for data in self.offline_data[:]:
            if self.send_data(data):
                self.offline_data.remove(data)
        try:
            with open(self.offline_file, 'w') as f:
                json.dump(self.offline_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error updating offline data file: {e}")

    def send_sim_data(self, sim_data):
        try:
            url = f"{self.config['backend']['url']}{self.config['backend']['endpoint_prefix']}{self.config['backend']['sim_data_endpoint']}"
            response = requests.post(url, json=sim_data)
            response.raise_for_status()
            self.logger.info(f"Sent SIM data to backend: {sim_data}")
        except Exception as e:
            self.logger.error(f"Failed to send SIM data: {e}")

    def run(self):
        if not self.initialize():
            self.logger.error("Initialization failed, exiting")
            return

        # Start Flask in a separate thread
        import threading
        flask_thread = threading.Thread(target=self.app.run, kwargs={
            'host': '0.0.0.0',
            'port': self.config['api']['port']
        })
        flask_thread.daemon = True
        flask_thread.start()

        last_gps = last_imu = last_camera = last_camera_init = 0
        camera_init_interval = 30  # Retry camera every 30 seconds if failed
        try:
            while True:
                current_time = time.time()
                data = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

                # GPS data
                if current_time - last_gps >= self.config['logging']['interval']['gps']:
                    gps_data = self.gps.get_data()
                    if gps_data:
                        data.update({"gps": gps_data})
                    else:
                        self.logger.warning("No valid GPS data received")
                    last_gps = current_time

                # IMU data
                if current_time - last_imu >= self.config['logging']['interval']['imu']:
                    imu_data = self.imu.read_data()
                    if imu_data:
                        data.update({"imu": imu_data})
                    last_imu = current_time

                # Camera data
                if self.camera_initialized and current_time - last_camera >= self.config['logging']['interval']['camera']:
                    frame = self.camera.get_frame()
                    if frame is not None:
                        print(f"[DEBUG] Frame captured: {frame.shape}")
                        if self.sign_detector:
                            signs = self.sign_detector.detect(frame)
                            print(f"[DEBUG] Detections: {signs}")
                            if signs:
                                data.update({"signs": signs})
                        last_camera = current_time
                    else:
                        print("[DEBUG] No frame captured from camera!")
                elif not self.camera_initialized and current_time - last_camera_init >= camera_init_interval:
                    self.camera_initialized = self.camera.initialize()
                    last_camera_init = current_time

                # Data usage logging is handled in send_data via self.sim_monitor.update_data_consumption

                # Send data if we have GPS coordinates
                if data.get("gps") and data["gps"].get("latitude") and data["gps"].get("longitude"):
                    if not self.send_data(data, frame if 'frame' in locals() else None):
                        self.log_offline(data)
                else:
                    self.logger.debug("No valid GPS data to send")

                # Try to send any offline data
                self.send_offline_data()

                time.sleep(0.1)  # Small delay to prevent CPU overload

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            self.cleanup()

if __name__ == "__main__":
    tracker = VehicleTracker("config/config.yaml")
    tracker.run()
