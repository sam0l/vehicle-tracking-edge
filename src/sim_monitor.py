import serial
import logging
import time
import requests
from datetime import datetime
import json
from collections import deque
import psutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimMonitor:
    def __init__(self, port="/dev/ttyUSB1", baudrate=115200, check_interval=3600, usage_file="data_usage.json", interfaces=None, apn="internet"):
        self.port = port
        self.baudrate = baudrate
        self.check_interval = check_interval
        self.usage_file = usage_file
        self.usage_log = deque(maxlen=10000)  # Keep last 10k records in memory
        self.interfaces = interfaces if interfaces else ["ppp0"]
        self.apn = apn
        self.serial = None
        self.last_counters = self.get_current_counters()
        self.load_usage()

    def initialize(self):
        """Initialize modem connection and set up PPP if needed."""
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            logger.info(f"Opened serial port {self.port}")
            
            # Check if modem is responsive
            response = self.send_at_command("AT")
            if not response or "OK" not in response:
                logger.error(f"Modem not responding correctly: {response}")
                return False
                
            # Check SIM card status
            sim_status = self.send_at_command("AT+CPIN?")
            if not sim_status or "READY" not in sim_status:
                logger.error(f"SIM card not ready: {sim_status}")
                return False
            
            # Check network registration
            reg_status = self.send_at_command("AT+CREG?")
            if not reg_status:
                logger.error("Failed to check network registration")
                return False
            
            # Set APN (essential for internet connectivity)
            apn_cmd = f'AT+CGDCONT=1,"IP","{self.apn}"'
            apn_response = self.send_at_command(apn_cmd)
            if not apn_response or "ERROR" in apn_response:
                logger.error(f"Failed to set APN: {apn_response}")
                # Continue anyway, might be already set
            
            logger.info("SIM Monitor initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SIM monitor: {e}")
            return False

    def send_at_command(self, command, timeout=2):
        """Send AT command and return response."""
        if not self.serial:
            logger.error("Serial port not initialized")
            return None
        
        try:
            self.serial.write((command + "\r\n").encode())
            time.sleep(0.1)
            
            response = ""
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.serial.in_waiting:
                    new_data = self.serial.read(self.serial.in_waiting).decode(errors='ignore')
                    response += new_data
                if "OK" in response or "ERROR" in response:
                    break
                time.sleep(0.1)
            
            logger.debug(f"AT command '{command}' response: {response.strip()}")
            return response.strip()
        except Exception as e:
            logger.error(f"Error sending AT command '{command}': {e}")
            return None

    def load_usage(self):
        try:
            with open(self.usage_file, 'r') as f:
                self.usage_log = deque(json.load(f), maxlen=10000)
        except Exception:
            self.usage_log = deque(maxlen=10000)

    def save_usage(self):
        try:
            with open(self.usage_file, 'w') as f:
                json.dump(list(self.usage_log), f)
        except Exception as e:
            logger.error(f"Failed to save usage log: {e}")

    def log_data_usage(self, bytes_sent, bytes_received):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "bytes_sent": bytes_sent,
            "bytes_received": bytes_received
        }
        self.usage_log.append(entry)
        self.save_usage()

    def get_usage_stats(self, period="1d"):
        now = datetime.now()
        if period == "1d":
            cutoff = now.timestamp() - 86400
        elif period == "1w":
            cutoff = now.timestamp() - 7*86400
        elif period == "1m":
            cutoff = now.timestamp() - 30*86400
        else:
            cutoff = 0
        sent = 0
        received = 0
        points = []
        for entry in self.usage_log:
            ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
            if ts >= cutoff:
                sent += entry["bytes_sent"]
                received += entry["bytes_received"]
                points.append({"timestamp": entry["timestamp"], "bytes_sent": entry["bytes_sent"], "bytes_received": entry["bytes_received"]})
        return {"bytes_sent": sent, "bytes_received": received, "points": points}

    def get_current_counters(self):
        counters = psutil.net_io_counters(pernic=True)
        total_sent = 0
        total_recv = 0
        for iface in self.interfaces:
            if iface in counters:
                total_sent += counters[iface].bytes_sent
                total_recv += counters[iface].bytes_recv
        return {"bytes_sent": total_sent, "bytes_received": total_recv}

    def update_data_usage(self):
        current = self.get_current_counters()
        delta_sent = current["bytes_sent"] - self.last_counters["bytes_sent"]
        delta_recv = current["bytes_received"] - self.last_counters["bytes_received"]
        # Only log if there was activity
        if delta_sent > 0 or delta_recv > 0:
            self.log_data_usage(delta_sent, delta_recv)
        self.last_counters = current

    def check_sim_balance(self):
        """Check SIM card balance using USSD code."""
        # Implementation varies by carrier
        # This is a basic example that might need modification for your specific carrier
        if not hasattr(self, 'ussd_balance_code'):
            logger.warning("No USSD balance code configured")
            return None
            
        response = self.send_at_command(f'AT+CUSD=1,"{self.ussd_balance_code}"', timeout=10)
        if response and "+CUSD:" in response:
            # Extract balance info from response
            try:
                parts = response.split('"')
                if len(parts) > 1:
                    return {"balance": parts[1]}
            except Exception as e:
                logger.error(f"Error parsing balance response: {e}")
        return None

    def get_data_usage(self):
        """Get data usage statistics."""
        return self.get_usage_stats()
    
    def get_network_info(self):
        """Get network information."""
        if not self.serial:
            logger.error("Serial not initialized")
            return None
            
        network_info = {}
        
        # Check registration status
        reg_status = self.send_at_command("AT+CREG?")
        if reg_status and "+CREG:" in reg_status:
            network_info["registration"] = reg_status
            
        # Check operator
        operator = self.send_at_command("AT+COPS?")
        if operator and "+COPS:" in operator:
            network_info["operator"] = operator
            
        # Check connection status
        connection = self.send_at_command("AT+CGACT?")
        if connection and "+CGACT:" in connection:
            network_info["connection"] = connection
            
        return network_info if network_info else None
    
    def get_signal_strength(self):
        """Get signal strength."""
        if not self.serial:
            logger.error("Serial not initialized")
            return None
            
        signal = self.send_at_command("AT+CSQ")
        if signal and "+CSQ:" in signal:
            try:
                # Format: +CSQ: xx,yy where xx is signal strength (0-31, 99=unknown)
                parts = signal.split(":")
                if len(parts) > 1:
                    values = parts[1].strip().split(",")
                    if len(values) > 0:
                        signal_value = int(values[0])
                        # Convert to percentage (0-31 → 0-100%)
                        if signal_value < 99:
                            percentage = min(100, int(signal_value * 100 / 31))
                            return {"signal": signal_value, "percentage": percentage}
            except Exception as e:
                logger.error(f"Error parsing signal strength: {e}")
        return None

    def close(self):
        """Close serial connection."""
        if self.serial:
            self.serial.close()
            self.serial = None
            logger.info("Serial connection closed")

