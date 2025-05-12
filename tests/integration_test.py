#!/usr/bin/env python3
"""
Integration Test Script

This script tests the integration of major subsystems:
- GPS, IMU, Camera, Sign Detection, and simulated LTE/Backend communication.

It verifies:
- Data flow between modules.
- Sensor fusion (basic combination).
- Packaging and sending data (mocked backend).
- Robustness under simulated network conditions.
- Basic system stability over time.

Usage:
python3 tests/integration_test.py [--duration DURATION] [--no-gui]
"""

import sys
import os
import time
import logging
import yaml
import argparse
import cv2
import random
import threading
import requests
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

# Add the parent directory to the path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.gps import GPS
from src.imu import IMU
from src.camera import Camera
from src.sign_detection import SignDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("integration_test")

# --- Mock Backend Server ---
received_data = deque(maxlen=100)
network_conditions = {"delay": 0, "fail_rate": 0.0}

class MockBackendHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Simulate network delay
        time.sleep(network_conditions["delay"])

        # Simulate network failure
        if random.random() < network_conditions["fail_rate"]:
            self.send_error(500, "Simulated Network Error")
            logger.warning("Simulated network failure for POST request")
            return

        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            received_data.append(data)
            logger.info(f"Mock Backend received data: {data}")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
        except Exception as e:
            logger.error(f"Error handling POST request: {e}")
            self.send_error(500, f"Server Error: {e}")

