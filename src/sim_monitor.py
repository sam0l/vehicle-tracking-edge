import serial
import logging
import time
import requests
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimMonitor:
    def __init__(self, port="/dev/ttyUSB1", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        logger.info(f"Initializing SIM monitor on port {port} with baudrate {baudrate}")
        self.initialize()

    def initialize(self):
        try:
            logger.info("Opening serial port for SIM module...")
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            # Test AT command
            logger.info("Testing AT command...")
            response = self.send_at_command("AT")
            if "OK" not in response:
                logger.error(f"Modem not responding to AT command. Response: {response}")
                raise Exception("Modem not responding to AT command")
            logger.info("SIM monitor initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SIM monitor: {e}")
            return False

    def send_at_command(self, command, wait_time=1):
        try:
            logger.debug(f"Sending AT command: {command}")
            self.serial.write(f"{command}\r\n".encode())
            time.sleep(wait_time)
            response = ""
            while self.serial.in_waiting:
                response += self.serial.read(self.serial.in_waiting).decode()
            logger.debug(f"Received response: {response}")
            return response.strip()
        except Exception as e:
            logger.error(f"Error sending AT command {command}: {e}")
            return None

    def check_sim_balance(self):
        """Get SIM balance using USSD command."""
        try:
            logger.info("Checking SIM balance...")
            # First check if SIM is ready
            response = self.send_at_command("AT+CPIN?")
            if "READY" not in response:
                logger.error(f"SIM not ready. Response: {response}")
                return None

            # Get SIM balance using USSD command
            logger.info("Sending USSD balance check command...")
            response = self.send_at_command('AT+CUSD=1,"*221#",15', wait_time=5)
            if response:
                logger.info(f"Received balance response: {response}")
                return {
                    "balance": response,
                    "timestamp": datetime.now().isoformat()
                }
            logger.warning("No response received for balance check")
            return None
        except Exception as e:
            logger.error(f"Error checking SIM balance: {e}")
            return None

    def get_data_usage(self):
        """Get data usage statistics."""
        try:
            logger.info("Getting data usage statistics...")
            # Get PDP context info
            response = self.send_at_command("AT+CGDCONT?")
            if not response:
                logger.warning("No response received for data usage check")
                return None

            logger.info(f"Received data usage response: {response}")
            return {
                "usage": response,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting data usage: {e}")
            return None

    def get_signal_strength(self):
        """Get signal strength."""
        try:
            logger.info("Getting signal strength...")
            response = self.send_at_command("AT+CSQ")
            if response:
                logger.info(f"Received signal strength: {response}")
                return {
                    "signal": response,
                    "timestamp": datetime.now().isoformat()
                }
            logger.warning("No response received for signal strength check")
            return None
        except Exception as e:
            logger.error(f"Error getting signal strength: {e}")
            return None

    def get_network_info(self):
        """Get network information."""
        try:
            logger.info("Getting network information...")
            # Get network registration status and operator info
            reg_status = self.send_at_command("AT+CREG?")
            operator = self.send_at_command("AT+COPS?")

            logger.info(f"Network registration status: {reg_status}")
            logger.info(f"Network operator: {operator}")

            return {
                "registration": reg_status,
                "operator": operator,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting network info: {e}")
            return None

    def close(self):
        """Close the serial connection."""
        if self.serial and self.serial.is_open:
            logger.info("Closing SIM monitor serial connection")
            self.serial.close()

def send_to_backend(balance_info, data_usage, network_info, signal_strength):
    """Send SIM data to backend."""
    try:
        url = "http://localhost:8000/api/sim-data"  # Update with your backend URL
        data = {
            "balance": balance_info,
            "data_usage": data_usage,
            "network_info": network_info,
            "signal_strength": signal_strength,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"Sending SIM data to backend: {data}")
        response = requests.post(url, json=data)
        response.raise_for_status()
        logger.info("SIM data sent to backend successfully")
        return True
    except Exception as e:
        logger.error(f"Error sending SIM data to backend: {e}")
        return False

def sim_monitor_thread():
    """Thread to monitor SIM data."""
    monitor = SimMonitor()
    if not monitor.initialize():
        logger.error("Failed to initialize SIM monitor")
        return

    try:
        while True:
            logger.info("Starting SIM data collection cycle...")
            balance_info = monitor.check_sim_balance()
            data_usage = monitor.get_data_usage()
            network_info = monitor.get_network_info()
            signal_strength = monitor.get_signal_strength()

            if any([balance_info, data_usage, network_info, signal_strength]):
                logger.info("Sending collected SIM data to backend...")
                send_to_backend(balance_info, data_usage, network_info, signal_strength)
            else:
                logger.warning("No SIM data collected in this cycle")

            logger.info(f"Waiting {3600} seconds until next SIM data check...")
            time.sleep(3600)  # Check every hour
    except Exception as e:
        logger.error(f"Error in SIM monitor thread: {e}")
    finally:
        monitor.close()

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the monitor
    sim_monitor_thread() 