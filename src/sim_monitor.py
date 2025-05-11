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
    def __init__(self, port="/dev/ttyUSB1", baudrate=115200, check_interval=3600, usage_file="data_usage.json", interfaces=None):
        self.port = port
        self.baudrate = baudrate
        self.check_interval = check_interval
        self.usage_file = usage_file
        self.usage_log = deque(maxlen=10000)  # Keep last 10k records in memory
        self.interfaces = interfaces if interfaces else ["ppp0"]
        self.last_counters = self.get_current_counters()
        self.load_usage()

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

    def close(self):
        pass

def send_to_backend(balance_info, data_usage, network_info, signal_strength):
    """Send SIM data to backend."""
    try:
        url = "https://vehicle-tracking-backend-bwmz.onrender.com/api/sim-data"  # Use the correct backend URL
        data = {
            "balance": balance_info,
            "data_usage": data_usage,
            "network_info": network_info,
            "signal_strength": signal_strength,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"Sending SIM data to backend at {url}")
        logger.info(f"Data being sent: {data}")
        response = requests.post(url, json=data)
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
    """Thread to monitor SIM data."""
    logger.info("Starting SIM monitor thread...")
    sim_cfg = config['sim'] if config and 'sim' in config else {}
    monitor = SimMonitor(
        port=sim_cfg.get('port', "/dev/ttyUSB1"),
        baudrate=sim_cfg.get('baudrate', 115200),
        check_interval=sim_cfg.get('check_interval', 3600),
        usage_file=sim_cfg.get('usage_file', "data_usage.json"),
        interfaces=sim_cfg.get('interfaces', None)
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
            
            # Collect all data
            balance_info = monitor.check_sim_balance()
            data_usage = monitor.get_data_usage()
            network_info = monitor.get_network_info()
            signal_strength = monitor.get_signal_strength()

            if any([balance_info, data_usage, network_info, signal_strength]):
                logger.info("Sending collected SIM data to backend...")
                send_to_backend(balance_info, data_usage, network_info, signal_strength)
            else:
                logger.warning("No SIM data collected in this cycle")

            logger.info(f"Waiting {monitor.check_interval} seconds until next SIM data check...")
            time.sleep(monitor.check_interval)  # Use configurable interval
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