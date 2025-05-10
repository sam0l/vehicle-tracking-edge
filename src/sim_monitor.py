import serial
import logging
import time
import re
from typing import Optional, Dict
import threading
import os
import json
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
SERIAL_PORT = "/dev/ttyUSB0"  # Adjust as needed
BAUD_RATE = 115200
USSD_CODE = "*123#"  # Smart Telecom balance check USSD code
BACKEND_URL = "https://vehicle-tracking-backend-bwmz.onrender.com/api"  # Adjust as needed

class SimMonitor:
    def __init__(self, port: str, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.logger = logging.getLogger(__name__)
        self.data_consumption = {
            'total_bytes': 0,
            'last_reset': time.time(),
            'current_rate': 0  # bytes per second
        }
        self._lock = threading.Lock()
        
    def connect(self) -> bool:
        """Initialize serial connection to SIM module."""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1
            )
            # Test AT command
            response = self._send_at_command('AT')
            return 'OK' in response
        except Exception as e:
            self.logger.error(f"Failed to connect to SIM module: {e}")
            return False

    def _send_at_command(self, command: str, timeout: int = 5) -> str:
        """Send AT command and get response."""
        if not self.serial:
            raise Exception("Serial connection not initialized")
        
        self.serial.write(f"{command}\r\n".encode())
        time.sleep(0.1)
        
        response = ""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.serial.in_waiting:
                response += self.serial.read(self.serial.in_waiting).decode()
                if 'OK' in response or 'ERROR' in response:
                    break
            time.sleep(0.1)
        
        return response

    def get_data_balance(self) -> Optional[Dict]:
        """Get remaining data balance from SIM card."""
        try:
            # First check if we're registered to network
            response = self._send_at_command('AT+CREG?')
            if '+CREG: 0,1' not in response and '+CREG: 0,5' not in response:
                self.logger.warning("SIM not registered to network")
                return None

            # Get data balance using USSD code (example for checking balance)
            # Note: The actual USSD code may vary by carrier
            response = self._send_at_command('AT+CUSD=1,"*100#",15')
            
            # Parse the response to extract balance
            # This is a simplified example - actual parsing depends on carrier response format
            balance_match = re.search(r'(\d+(?:\.\d+)?)\s*(MB|GB)', response)
            if balance_match:
                amount, unit = balance_match.groups()
                return {
                    'balance': float(amount),
                    'unit': unit,
                    'timestamp': int(time.time())
                }
            return None
        except Exception as e:
            self.logger.error(f"Error getting data balance: {e}")
            return None

    def update_data_consumption(self, bytes_sent: int, bytes_received: int):
        """Update data consumption statistics."""
        with self._lock:
            self.data_consumption['total_bytes'] += (bytes_sent + bytes_received)
            current_time = time.time()
            time_diff = current_time - self.data_consumption['last_reset']
            
            if time_diff >= 1:  # Update rate every second
                self.data_consumption['current_rate'] = (
                    self.data_consumption['total_bytes'] / time_diff
                )
                self.data_consumption['last_reset'] = current_time
                self.data_consumption['total_bytes'] = 0

    def get_data_consumption(self) -> Dict:
        """Get current data consumption statistics."""
        with self._lock:
            return {
                'current_rate': self.data_consumption['current_rate'],
                'timestamp': int(time.time())
            }

    def close(self):
        """Close serial connection."""
        if self.serial:
            self.serial.close()
            self.serial = None

def send_at_command(ser, command, timeout=5):
    """Send AT command and return response."""
    ser.write((command + "\r\n").encode())
    time.sleep(0.5)
    response = ""
    start_time = time.time()
    while (time.time() - start_time) < timeout:
        if ser.in_waiting:
            response += ser.read(ser.in_waiting).decode(errors="ignore")
            if "OK" in response or "ERROR" in response:
                break
        time.sleep(0.1)
    return response

def check_sim_balance():
    """Check SIM balance using USSD."""
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        # Ensure module is ready
        send_at_command(ser, "AT")
        # Send USSD command
        response = send_at_command(ser, f'AT+CUSD=1,"{USSD_CODE}",15')
        ser.close()
        # Parse response for balance info
        balance_info = parse_balance_response(response)
        return balance_info
    except Exception as e:
        logger.error(f"Error checking SIM balance: {e}")
        return None

def parse_balance_response(response):
    """Parse USSD response for balance info."""
    # Look for keywords like UNLI, UNLIMITED, MAGIC DATA, DATA
    keywords = ["UNLI", "UNLIMITED", "MAGIC DATA", "DATA"]
    for keyword in keywords:
        if keyword in response:
            return f"Found {keyword} in balance info: {response}"
    return "No balance info found"

def track_data_usage():
    """Track data usage (simplified example)."""
    global data_usage
    # Simulate data usage (replace with actual tracking logic)
    data_usage += 1000  # Example: 1KB per call
    return data_usage

def send_to_backend(balance_info, data_usage):
    """Send balance and data usage to backend."""
    try:
        payload = {
            "balance": balance_info,
            "data_usage": data_usage
        }
        response = requests.post(f"{BACKEND_URL}/sim-data", json=payload)
        if response.status_code == 200:
            logger.info("Data sent to backend successfully")
        else:
            logger.error(f"Failed to send data to backend: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending data to backend: {e}")

def main():
    """Main function to check balance and track data usage."""
    balance_info = check_sim_balance()
    if balance_info:
        logger.info(f"SIM Balance: {balance_info}")
    data_usage = track_data_usage()
    logger.info(f"Data Usage: {data_usage} bytes")
    send_to_backend(balance_info, data_usage)

if __name__ == "__main__":
    main() 