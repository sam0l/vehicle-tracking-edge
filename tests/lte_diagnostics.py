#!/usr/bin/env python3
import serial
import time
import sys
import os
import yaml
import subprocess
import logging
import socket

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load config
config_path = os.path.join(os.path.dirname(__file__), '../config/config.yaml')
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
else:
    logger.error("Config file not found")
    config = {}

# Get SIM configuration
sim_config = config.get('sim', {})
PORT = sim_config.get('port', "/dev/ttyUSB2")
BAUDRATE = sim_config.get('baudrate', 115200)
APN = sim_config.get('apn', "internet")
DIAL_COMMAND = sim_config.get('dial_command', "ATD*99#")

def send_command(ser, command, wait=1, show_command=True):
    """Send AT command to modem and return response."""
    if show_command:
        logger.info(f"Sending: {command}")
    ser.write((command + "\r\n").encode())
    time.sleep(wait)
    response = ""
    while ser.in_waiting:
        response += ser.read(ser.in_waiting).decode(errors='ignore')
        time.sleep(0.1)
    if response:
        logger.info(f"Response: {response.strip()}")
    return response

def check_sim_status(ser):
    """Check if SIM card is ready."""
    response = send_command(ser, "AT+CPIN?")
    if "+CPIN: READY" in response:
        logger.info("SIM is ready")
        return True
    else:
        logger.error("SIM not ready or not inserted")
        return False

def check_signal_quality(ser):
    """Check signal strength."""
    response = send_command(ser, "AT+CSQ")
    if "+CSQ:" in response:
        try:
            # Format: +CSQ: xx,yy where xx is signal strength (0-31, 99=unknown)
            parts = response.split("+CSQ:")[1].strip().split(",")
            signal = int(parts[0])
            if signal < 99:
                # Convert to percentage (0-31 → 0-100%)
                percentage = min(100, int(signal * 100 / 31))
                logger.info(f"Signal strength: {signal}/31 ({percentage}%)")
                return signal, percentage
            else:
                logger.warning("Signal strength unknown")
                return None, None
        except Exception as e:
            logger.error(f"Error parsing signal strength: {e}")
            return None, None
    else:
        logger.error("Failed to get signal strength")
        return None, None

def check_network_registration(ser):
    """Check network registration status."""
    response = send_command(ser, "AT+CREG?")
    if "+CREG:" in response:
        try:
            # Format: +CREG: n,stat, where stat is:
            # 0 = not registered, not searching
            # 1 = registered, home network
            # 2 = not registered, searching
            # 3 = registration denied
            # 4 = unknown
            # 5 = registered, roaming
            parts = response.split("+CREG:")[1].strip().split(",")
            status = int(parts[1])
            status_text = {
                0: "Not registered, not searching",
                1: "Registered, home network",
                2: "Not registered, searching",
                3: "Registration denied",
                4: "Unknown",
                5: "Registered, roaming"
            }.get(status, "Unknown status")
            
            logger.info(f"Network registration: {status_text} ({status})")
            return status in [1, 5]  # Registered if status is 1 or 5
        except Exception as e:
            logger.error(f"Error parsing registration status: {e}")
            return False
    else:
        logger.error("Failed to get registration status")
        return False

def check_operator(ser):
    """Check current operator."""
    response = send_command(ser, "AT+COPS?")
    if "+COPS:" in response:
        # Try to extract operator name
        try:
            if '"' in response:
                operator = response.split('"')[1]
                logger.info(f"Operator: {operator}")
                return operator
        except Exception as e:
            logger.error(f"Error parsing operator: {e}")
    return None

def configure_apn(ser, apn):
    """Configure APN for data connection."""
    logger.info(f"Setting APN to: {apn}")
    # Check current APN
    current_apn = send_command(ser, "AT+CGDCONT?")
    
    # Set APN
    cmd = f'AT+CGDCONT=1,"IP","{apn}"'
    response = send_command(ser, cmd)
    if "OK" in response:
        logger.info("APN set successfully")
        return True
    else:
        logger.error("Failed to set APN")
        return False

