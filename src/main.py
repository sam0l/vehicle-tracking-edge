import requests
import logging
import yaml
import time
import json
import os
import cv2
import base64
import socket
from datetime import datetime
from flask import Flask, jsonify
from src.sim_monitor import SimMonitor
from src.gps import GPS
from src.imu import IMU
from src.camera import Camera
from src.sign_detection import SignDetector
import urllib.parse
import traceback

app = Flask(__name__)

class VehicleTracker:
    def __init__(self, config_path):
        self.logger = logging.getLogger(__name__)
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        self.setup_logging()
        self.logger.info(f"Loaded config: {json.dumps(self.config, indent=2)}")
        
        # Initialize core components
        self.gps = GPS(
            self.config['gps']['port'],
            self.config['gps']['baudrate'],
            self.config['gps']['timeout'],
            self.config['gps']['power_delay'],
            self.config['gps']['agps_delay']
        )
        self.imu = IMU(
            i2c_bus=self.config['imu']['i2c_bus'],
            i2c_addresses=self.config['imu'].get('i2c_addresses', ["0x68", "0x69"]),
            sample_rate=self.config['imu'].get('sample_rate', 100),
            accel_range=self.config['imu'].get('accel_range', 2),
            gyro_range=self.config['imu'].get('gyro_range', 250)
        )
        self.camera = Camera(
            str(self.config['camera']['device_id']),
            self.config['camera']['width'],
            self.config['camera']['height'],
            self.config['camera']['fps']
        )
        
        # Initialize SIM monitor
        self.sim_monitor = SimMonitor(
            port=self.config['sim']['port'],
            baudrate=self.config['sim']['baudrate'],
            ussd_balance_code=self.config['sim'].get('ussd_balance_code', '*221#'),
            check_interval=self.config['sim'].get('check_interval', 3600)
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
        
        # Setup Flask routes
        self.setup_routes()

    def setup_routes(self):
        @app.route('/api/sim-data')
        def get_sim_data():
            data = self.sim_monitor.get_data_balance()
            return jsonify(data if data else {'error': 'No data available'})

        @app.route('/api/data-consumption')
        def get_data_consumption():
            data = self.sim_monitor.get_data_consumption()
            return jsonify(data)

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
                'camera': self.camera.initialize(),
                'sim': self.sim_monitor.connect()
            }
            self.camera_initialized = results['camera']
            if results['gps'] and results['imu'] and results['sim']:  # Camera is optional
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
            # Use urljoin to construct the URL safely
            base_url = self.config['backend']['url']
            prefix = self.config['backend']['endpoint_prefix']
            endpoint = self.config['backend']['detection_endpoint']
            url = urllib.parse.urljoin(base_url.rstrip('/') + '/', prefix.strip('/') + '/')
            url = urllib.parse.urljoin(url, endpoint.lstrip('/'))

            # Handle malformed timestamps gracefully
            try:
                timestamp = datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S").isoformat()
            except Exception as e:
                self.logger.error(f"Malformed timestamp: {data.get('timestamp')}, error: {e}")
                timestamp = datetime.now().isoformat()

            # Get retry count from config, default to 3
            retries = self.config.get('network', {}).get('retries', 3)

            # Send telemetry data (GPS)
            gps_sent = False
            if (
                data.get("gps") and
                data["gps"].get("latitude") is not None and
                data["gps"].get("longitude") is not None
            ):
                telemetry_data = {
                    "latitude": data["gps"]["latitude"],
                    "longitude": data["gps"]["longitude"],
                    "speed": data["gps"].get("speed") if data["gps"].get("speed") is not None else 0.0,
                    "timestamp": timestamp
                }
                telemetry_json = json.dumps(telemetry_data)
                for attempt in range(retries):
                    try:
                        self.logger.debug(f"Sending telemetry data (size: {len(telemetry_json)} bytes)")
                        response = requests.post(url, json=telemetry_data, timeout=30)
                        response.raise_for_status()
                        self.logger.info("Telemetry data sent successfully")
                        self.sim_monitor.update_data_consumption(len(telemetry_json), len(response.content))
                        gps_sent = True
                        break
                    except requests.RequestException as e:
                        self.logger.warning(f"Attempt {attempt+1}/{retries} failed to send telemetry data: {e}")
                        if attempt < retries - 1:
                            time.sleep(2)
                        continue
                if not gps_sent:
                    self.logger.error(f"All retry attempts failed for telemetry data: {telemetry_data}")
            else:
                self.logger.debug("No valid GPS data to send")

            # Send detection data (signs)
            signs_sent = True
            if self.sign_detector and data.get("signs") and frame is not None:
                image_base64 = None
                if self.config['yolo']['send_images']:
                    _, buffer = cv2.imencode('.jpg', frame)
                    image_base64 = base64.b64encode(buffer).decode('utf-8')
                for sign in data["signs"]:
                    detection_data = {
                        "latitude": data["gps"].get("latitude") if data.get("gps") and data["gps"].get("latitude") is not None else 0.0,
                        "longitude": data["gps"].get("longitude") if data.get("gps") and data["gps"].get("longitude") is not None else 0.0,
                        "speed": data["gps"].get("speed") if data.get("gps") and data["gps"].get("speed") is not None else 0.0,
                        "timestamp": timestamp,
                        "sign_type": sign["label"],
                        "confidence": sign["confidence"]
                    }
                    if image_base64:
                        detection_data["image"] = image_base64
                    detection_json = json.dumps(detection_data)
                    sign_sent = False
                    for attempt in range(retries):
                        try:
                            self.logger.debug(f"Sending detection data for sign {sign['label']} (size: {len(detection_json)} bytes)")
                            response = requests.post(url, json=detection_data, timeout=30)
                            response.raise_for_status()
                            self.logger.info(f"Detection data for sign {sign['label']} sent successfully")
                            self.sim_monitor.update_data_consumption(len(detection_json), len(response.content))
                            sign_sent = True
                            break
                        except requests.RequestException as e:
                            self.logger.warning(f"Attempt {attempt+1}/{retries} failed to send detection data for sign {sign['label']}: {e}")
                            if attempt < retries - 1:
                                time.sleep(2)
                            continue
                    if not sign_sent:
                        self.logger.error(f"All retry attempts failed for detection data: {detection_data}")
                        signs_sent = False
            # Return True if at least telemetry or one sign was sent
            return gps_sent or signs_sent
        except Exception as e:
            self.logger.error(f"Unexpected error sending data: {e}\n{traceback.format_exc()}")
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

    def run(self):
        if not self.initialize():
            self.logger.error("Initialization failed, exiting")
            return

        # Start Flask in a separate thread
        import threading
        flask_thread = threading.Thread(target=app.run, kwargs={
            'host': '0.0.0.0',
            'port': self.config['api']['port']
        })
        flask_thread.daemon = True
        flask_thread.start()

        last_gps = last_imu = last_camera = last_camera_init = last_sim = 0
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

                # SIM data
                if current_time - last_sim >= self.config['logging']['interval']['sim']:
                    sim_data = self.sim_monitor.get_data_balance()
                    if sim_data:
                        data.update({"sim": sim_data})
                    last_sim = current_time

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

    def cleanup(self):
        """Cleanup resources."""
        if hasattr(self, 'sim_monitor'):
            self.sim_monitor.close()
        if hasattr(self, 'camera'):
            self.camera.release()

if __name__ == "__main__":
    tracker = VehicleTracker("config/config.yaml")
    tracker.run() 