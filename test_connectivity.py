import requests
import socket
import serial
import time
import logging
import yaml

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load config
config = load_config()
gps_config = config.get("gps", {})
backend_config = config.get("backend", {})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        logger.info("Internet connectivity OK (Google DNS)")
        return True
    except socket.error as e:
        logger.error(f"No internet connectivity: {e}")
        return False

def check_backend():
    url = f"{backend_config['url']}{backend_config['endpoint_prefix']}{backend_config['detection_endpoint']}"
    try:
        test_data = {
            "latitude": 48.123456,
            "longitude": 123.123456,
            "speed": 45.6,
            "timestamp": "2025-05-07T10:40:00"
        }
        response = requests.post(url, json=test_data, timeout=30)
        response.raise_for_status()
        logger.info(f"Backend OK: {response.json()}")
        return True
    except requests.RequestException as e:
        logger.error(f"Backend unreachable: {e}")
        return False

def check_lte():
    try:
        ser = serial.Serial(gps_config["port"], gps_config["baudrate"], timeout=1)
        # Check signal quality
        ser.write(b"AT+CSQ\r\n")
        time.sleep(1)
        response = ser.read(1000).decode()
        logger.info(f"LTE signal quality: {response.strip()}")
        # Check network registration
        ser.write(b"AT+COPS?\r\n")
        time.sleep(1)
        response = ser.read(1000).decode()
        logger.info(f"LTE network registration: {response.strip()}")
        ser.close()
        return True
    except Exception as e:
        logger.error(f"LTE module error: {e}")
        return False

if __name__ == "__main__":
    logger.info("Running connectivity diagnostics...")
    check_internet()
    check_backend()
    check_lte()
