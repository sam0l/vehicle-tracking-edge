import os
import sys
import time
import socket
import yaml
import csv
from datetime import datetime
import threading
import pytz  # Added for timezone
import subprocess # Added for running sensors command
import re         # Added for parsing sensors output

# Ensure src is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from sign_detection import SignDetector
from camera import Camera
from gps import GPS
from imu import IMU

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../config/config.yaml')
try:
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"[ERROR] Failed to load config file {CONFIG_PATH}: {e}")
    # Provide minimal default config to prevent crashes
    config = {'camera': {}, 'yolo': {}, 'gps': {}, 'imu': {}, 'general': {}, 'test': {}}

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

# Define timezone from config, default to Singapore
DEFAULT_TIMEZONE = 'Asia/Singapore'
general_cfg = config.get('general', {})
timezone_str = general_cfg.get('timezone', DEFAULT_TIMEZONE)
try:
    app_timezone = pytz.timezone(timezone_str)
except pytz.exceptions.UnknownTimeZoneError:
    print(f"[WARN] Unknown timezone '{timezone_str}' in config, defaulting to {DEFAULT_TIMEZONE}.")
    app_timezone = pytz.timezone(DEFAULT_TIMEZONE)

# Helper: check internet connectivity
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

# Helper: get system temperatures from 'sensors' command
def get_system_temperatures():
    temps = {}
    try:
        # Run the sensors command
        result = subprocess.run(['sensors'], capture_output=True, text=True, check=True, timeout=5)
        output = result.stdout
        print(f"[DEBUG SENSORS OUTPUT]:\n---\n{output}\n---") # DEBUG PRINT
        
        # Regex to find temperature lines (e.g., "temp1: +43.5 C")
        # It captures the thermal zone name (e.g., 'soc_thermal', 'gpu_thermal') and the temp value
        # Adjusted regex to better capture the thermal zone identifier and handle °C
        pattern = re.compile(r"^([a-zA-Z0-9_]+)-virtual-[0-9]+\n(?:.+\n)*?temp1:\s+\+?([0-9.]+)\s*°?C", re.MULTILINE)
        
        matches = pattern.findall(output)
        print(f"[DEBUG REGEX MATCHES (primary)]: {matches}") # DEBUG PRINT
        
        for match in matches:
            zone_name = match[0].replace('_thermal', '') # Simplify name (e.g., 'soc_thermal' -> 'soc')
            temp_value = float(match[1])
            temps[f'temp_{zone_name}'] = temp_value
            
        # Fallback for specific format if the general one fails
        # Example: soc_thermal-virtual-0, temp1: +43.5 C
        if not temps:
             # Adjusted fallback regex to handle °C
             fallback_pattern = re.compile(r"^(\w+_thermal)-virtual-0\s*\nAdapter: Virtual device\s*\ntemp1:\s*\+([0-9.]+)\s*°?C", re.MULTILINE)
             fallback_matches = fallback_pattern.findall(output)
             print(f"[DEBUG REGEX MATCHES (fallback)]: {fallback_matches}") # DEBUG PRINT
             for name, temp_str in fallback_matches:
                 key = name.replace('_thermal','')
                 temps[f'temp_{key}'] = float(temp_str)

        # Calculate average CPU temperature from core temps if available
        cpu_core_keys = ['temp_littlecore', 'temp_bigcore0', 'temp_bigcore1', 'temp_center']
        core_temps = [temps[key] for key in cpu_core_keys if key in temps]
        if core_temps:
            temps['temp_cpu_avg'] = sum(core_temps) / len(core_temps)
        else:
            # Fallback: Check if 'temp_soc' exists as a proxy for CPU temp
            if 'temp_soc' in temps:
                 temps['temp_cpu_avg'] = temps['temp_soc']

    except FileNotFoundError:
        print("[WARN] 'sensors' command not found. Cannot read system temperatures.")
    except subprocess.TimeoutExpired:
        print("[WARN] 'sensors' command timed out.")
    except subprocess.CalledProcessError as e:
        print(f"[WARN] 'sensors' command failed: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error reading system temperatures: {e}")
        
    print(f"[DEBUG FINAL TEMPS DICT]: {temps}") # DEBUG PRINT
    return temps

# Early exit flag
early_exit = threading.Event()

def input_listener():
    while True:
        user_input = input()
        if user_input.strip().lower() == 'x':
            print("[INFO] Early termination requested. Finishing test...")
            early_exit.set()
            break

