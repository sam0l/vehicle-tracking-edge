import serial
import logging
import time
import re
from typing import Optional, Dict

class SimMonitor:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        """
        Initialize the SIM monitor.
        
        Args:
            port (str): Serial port for the modem
            baudrate (int): Baud rate for serial communication
        """
        self.logger = logging.getLogger(__name__)
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.last_check = 0
        self.check_interval = 300  # Check every 5 minutes
        self.cached_data = None

    def connect(self) -> bool:
        """Establish connection with the modem."""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1
            )
            # Test AT command
            response = self._send_at_command("AT")
            return "OK" in response
        except Exception as e:
            self.logger.error(f"Failed to connect to modem: {e}")
            return False

    def _send_at_command(self, command: str, wait_time: float = 1.0) -> str:
        """Send AT command and get response."""
        try:
            if not self.serial or not self.serial.is_open:
                self.connect()
            
            self.serial.write(f"{command}\r\n".encode())
            time.sleep(wait_time)
            response = ""
            while self.serial.in_waiting:
                response += self.serial.read(self.serial.in_waiting).decode('utf-8', errors='ignore')
            return response
        except Exception as e:
            self.logger.error(f"Error sending AT command {command}: {e}")
            return ""

    def get_data_balance(self) -> Optional[Dict]:
        """
        Get SIM card data balance.
        For Smart Philippines, we'll use USSD code *123# to check balance.
        """
        current_time = time.time()
        if self.cached_data and (current_time - self.last_check) < self.check_interval:
            return self.cached_data

        try:
            # Send USSD code
            response = self._send_at_command('AT+CUSD=1,"*123#",15', wait_time=5.0)
            
            # Parse response to extract data balance
            # Note: This parsing logic might need adjustment based on actual response format
            data_match = re.search(r'(\d+\.?\d*)\s*(?:MB|GB)', response)
            if data_match:
                balance = float(data_match.group(1))
                unit = 'MB' if 'MB' in response else 'GB'
                
                self.cached_data = {
                    'balance': balance,
                    'unit': unit,
                    'timestamp': time.time()
                }
                self.last_check = current_time
                return self.cached_data
            
            self.logger.warning(f"Could not parse data balance from response: {response}")
            return None

        except Exception as e:
            self.logger.error(f"Error getting data balance: {e}")
            return None

    def close(self):
        """Close the serial connection."""
        if self.serial and self.serial.is_open:
            self.serial.close()

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