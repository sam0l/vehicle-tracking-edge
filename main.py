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
            usage_file=self.config['sim'].get('usage_file', 'data_usage.json'),
            interfaces=self.config['network'].get('interface', ["ppp0"])
        )
        self.app = app  # Store Flask app as instance variable
        self.setup_routes()
        
        # Keep track of last telemetry update to optimize real-time map updates
        self.last_telemetry_send_time = 0
        self.telemetry_interval = 1.0  # Send telemetry updates every 1 second
        
        # Speed calculation parameters
        self.current_speed = 0.0
        self.speed_alpha = 0.8  # Weight for GPS in combined speed calculation (0.8 GPS, 0.2 IMU)
        self.use_imu_speed = False
        self.last_speed_update = time.time()  # Initialize to current time instead of 0
        self.max_speed_age = 30  # Maximum age for speed data in seconds (increased from 10s)

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
            
            # Initialize GPS first with longer timeout for AGPS initialization
            gps_init = self.gps.initialize()
            if not gps_init:
                self.logger.error("GPS initialization failed")
                if attempt < max_retries:
                    self.logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                continue
                
            # Initialize other components
            results = {
                'gps': gps_init,
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

    def calculate_speed(self, gps_data, imu_data):
        """
        Calculate a more accurate speed by combining GPS and IMU data.
        
        GPS provides absolute speed but can be noisy or have delay.
        IMU provides relative speed changes but can drift over time.
        We combine them using an exponential moving average.
        
        Fallback order:
        1. Use weighted average of GPS and IMU when both available
        2. Use GPS only when IMU unavailable
        3. Use IMU only when GPS unavailable
        4. Use last known speed if neither available
        """
        current_time = time.time()
        
        # Initialize with GPS speed if available
        if gps_data and 'speed' in gps_data and gps_data['speed'] is not None:
            gps_speed = gps_data['speed']
            self.last_speed_update = current_time
            
            if imu_data and 'speed' in imu_data:
                # We have both GPS and IMU speed, combine them using weighted average
                imu_speed = imu_data['speed']
                
                # If IMU reports stationary (0 speed), give it more weight
                # This helps quickly detect when vehicle stops
                if imu_speed == 0 and imu_data.get('is_stationary', False):
                    # Use 50/50 blend when IMU detects we're stopped
                    self.current_speed = 0.5 * gps_speed + 0.5 * imu_speed
                    if self.current_speed < 0.5:  # If combined speed is low enough, force to zero
                        self.current_speed = 0.0
                else:
                    # Normal weighted average (80% GPS, 20% IMU)
                    self.current_speed = (self.speed_alpha * gps_speed) + ((1 - self.speed_alpha) * imu_speed)
                
                # Enable IMU speed for future calculations
                self.use_imu_speed = True
                self.logger.debug(f"Speed calculation: GPS={gps_speed:.2f}, IMU={imu_speed:.2f}, Combined={self.current_speed:.2f}")
            else:
                # Just use GPS speed (IMU unavailable)
                self.current_speed = gps_speed
                self.logger.debug(f"Speed calculation: using GPS speed only: {gps_speed:.2f}")
                
            # Update IMU with latest GPS data for better dead reckoning
            if self.imu and gps_data:
                self.imu.update_gps(gps_data)
                
            return round(self.current_speed, 2)
            
        # If GPS speed is not available but IMU speed is, use IMU
        elif imu_data and 'speed' in imu_data:
            # Always update last_speed_update when we receive fresh IMU data
            self.last_speed_update = current_time
            
            self.use_imu_speed = True
            self.current_speed = imu_data['speed']
            
            # If IMU reports stationary, ensure speed is exactly zero
            if imu_data.get('is_stationary', False):
                self.current_speed = 0.0
                
            self.logger.debug(f"Speed calculation: using IMU speed: {self.current_speed:.2f}")
            return round(self.current_speed, 2)
            
        # If neither is available, return the last known speed
        self.logger.debug(f"Speed calculation: no new data, using last speed: {self.current_speed:.2f}")
        return round(self.current_speed, 2)

    def send_data(self, data, frame=None):
        """
        Send data to the backend server:
        1. Regular telemetry updates (position, speed) for map updates
        2. Sign detections when they occur (with position, speed, and sign info)
        """
        if not self.check_connectivity():
            self.logger.error("No network connection, skipping send")
            return False

        try:
            url = f"{self.config['backend']['url']}{self.config['backend']['endpoint_prefix']}{self.config['backend']['detection_endpoint']}"
            timestamp = datetime.strptime(data["timestamp"], "%Y-%m-%d %H:%M:%S").isoformat()
            retries = 3
            current_time = time.time()
            send_telemetry = False
            send_detection = False

            # Determine if we should send telemetry (for map updates)
            if data.get("gps") and data["gps"].get("latitude") and data["gps"].get("longitude"):
                # Send telemetry at regular intervals for map updates
                if current_time - self.last_telemetry_send_time >= self.telemetry_interval:
                    send_telemetry = True
                    self.last_telemetry_send_time = current_time

            # Determine if we should send detection data
            if data.get("signs") and len(data.get("signs")) > 0:
                send_detection = True

            # If nothing to send, return early
            if not (send_telemetry or send_detection):
                return True

            # Create combined telemetry and detection data
            for attempt in range(retries):
                try:
                    # Send telemetry data for map updates (independent of detections)
                    if send_telemetry:
                        # Create telemetry data
                        telemetry_data = {
                            "latitude": data["gps"]["latitude"],
                            "longitude": data["gps"]["longitude"],
                            "speed": data["gps"].get("speed", 0.0),
                            "timestamp": timestamp,
                            "connection_status": self.check_connectivity(),
                            "update_type": "position"  # Flag this as position update for map
                        }
                        
                        # Add additional GPS data if available
                        if "satellites" in data["gps"]:
                            telemetry_data["satellites"] = data["gps"]["satellites"]
                        if "altitude" in data["gps"]:
                            telemetry_data["altitude"] = data["gps"]["altitude"]
                        
                        # Flag dead reckoning data
                        if data["gps"].get("dead_reckoning", False):
                            telemetry_data["dead_reckoning"] = True
                            telemetry_data["position_source"] = "imu"
                            telemetry_data["accuracy"] = "low"  # Dead reckoning has lower accuracy
                            
                        payload_bytes = len(json.dumps(telemetry_data).encode('utf-8'))
                        self.logger.debug(f"Sending telemetry data (size: {payload_bytes} bytes): {telemetry_data}")
                        response = requests.post(url, json=telemetry_data, timeout=30)
                        response.raise_for_status()
                        response_bytes = len(response.content)
                        self.sim_monitor.update_data_usage()
                        self.logger.info(f"Telemetry data sent successfully (sent: {payload_bytes} bytes, received: {response_bytes} bytes)")

                    # Send detection data only when signs are detected
                    if send_detection and self.sign_detector:
                        # Get current speed from IMU if GPS is not available
                        current_speed = 0.0
                        has_valid_gps = False
                        is_dead_reckoning = False
                        
                        # Check if we have GPS data
                        if data.get("gps"):
                            gps_data = data["gps"]
                            lat = gps_data.get("latitude", 0.0)
                            lon = gps_data.get("longitude", 0.0)
                            spd = gps_data.get("speed", 0.0)
                            has_valid_gps = (lat != 0.0 and lon != 0.0)
                            is_dead_reckoning = gps_data.get("dead_reckoning", False)
                        else:
                            # No GPS data, use default values
                            gps_data = {}
                            lat = 0.0
                            lon = 0.0
                            
                            # Try to get speed from IMU
                            if data.get("imu") and "speed" in data["imu"]:
                                spd = data["imu"]["speed"]
                                self.logger.info(f"Using IMU speed ({spd:.2f} m/s) for detection without GPS")
                            else:
                                spd = 0.0
                        
                        # Check if we should skip detections without GPS based on config
                        allow_without_gps = self.config['yolo'].get('allow_detections_without_gps', False)
                        if not has_valid_gps and not allow_without_gps:
                            self.logger.warning("Skipping detections without valid GPS data (allow_detections_without_gps is False)")
                            continue
                            
                        image_base64 = None
                        if self.config['yolo']['send_images'] and frame is not None:
                            _, buffer = cv2.imencode('.jpg', frame)
                            image_base64 = base64.b64encode(buffer).decode('utf-8')
                            
                        for sign in data["signs"]:
                            detection_data = {
                                "latitude": lat,
                                "longitude": lon,
                                "speed": spd,
                                "timestamp": timestamp,
                                "sign_type": sign["label"],
                                "confidence": sign["confidence"],
                                "connection_status": self.check_connectivity(),
                                "update_type": "detection",  # Flag this as detection for backend
                                "indoor_test": not has_valid_gps and not is_dead_reckoning  # Flag if this is indoor testing without GPS
                            }
                            
                            # Add additional GPS data if available
                            if "satellites" in gps_data:
                                detection_data["satellites"] = gps_data["satellites"]
                            if "altitude" in gps_data:
                                detection_data["altitude"] = gps_data["altitude"]
                            
                            # Flag dead reckoning data
                            if is_dead_reckoning:
                                detection_data["dead_reckoning"] = True
                                detection_data["position_source"] = "imu"
                                detection_data["accuracy"] = "low"  # Dead reckoning has lower accuracy
                                
                            if image_base64:
                                detection_data["image"] = image_base64
                                
                            payload_bytes = len(json.dumps(detection_data).encode('utf-8'))
                            self.logger.debug(f"[SEND] Attempting to send detection data (size: {payload_bytes} bytes): {detection_data}")
                            response = requests.post(url, json=detection_data, timeout=30)
                            response.raise_for_status()
                            response_bytes = len(response.content)
                            self.sim_monitor.update_data_usage()
                            self.logger.info(f"[SEND] Detection data sent successfully (sent: {payload_bytes} bytes, received: {response_bytes} bytes)")

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

    def setup_routes(self):
        @self.app.route('/api/data-usage')
        def get_data_usage():
            return jsonify({
                '1d': self.sim_monitor.get_usage_stats('1d'),
                '1w': self.sim_monitor.get_usage_stats('1w'),
                '1m': self.sim_monitor.get_usage_stats('1m')
            })

    def post_data_usage_loop(self):
        interval = self.config['sim'].get('usage_post_interval', 30)
        backend_url = f"{self.config['backend']['url']}/api/data-usage"
        last_post_time = time.time()
        last_bytes_sent = 0
        last_bytes_received = 0
        while True:
            try:
                time.sleep(interval)
                # Get usage for the last interval
                usage_stats = self.sim_monitor.get_usage_stats('1d')
                now = datetime.utcnow().isoformat()
                bytes_sent = usage_stats['bytes_sent']
                bytes_received = usage_stats['bytes_received']
                # Calculate delta since last post
                delta_sent = bytes_sent - last_bytes_sent
                delta_received = bytes_received - last_bytes_received
                if delta_sent < 0 or delta_received < 0:
                    # If log rotated or reset, just send current
                    delta_sent = bytes_sent
                    delta_received = bytes_received
                payload = {
                    'timestamp': now,
                    'bytes_sent': delta_sent,
                    'bytes_received': delta_received
                }
                last_bytes_sent = bytes_sent
                last_bytes_received = bytes_received
                response = requests.post(backend_url, json=payload, timeout=10)
                if response.status_code == 200:
                    self.logger.info(f"Posted data usage to backend: {payload}")
                else:
                    self.logger.warning(f"Failed to post data usage: {response.status_code} {response.text}")
            except Exception as e:
                self.logger.warning(f"Error posting data usage: {e}")

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

        # Start data usage posting thread
        usage_thread = threading.Thread(target=self.post_data_usage_loop)
        usage_thread.daemon = True
        usage_thread.start()

        last_gps = last_imu = last_camera = last_camera_init = 0
        camera_init_interval = 30  # Retry camera every 30 seconds if failed
        consecutive_gps_failures = 0
        max_gps_failures = 10  # After this many consecutive failures, try to reinitialize GPS
        consecutive_imu_failures = 0
        max_imu_failures = 5  # After this many consecutive failures, try to reinitialize IMU
        
        # Initialize position tracking variables
        last_known_position = None
        using_dead_reckoning = False
        dead_reckoning_start_time = 0
        max_dead_reckoning_time = 300  # 5 minutes max dead reckoning
        
        try:
            while True:
                current_time = time.time()
                data = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
                frame = None
                gps_data = None
                imu_data = None
                
                # Tracked failure states
                gps_failure = False
                imu_failure = False

                # GPS data
                if current_time - last_gps >= self.config['logging']['interval']['gps']:
                    try:
                        gps_data = self.gps.get_data()
                        if gps_data:
                            data.update({"gps": gps_data})
                            last_known_position = (gps_data['latitude'], gps_data['longitude'])
                            consecutive_gps_failures = 0  # Reset failure counter on success
                            using_dead_reckoning = False  # Reset dead reckoning flag
                            
                            # Log GPS fix details
                            satellites = gps_data.get("satellites", 0)
                            self.logger.info(f"GPS fix acquired: {gps_data['latitude']},{gps_data['longitude']} (satellites: {satellites})")
                        else:
                            self.logger.warning(f"No valid GPS data received (satellites visible: {self.gps.satellites})")
                            consecutive_gps_failures += 1
                            gps_failure = True
                            
                            # If we've had too many consecutive failures, try to reinitialize GPS
                            if consecutive_gps_failures >= max_gps_failures:
                                self.logger.warning(f"Too many consecutive GPS failures ({consecutive_gps_failures}), reinitializing GPS...")
                                try:
                                    self.gps.initialize()
                                    consecutive_gps_failures = 0
                                except Exception as e:
                                    self.logger.error(f"Failed to reinitialize GPS: {e}")
                    except Exception as e:
                        self.logger.error(f"GPS error: {e}")
                        consecutive_gps_failures += 1
                        gps_failure = True
                    last_gps = current_time

                # IMU data
                if current_time - last_imu >= self.config['logging']['interval']['imu']:
                    try:
                        imu_data = self.imu.read_data()
                        if imu_data:
                            data.update({"imu": imu_data})
                            consecutive_imu_failures = 0  # Reset failure counter on success
                            
                            # If we have GPS data, update IMU with it
                            if gps_data:
                                self.imu.update_gps(gps_data)
                                
                            # If GPS has failed but IMU has position data, enter dead reckoning mode
                            if gps_failure and imu_data.get('position') and not using_dead_reckoning:
                                using_dead_reckoning = True
                                dead_reckoning_start_time = current_time
                                self.logger.info("Entering dead reckoning mode with IMU position data")
                        else:
                            self.logger.warning("No valid IMU data received")
                            consecutive_imu_failures += 1
                            imu_failure = True
                            
                            # If we've had too many consecutive failures, try to reinitialize IMU
                            if consecutive_imu_failures >= max_imu_failures:
                                self.logger.warning(f"Too many consecutive IMU failures ({consecutive_imu_failures}), reinitializing IMU...")
                                try:
                                    self.imu.initialize()
                                    consecutive_imu_failures = 0
                                except Exception as e:
                                    self.logger.error(f"Failed to reinitialize IMU: {e}")
                    except Exception as e:
                        self.logger.error(f"IMU error: {e}")
                        consecutive_imu_failures += 1
                        imu_failure = True
                    last_imu = current_time
                
                # Dead reckoning fallback when GPS is down but IMU is working
                if gps_failure and not imu_failure and using_dead_reckoning:
                    # Check if we've been dead reckoning too long
                    if current_time - dead_reckoning_start_time > max_dead_reckoning_time:
                        self.logger.warning(f"Dead reckoning timeout ({max_dead_reckoning_time}s) exceeded, disabling")
                        using_dead_reckoning = False
                    elif imu_data and imu_data.get('position') and not data.get('gps'):
                        # Create a synthetic GPS entry from IMU position data
                        imu_pos = imu_data['position']
                        if imu_pos:
                            if 'gps' not in data:
                                data['gps'] = {}
                            data['gps']['latitude'] = imu_pos[0]
                            data['gps']['longitude'] = imu_pos[1]
                            data['gps']['speed'] = imu_data['speed']
                            data['gps']['dead_reckoning'] = True  # Flag that this is from dead reckoning
                            dr_duration = current_time - dead_reckoning_start_time
                            self.logger.info(f"Using IMU dead reckoning position after {dr_duration:.1f}s: {imu_pos[0]:.6f},{imu_pos[1]:.6f}")
                
                # Calculate speed from GPS and IMU data
                if gps_data or imu_data:
                    speed = self.calculate_speed(gps_data, imu_data)
                    # Update GPS data with calculated speed
                    if "gps" in data and speed is not None:
                        data["gps"]["speed"] = speed
                    # Make sure IMU speed is also available without GPS
                    elif "imu" in data and speed is not None:
                        data["imu"]["speed"] = speed

                # Camera data and sign detection
                if self.camera_initialized and current_time - last_camera >= self.config['logging']['interval']['camera']:
                    try:
                        frame = self.camera.get_frame()
                        if frame is not None:
                            # Only detect signs if we have a valid frame
                            if self.sign_detector:
                                signs = self.sign_detector.detect(frame)
                                if signs:  # Only add signs to data if we found any
                                    data.update({"signs": signs})
                        else:
                            self.logger.debug("No frame captured from camera")
                    except Exception as e:
                        self.logger.error(f"Camera error: {e}")
                    last_camera = current_time
                elif not self.camera_initialized and current_time - last_camera_init >= camera_init_interval:
                    try:
                        self.camera_initialized = self.camera.initialize()
                    except Exception as e:
                        self.logger.error(f"Camera init error: {e}")
                    last_camera_init = current_time

                # Send data to backend or log offline
                should_send = False
                
                # Send if we have a valid GPS position (for map updates)
                if data.get("gps") and data["gps"].get("latitude") and data["gps"].get("longitude"):
                    should_send = True
                    
                # Also send if we have sign detections (regardless of GPS when allow_detections_without_gps is true)
                if data.get("signs") and (self.config['yolo'].get('allow_detections_without_gps', False) or 
                                         (data.get("gps") and data["gps"].get("latitude") and data["gps"].get("longitude"))):
                    should_send = True
                
                if should_send:
                    if not self.send_data(data, frame if frame is not None else None):
                        self.log_offline(data)
                else:
                    self.logger.debug("No valid data to send")

                # Try to send any offline data
                self.send_offline_data()

                time.sleep(0.1)  # Small delay to prevent CPU overload

        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up resources before shutdown."""
        try:
            if self.gps:
                self.gps.close()
            if self.imu:
                self.imu.close()
            if self.camera:
                self.camera.close()
            if self.sign_detector:
                self.sign_detector.close()
            self.logger.info("All resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    tracker = VehicleTracker("config/config.yaml")
    tracker.run()