def initialize_ppp(ser):
    """Start PPP connection process."""
    logger.info("Initializing PPP connection...")
    # Reset connection if active
    send_command(ser, "AT+CGACT=0,1")
    time.sleep(1)
    
    # Activate context
    response = send_command(ser, "AT+CGACT=1,1")
    if "OK" not in response:
        logger.error("Failed to activate PDP context")
        return False
    
    # Dial
    logger.info(f"Dialing with command: {DIAL_COMMAND}")
    response = send_command(ser, DIAL_COMMAND)
    
    # Look for CONNECT in response
    if "CONNECT" in response:
        logger.info("Connected! PPP handshake should begin")
        return True
    else:
        logger.error("Failed to connect for PPP")
        return False

def check_internet_connectivity():
    """Check if the device can reach the internet."""
    try:
        # Try Google DNS
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        logger.info("Internet connectivity: OK")
        return True
    except socket.error as e:
        logger.error(f"No internet connectivity: {e}")
        return False

def check_ppp_interface():
    """Check if ppp0 interface exists."""
    try:
        result = subprocess.run(["ifconfig", "ppp0"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("PPP interface exists")
            return True
        else:
            logger.error("PPP interface does not exist")
            return False
    except Exception as e:
        logger.error(f"Error checking PPP interface: {e}")
        return False

def main():
    """Run LTE diagnostics."""
    logger.info(f"=== LTE Diagnostics ===")
    logger.info(f"Using port: {PORT}, baudrate: {BAUDRATE}")
    
    try:
        # Step 1: Open serial port
        logger.info("Opening serial port...")
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
        logger.info("Serial port opened successfully")
        
        # Step 2: Basic AT command test
        response = send_command(ser, "AT")
        if "OK" not in response:
            logger.error("Modem not responding to AT commands")
            ser.close()
            return
        
        # Step 3: Check SIM status
        if not check_sim_status(ser):
            logger.error("SIM card issue detected")
            ser.close()
            return
        
        # Step 4: Check signal quality
        signal, percentage = check_signal_quality(ser)
        if signal is None or signal < 10:  # Less than 10 is poor signal
            logger.warning("Poor signal strength or unknown")
            
        # Step 5: Check network registration
        registered = check_network_registration(ser)
        if not registered:
            logger.error("Not registered to network")
            # Continue anyway to see other diagnostics
        
        # Step 6: Check operator
        operator = check_operator(ser)
        
        # Step 7: Check APN settings
        logger.info("Checking current APN settings...")
        send_command(ser, "AT+CGDCONT?")
        
        # Step 8: Configure APN
        logger.info(f"Setting APN to: {APN}")
        configure_apn(ser, APN)
        
        # Step 9: Check PPP interface status
        ppp_exists = check_ppp_interface()
        
        # Step 10: Check Internet connectivity
        internet_ok = check_internet_connectivity()
        
        # Step 11: If not connected, offer to initialize PPP connection
        if not ppp_exists or not internet_ok:
            logger.info("PPP connection not active or no internet connectivity")
            
            user_input = input("Attempt to set up PPP connection? (y/n): ")
            if user_input.lower() == 'y':
                initialize_ppp(ser)
                logger.info("PPP initialization command sent. Check network status.")
        
        # Summary
        logger.info("\n=== Summary ===")
        logger.info(f"Modem response: {'OK' if 'OK' in response else 'Not responding'}")
        logger.info(f"SIM status: {'Ready' if check_sim_status(ser) else 'Not ready'}")
        logger.info(f"Signal strength: {percentage}% ({signal}/31 bars)")
        logger.info(f"Network registration: {'Registered' if registered else 'Not registered'}")
        logger.info(f"Operator: {operator or 'Unknown'}")
        logger.info(f"PPP interface: {'Active' if ppp_exists else 'Not active'}")
        logger.info(f"Internet connectivity: {'OK' if internet_ok else 'No connection'}")
        
        # Close serial port
        ser.close()
        logger.info("Serial port closed")
        
    except serial.SerialException as e:
        logger.error(f"Serial error: {e}")
        logger.error(f"Check if {PORT} is the correct port and if it's accessible")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main() 