def main(duration_seconds=duration_seconds, log_file="stress_test_log.csv", temp_log_file="temperature_stress_log.csv"):
    print(f"[INFO] Starting stress test for {duration_seconds} seconds ({duration_seconds/3600:.2f} hours)")
    print(f"[INFO] Logging subsystem status to: {log_file}")
    print(f"[INFO] Logging temperature to: {temp_log_file}")
    print("[INFO] Press 'x' and Enter at any time to end the test early.")
    # Start input listener thread
    listener_thread = threading.Thread(target=input_listener, daemon=True)
    listener_thread.start()

    # Initialize subsystems and track initialization status
    detector = None
    camera = None
    gps = None
    imu = None

    camera_initialized = False
    detector_initialized = False
    gps_initialized = False
    imu_initialized = False

    try:
        detector = SignDetector(config_path=CONFIG_PATH)
        detector_initialized = True
        # print("[INFO] SignDetector initialized.")
    except Exception as e:
        # print(f"[ERROR] Failed to initialize SignDetector: {e}")
        pass # Suppress error print

    try:
        camera = Camera(
            device_id=camera_cfg.get('device_id', 0),
            width=camera_cfg.get('width', 640),
            height=camera_cfg.get('height', 360),
            fps=camera_cfg.get('fps', 30)
        )
        if camera.initialize():
            camera_initialized = True
            # print("[INFO] Camera initialized.")
        else:
            # print("[ERROR] Camera initialization failed.")
            pass # Suppress error print
    except Exception as e:
        # print(f"[ERROR] Failed to initialize Camera: {e}")
        pass # Suppress error print

    try:
        gps = GPS(
            port=gps_cfg.get('port'), # Use .get() for safety
            baudrate=gps_cfg.get('baudrate'),
            timeout=gps_cfg.get('timeout'),
            power_delay=gps_cfg.get('power_delay'),
            agps_delay=gps_cfg.get('agps_delay')
        )
        if gps.initialize():
            gps_initialized = True
            # print("[INFO] GPS initialized.")
        else:
            # print("[ERROR] GPS initialization failed.")
            pass # Suppress error print
    except Exception as e:
        # print(f"[ERROR] Failed to initialize GPS: {e}")
        pass # Suppress error print

    try:
        imu = IMU(
            i2c_bus=imu_cfg.get('i2c_bus'), # Use .get() for safety
            i2c_addresses=imu_cfg.get('i2c_addresses'),
            sample_rate=imu_cfg.get('sample_rate'),
            accel_range=imu_cfg.get('accel_range'),
            gyro_range=imu_cfg.get('gyro_range')
        )
        if imu.initialize():
            imu_initialized = True
            # print("[INFO] IMU initialized.")
        else:
            # print("[ERROR] IMU initialization failed.")
            pass # Suppress error print
    except Exception as e:
        # print(f"[ERROR] Failed to initialize IMU: {e}")
        pass # Suppress error print

    subsystems = ["GPS", "IMU", "DETECTION", "INTERNET"]
    up_counts = {k: 0 for k in subsystems}
    total_counts = {k: 0 for k in subsystems}

    # Define expected system temperature keys (adjust based on your 'sensors' output)
    system_temp_keys = [
        'temp_soc', 'temp_gpu', 'temp_npu', 
        'temp_littlecore', 'temp_bigcore0', 'temp_bigcore1', 'temp_center'
    ]

    # Open both log files
    with open(log_file, "w", newline="") as main_log, open(temp_log_file, "w", newline="") as temp_log:
        main_writer = csv.writer(main_log)
        temp_writer = csv.writer(temp_log)

        # Write headers
        main_writer.writerow(["timestamp"] + subsystems + ["IMU_speed", "IMU_position"])
        temp_writer.writerow(["timestamp", "imu_temp_celsius"] + system_temp_keys)

        start_time = time.time()
        while (time.time() - start_time) < duration_seconds and not early_exit.is_set():
            # Use timezone-aware timestamp
            timestamp = datetime.now(app_timezone).isoformat()

            # 1. GPS Status (Based on initialization)
            gps_status = "WORKING" if gps_initialized else "NOT WORKING"
            gps_data = None
            if gps_initialized and gps:
                try:
                    gps_data = gps.get_data() # Still attempt to read for IMU update
                    if gps_data and imu_initialized and imu:
                        imu.update_gps(gps_data)
                except Exception as gps_e:
                    # Log read error but don't change status if initialized
                    # print(f"[WARN] Failed to read GPS data (but GPS considered working): {gps_e}")
                    gps_status = "WORKING (Read Error)" # Indicate read issue

            # Update GPS counts
            total_counts["GPS"] += 1
            if gps_status.startswith("WORKING"): # Count both "WORKING" and "WORKING (Read Error)"
                up_counts["GPS"] += 1

            # 2. IMU Status (Based on initialization and successful read)
            imu_status = "NOT WORKING"
            imu_data_read_success = False # Flag to track if read succeeded this iteration
            imu_speed = None
            imu_position = None
            imu_temperature = None
            if imu_initialized and imu:
                try:
                    # Try reading core data first
                    imu_data = imu.read_data()
                    if imu_data is not None: # Check if read_data returned something
                        imu_data_read_success = True
                        imu_speed = imu_data.get('speed') # Use data returned by read_data
                        imu_position = imu_data.get('position')
                        imu_temperature = imu_data.get('temp') # Get temp from read_data result
                        imu_status = "WORKING"
                    else:
                        # read_data returned None, still an issue
                        # print("[WARN] imu.read_data() returned None.")
                        imu_status = "NOT WORKING (Read Failed)"

                    # If core data failed, try getting temp separately (optional, might hide issues)
                    # if not imu_data_read_success:
                    #     try:
                    #         imu_temperature = imu.get_temperature()
                    #         if imu_temperature is not None:
                    #             # If ONLY temp works, maybe still mark as partially working?
                    #             imu_status = "WORKING (Temp Only)"
                    #             # Don't set imu_data_read_success = True here
                    #     except Exception as temp_e:
                    #          # print(f"[WARN] Could not read IMU temperature separately: {temp_e}")
                    #          pass

                except Exception as imu_e:
                    # print(f"[ERROR] Error reading IMU data: {imu_e}")
                    imu_status = "NOT WORKING (Exception)"

            # Update IMU counts
            total_counts["IMU"] += 1
            if imu_status.startswith("WORKING"):
                up_counts["IMU"] += 1

            # 3. Sign Detection Status (Based on initialization and successful detection)
            detection_status = "NOT WORKING"
            if detector_initialized and detector and camera_initialized and camera:
                try:
                    frame = camera.get_frame()
                    if frame is not None:
                        # Detection itself signifies working state for this iteration
                        detector.detect(frame) # Assuming detect raises error on failure
                        detection_status = "WORKING"
                    else:
                        # print("[WARN] Failed to get frame from camera for detection.")
                        detection_status = "NOT WORKING (No Frame)"
                except Exception as det_e:
                    # print(f"[ERROR] Error during detection: {det_e}")
                    detection_status = "NOT WORKING (Exception)"

            # Update Detection counts
            total_counts["DETECTION"] += 1
            if detection_status == "WORKING":
                up_counts["DETECTION"] += 1

            # 4. Internet
            internet_status = "WORKING" if check_internet() else "NOT WORKING"
            total_counts["INTERNET"] += 1
            if internet_status == "WORKING":
                up_counts["INTERNET"] += 1

            # 5. System Temperatures
            system_temps = get_system_temperatures()
            # Get the specific temperature for 'center_thermal' if available
            cpu_temp_center = system_temps.get('temp_center') 

            # Print summary line to console with status
            summary_line = (
                f"GPS: {gps_status} | IMU: {imu_status} | DETECTION: {detection_status} | INTERNET: {internet_status} "
                f"| Speed: {f'{imu_speed:.1f}' if imu_speed is not None else 'N/A'} "
                f"| Pos: {f'{imu_position[0]:.5f},{imu_position[1]:.5f}' if imu_position else 'N/A'} "
                f"| IMU Temp: {f'{imu_temperature:.1f}C' if imu_temperature is not None else 'N/A'} "
                f"| CPU Temp: {f'{cpu_temp_center:.1f}C' if cpu_temp_center is not None else 'N/A'}" # Use temp_center directly
            )
            print(summary_line)

            # Write to main log (include status text)
            main_writer.writerow([
                timestamp, gps_status, imu_status, detection_status, internet_status, imu_speed, imu_position
            ])

            # Write to temperature log if temperature was read successfully
            if imu_initialized and imu_temperature is not None:
                # Prepare data row for temperature log
                temp_row = [timestamp, imu_temperature]
                # Append system temps in the correct order, using None if key is missing
                for key in system_temp_keys:
                    temp_row.append(system_temps.get(key, None))
                temp_writer.writerow(temp_row)
            else:
                 # Still log system temps even if IMU temp fails, but put None for IMU temp
                temp_row = [timestamp, None] # Add None for imu_temp_celsius
                for key in system_temp_keys:
                    temp_row.append(system_temps.get(key, None))
                # Only write if we actually got any system temps
                if any(v is not None for v in temp_row[1:]): # Check if any temp value exists
                    temp_writer.writerow(temp_row)

            time.sleep(1)

    # Suppress final uptime stats print
    # print("\n[INFO] Test complete. Uptime summary:")
    # for subsystem in subsystems:
    #     up = up_counts[subsystem]
    #     total = total_counts[subsystem]
    #     down = total - up
    #     uptime_percent = (up / total) * 100 if total else 0
    #     print(f"{subsystem}: Uptime={up}s, Breakdown={down}s, Uptime%={uptime_percent:.2f}")

if __name__ == "__main__":
    main() 