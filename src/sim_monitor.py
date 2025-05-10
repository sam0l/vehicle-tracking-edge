import serial
import logging
import time
import re
from typing import Optional, Dict
import threading

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

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(level=logging.DEBUG)
    
    # Test the SIM monitor
    monitor = SimMonitor()
    try:
        balance = monitor.get_data_balance()
        if balance:
            print(f"Data Balance: {balance['balance']} {balance['unit']}")
        else:
            print("Failed to get data balance")
    finally:
        monitor.close() 