def run_mock_server(port=8000):
    server_address = ('', port)
    httpd = HTTPServer(server_address, MockBackendHandler)
    logger.info(f"Starting mock backend server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logger.info("Mock backend server stopped.")

# --- Integration Tester Class ---

class IntegrationTester:
    """Test class for integrating major subsystems."""

    def __init__(self, config_path='config/config.yaml', backend_url='http://localhost:8000/api/telemetry'):
        self.config_path = config_path
        self.backend_url = backend_url
        self.load_config()
        self.initialize_modules()

        self.telemetry_interval = 1.0  # seconds
        self.last_telemetry_send_time = 0
        self.test_results = {
            "gps_reads": 0,
            "imu_reads": 0,
            "frames_captured": 0,
            "detections_made": 0,
            "telemetry_sent": 0,
            "telemetry_failed": 0,
            "errors": 0
        }

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Error loading config: {e}. Using defaults.")
            # Define minimal default config if loading fails
            self.config = {
                'gps': {'port': '/dev/ttyUSB1', 'baudrate': 115200, 'timeout': 1, 'power_delay': 5, 'agps_delay': 5},
                'imu': {'i2c_bus': 4, 'i2c_addresses': ['0x68', '0x69'], 'sample_rate': 100, 'accel_range': 2, 'gyro_range': 250},
                'camera': {'device_id': 0, 'width': 640, 'height': 360, 'fps': 30},
                'yolo': {'model_path': 'models/best.onnx', 'imgsz': 640, 'conf_threshold': 0.7, 'iou_threshold': 0.45, 'draw_boxes': True, 'send_images': False},
            }

    def initialize_modules(self):
        logger.info("Initializing subsystems...")
        try:
            gps_cfg = self.config['gps']
            self.gps = GPS(gps_cfg['port'], gps_cfg['baudrate'], gps_cfg['timeout'], gps_cfg['power_delay'], gps_cfg['agps_delay'])
            if not self.gps.initialize(): raise Exception("GPS init failed")
            logger.info("GPS initialized.")

            imu_cfg = self.config['imu']
            self.imu = IMU(imu_cfg['i2c_bus'], i2c_addresses=imu_cfg['i2c_addresses'], sample_rate=imu_cfg['sample_rate'], accel_range=imu_cfg['accel_range'], gyro_range=imu_cfg['gyro_range'])
            if not self.imu.initialize(): raise Exception("IMU init failed")
            logger.info("IMU initialized.")

            cam_cfg = self.config['camera']
            self.camera = Camera(cam_cfg['device_id'], cam_cfg['width'], cam_cfg['height'], cam_cfg['fps'])
            if not self.camera.initialize(): raise Exception("Camera init failed")
            logger.info("Camera initialized.")

            self.detector = SignDetector(self.config_path)
            # Initialization happens in SignDetector __init__
            logger.info("SignDetector initialized.")

        except Exception as e:
            logger.error(f"Failed to initialize one or more subsystems: {e}")
            self.test_results["errors"] += 1
            # Depending on the critical nature, you might want to exit or continue degraded
            raise RuntimeError("Subsystem initialization failed") from e

    def gather_sensor_data(self):
        gps_data = None
        imu_data = None
        try:
            gps_data = self.gps.read_gps_data()
            if gps_data: self.test_results["gps_reads"] += 1
        except Exception as e:
            logger.error(f"Error reading GPS data: {e}")
            self.test_results["errors"] += 1

        try:
            imu_data = self.imu.read_data()
            if imu_data: self.test_results["imu_reads"] += 1
        except Exception as e:
            logger.error(f"Error reading IMU data: {e}")
            self.test_results["errors"] += 1

        return gps_data, imu_data

    def process_camera_and_detect(self, visualize=False):
        detections = []
        frame = None
        try:
            frame = self.camera.get_frame()
            if frame is not None:
                self.test_results["frames_captured"] += 1
                detections = self.detector.detect(frame)
                self.test_results["detections_made"] += len(detections)

                if visualize:
                    # Draw detections (simplified version)
                    for det in detections:
                        if 'bbox' in det: x1, y1, x2, y2 = det['bbox']
                        elif 'box' in det: cx, cy, w, h = det['box']; x1, y1, x2, y2 = int(cx-w/2), int(cy-h/2), int(cx+w/2), int(cy+h/2)
                        else: continue
                        label = det.get('label', '?')
                        conf = det.get('confidence', 0)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
                        cv2.putText(frame, f"{label}:{conf:.1f}", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
                    cv2.imshow("Integration Test", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        return None, True # Signal to exit
            else:
                logger.warning("Failed to capture frame")
                self.test_results["errors"] += 1

        except Exception as e:
            logger.error(f"Error during camera/detection: {e}")
            self.test_results["errors"] += 1

        return detections, False # False means don't exit

    def package_telemetry(self, gps_data, imu_data, detections):
        telemetry = {
            "timestamp": time.time(),
            "gps": gps_data,
            "imu": imu_data,
            "detections": detections,
            "status": "ok"
        }
        # Basic sensor fusion/selection
        position = None
        speed = None
        heading = None

        if gps_data and gps_data.get('fix'):
            position = (gps_data.get('latitude'), gps_data.get('longitude'))
            speed = gps_data.get('speed')
            heading = gps_data.get('heading')
        elif imu_data:
            position = imu_data.get('position') # Might be from Kalman filter
            speed = imu_data.get('speed')
            heading = imu_data.get('heading')

        telemetry['calculated_position'] = position
        telemetry['calculated_speed'] = speed
        telemetry['calculated_heading'] = heading

        return telemetry

    def send_telemetry(self, telemetry_data):
        try:
            response = requests.post(self.backend_url, json=telemetry_data, timeout=10)
            response.raise_for_status() # Raises exception for 4xx/5xx errors
            logger.info(f"Telemetry sent successfully. Status: {response.status_code}")
            self.test_results["telemetry_sent"] += 1
            return True
        except requests.exceptions.Timeout:
            logger.warning("Telemetry send timed out.")
            self.test_results["telemetry_failed"] += 1
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending telemetry: {e}")
            self.test_results["telemetry_failed"] += 1
            self.test_results["errors"] += 1 # Count network errors
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending telemetry: {e}")
            self.test_results["telemetry_failed"] += 1
            self.test_results["errors"] += 1
            return False

    def run_test_loop(self, duration_seconds, visualize=False):
        logger.info(f"Starting integration test loop for {duration_seconds} seconds...")
        start_time = time.time()
        end_time = start_time + duration_seconds

        while time.time() < end_time:
            loop_start = time.time()

            # 1. Gather Data
            gps_data, imu_data = self.gather_sensor_data()

            # 2. Process Camera & Detect Signs
            detections, exit_signal = self.process_camera_and_detect(visualize)
            if exit_signal:
                break

            # 3. Package Telemetry
            telemetry = self.package_telemetry(gps_data, imu_data, detections)

            # 4. Send Telemetry (throttled)
            current_time = time.time()
            if current_time - self.last_telemetry_send_time >= self.telemetry_interval:
                self.send_telemetry(telemetry)
                self.last_telemetry_send_time = current_time

            # Maintain loop timing (simple approach)
            loop_duration = time.time() - loop_start
            sleep_time = max(0, 0.1 - loop_duration) # Aim for ~10Hz loop
            time.sleep(sleep_time)

        logger.info("Integration test loop finished.")
        if visualize:
            cv2.destroyAllWindows()

    def simulate_network_conditions(self, delay, fail_rate):
        logger.info(f"Simulating network conditions: Delay={delay}s, Fail Rate={fail_rate*100}%")
        network_conditions["delay"] = delay
        network_conditions["fail_rate"] = fail_rate

    def report_results(self):
        logger.info("\n===== Integration Test Summary =====")
        for key, value in self.test_results.items():
            logger.info(f"  {key.replace('_', ' ').title()}: {value}")

        total_sent = self.test_results["telemetry_sent"]
        total_failed = self.test_results["telemetry_failed"]
        total_attempts = total_sent + total_failed
        success_rate = (total_sent / total_attempts * 100) if total_attempts > 0 else 0
        logger.info(f"  Telemetry Success Rate: {success_rate:.1f}% ({total_sent}/{total_attempts})")
        logger.info(f"  Backend Received Count: {len(received_data)}")
        logger.info("====================================")

        # Basic check for success
        if self.test_results["errors"] == 0 and total_sent > 0:
            logger.info("Integration Test: PASSED")
            return True
        else:
            logger.error("Integration Test: FAILED")
            return False

    def cleanup(self):
        logger.info("Cleaning up resources...")
        if self.gps: self.gps.close()
        if self.imu: self.imu.close()
        if self.camera: self.camera.close()
        # Detector might have resources, add close if needed
        # if self.detector: self.detector.close()
        cv2.destroyAllWindows()
        logger.info("Cleanup complete.")

def parse_args():
    parser = argparse.ArgumentParser(description="Integration Test Runner")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI visualization")
    parser.add_argument("--backend-port", type=int, default=8000, help="Port for the mock backend server")
    parser.add_argument("--net-delay", type=float, default=0, help="Simulated network delay in seconds")
    parser.add_argument("--net-fail", type=float, default=0.0, help="Simulated network failure rate (0.0 to 1.0)")
    return parser.parse_args()

def main():
    args = parse_args()
    backend_port = args.backend_port
    backend_url = f'http://localhost:{backend_port}/api/telemetry'

    # Start mock backend server in a separate thread
    server_thread = threading.Thread(target=run_mock_server, args=(backend_port,), daemon=True)
    server_thread.start()
    time.sleep(1) # Give server time to start

    tester = None
    success = False
    try:
        tester = IntegrationTester(backend_url=backend_url)
        tester.simulate_network_conditions(args.net_delay, args.net_fail)
        tester.run_test_loop(args.duration, visualize=not args.no_gui)
        success = tester.report_results()
    except Exception as e:
        logger.error(f"Integration test failed critically: {e}", exc_info=True)
        success = False
    finally:
        if tester:
            tester.cleanup()
        # The server thread is a daemon, so it will exit when the main thread exits.

    return 0 if success else 1

if __name__ == "__main__":
    # Ensure test results directory exists
    os.makedirs('test_results', exist_ok=True)
    sys.exit(main()) 