def send_to_backend(balance_info, data_usage, network_info, signal_strength):
    """Send SIM data to backend."""
    try:
        url = "https://vehicle-tracking-backend-bwmz.onrender.com/api/sim-data"
        data = {
            "balance": balance_info,
            "data_usage": data_usage,
            "network_info": network_info,
            "signal_strength": signal_strength,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"Sending SIM data to backend at {url}")
        logger.debug(f"Data being sent: {data}")
        response = requests.post(url, json=data, timeout=30)
        response.raise_for_status()
        logger.info(f"SIM data sent successfully. Response: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error sending SIM data to backend: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending SIM data to backend: {e}")
        return False

def sim_monitor_thread(config=None):
    """Thread to monitor SIM data and connectivity."""
    logger.info("Starting SIM monitor thread...")
    sim_cfg = config['sim'] if config and 'sim' in config else {}
    monitor = SimMonitor(
        port=sim_cfg.get('port', "/dev/ttyUSB1"),
        baudrate=sim_cfg.get('baudrate', 115200),
        check_interval=sim_cfg.get('check_interval', 3600),
        usage_file=sim_cfg.get('usage_file', "data_usage.json"),
        interfaces=sim_cfg.get('interfaces', ["ppp0"]),
        apn=sim_cfg.get('apn', "internet")
    )
    
    if not monitor.initialize():
        logger.error("Failed to initialize SIM monitor")
        return

    try:
        while True:
            logger.info("Starting SIM data collection cycle...")
            
            # Check SIM status first
            logger.info("Checking SIM status...")
            sim_status = monitor.send_at_command("AT+CPIN?")
            logger.info(f"SIM status: {sim_status}")
            
            # Get network registration status
            logger.info("Checking network registration...")
            reg_status = monitor.send_at_command("AT+CREG?")
            logger.info(f"Network registration status: {reg_status}")
            
            # Get operator info
            logger.info("Getting operator info...")
            operator = monitor.send_at_command("AT+COPS?")
            logger.info(f"Operator info: {operator}")
            
            # Get signal strength
            logger.info("Getting signal strength...")
            signal = monitor.send_at_command("AT+CSQ")
            logger.info(f"Signal strength: {signal}")
            
            # Update data usage counters
            monitor.update_data_usage()
            
            # Collect all data
            balance_info = monitor.check_sim_balance()
            data_usage = monitor.get_data_usage()
            network_info = monitor.get_network_info()
            signal_strength = monitor.get_signal_strength()

            # Try to send data to backend
            if any([balance_info, data_usage, network_info, signal_strength]):
                logger.info("Sending collected SIM data to backend...")
                send_result = send_to_backend(balance_info, data_usage, network_info, signal_strength)
                if not send_result:
                    logger.warning("Failed to send data to backend")
            else:
                logger.warning("No SIM data collected in this cycle")

            logger.info(f"Waiting {monitor.check_interval} seconds until next SIM data check...")
            time.sleep(monitor.check_interval)
    except KeyboardInterrupt:
        logger.info("SIM monitor thread stopped by user")
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
    # Load config if available
    import os
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), '../config/config.yaml')
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    else:
        config = None
    # Run the monitor
    sim_monitor_thread(config) 