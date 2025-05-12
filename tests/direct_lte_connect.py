#!/usr/bin/env python3
"""
Direct LTE connection script using pyserial.
This is a more flexible approach than shell scripts for setting up LTE connections.
"""

import serial
import time
import os
import sys
import subprocess
import argparse
import logging
import glob

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default settings
DEFAULT_PORT = "/dev/ttyUSB2"
DEFAULT_BAUDRATE = 115200
DEFAULT_APN = "internet"

def parse_args():
    parser = argparse.ArgumentParser(description="Direct LTE connection using Python")
    parser.add_argument("--port", "-p", default=DEFAULT_PORT, help="Serial port")
    parser.add_argument("--baudrate", "-b", type=int, default=DEFAULT_BAUDRATE, help="Baudrate")
    parser.add_argument("--apn", "-a", default=DEFAULT_APN, help="APN")
    parser.add_argument("--timeout", "-t", type=int, default=60, help="Connection timeout in seconds")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")
    parser.add_argument("--auto", action="store_true", help="Automatic mode without prompts")
    parser.add_argument("--force", "-f", action="store_true", help="Force connection even if PPP exists")
    return parser.parse_args()

def check_for_ppp():
    """Check if PPP is already running and using the modem."""
    try:
        # Check if ppp0 interface exists
        ifconfig = subprocess.run(["ifconfig", "ppp0"], 
                                stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
        
        if ifconfig.returncode == 0:
            logger.warning("PPP interface already exists! Another connection might be active.")
            return True
            
        # Check for running pppd processes
        ps_output = subprocess.check_output(["ps", "aux"]).decode()
        if "pppd" in ps_output and "ttyUSB" in ps_output:
            logger.warning("PPP daemon is already running!")
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error checking PPP status: {e}")
        return False

def stop_ppp_service():
    """Stop any running PPP service."""
    try:
        logger.info("Stopping any running LTE connection services...")
        subprocess.run(["sudo", "systemctl", "stop", "lte-connection.service"], 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
        time.sleep(2)  # Wait for service to properly stop
        
        # Kill any stray pppd processes
        subprocess.run(["sudo", "killall", "pppd"], 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
        time.sleep(1)
        
        logger.info("All PPP services stopped")
        return True
    except Exception as e:
        logger.error(f"Error stopping PPP services: {e}")
        return False

def find_available_modem():
    """Find an available LTE modem on the system."""
    # Try detecting modem from common patterns
    logger.info("Scanning for available modems...")
    modem_patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyHS*"
    ]
    
    available_ports = []
    for pattern in modem_patterns:
        available_ports.extend(glob.glob(pattern))
    
    if not available_ports:
        logger.error("No potential modem devices found!")
        return None
    
    logger.info(f"Found potential modem devices: {available_ports}")
    
    # Try to open each port and test with AT command
    for port in available_ports:
        logger.info(f"Testing port {port}...")
        try:
            ser = serial.Serial(port, DEFAULT_BAUDRATE, timeout=1)
            ser.write(b"AT\r")
            time.sleep(1)
            response = ser.read(ser.in_waiting).decode(errors='ignore')
            ser.close()
            
            if "OK" in response:
                logger.info(f"Found working modem at {port}!")
                return port
        except Exception as e:
            logger.debug(f"Port {port} test failed: {e}")
    
    logger.error("No responsive modem found!")
    return None

def send_command(ser, command, wait=1, timeout=10):
    """Send AT command to modem and return response."""
    logger.info(f"Sending: {command}")
    ser.write(f"{command}\r".encode())
    
    response = ""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if ser.in_waiting:
            new_data = ser.read(ser.in_waiting).decode(errors='ignore')
            response += new_data
            logger.debug(f"Received data: {new_data}")
            if "OK" in response or "ERROR" in response or "CONNECT" in response:
                break
        time.sleep(0.1)
    
    time.sleep(wait)  # Additional wait after response
    logger.info(f"Response: {response.strip()}")
    return response

def initialize_modem(ser, apn):
    """Initialize the modem with proper settings."""
    commands = [
        "ATZ",             # Reset modem
        "AT+CFUN=1",       # Set full functionality
        "AT+CMEE=2",       # Verbose error messages
        "AT+CREG=1",       # Enable network registration
        f'AT+CGDCONT=1,"IP","{apn}"',  # Set APN
        "AT+CGATT=1",      # Attach to packet service
    ]
    
    for cmd in commands:
        response = send_command(ser, cmd, wait=2)
        if "ERROR" in response:
            logger.warning(f"Command {cmd} returned error: {response}")
            if cmd == "AT+CGATT=1":
                # Try again with longer timeout for network attachment
                logger.info("Retrying network attachment with longer timeout...")
                response = send_command(ser, cmd, wait=5, timeout=30)
    
    # Check registration status
    reg_response = send_command(ser, "AT+CREG?")
    logger.info(f"Registration status: {reg_response}")
    
    # Check PDP context
    pdp_response = send_command(ser, "AT+CGDCONT?")
    logger.info(f"PDP context: {pdp_response}")
    
    return True

def activate_pdp(ser):
    """Activate PDP context."""
    # Deactivate first to ensure clean state
    send_command(ser, "AT+CGACT=0,1", wait=2)
    
    # Activate PDP context
    response = send_command(ser, "AT+CGACT=1,1", wait=5, timeout=20)
    if "ERROR" in response:
        logger.error(f"Failed to activate PDP context: {response}")
        return False
    
    # Verify activation
    check = send_command(ser, "AT+CGACT?")
    if "+CGACT: 1,1" in check:
        logger.info("PDP context activated successfully")
        return True
    else:
        logger.warning(f"PDP context not activated: {check}")
        return False

def dial_connection(ser):
    """Dial the data connection."""
    response = send_command(ser, "ATD*99#", wait=5, timeout=20)
    if "CONNECT" in response:
        logger.info("Connected! Ready for PPP")
        return True
    else:
        logger.error(f"Failed to connect: {response}")
        return False

def start_pppd(port, baudrate):
    """Start pppd process."""
    try:
        logger.info("Starting pppd...")
        
        # Create a simple script file with PPP options
        script_content = f"""#!/bin/sh
# Direct PPP connection script
exec /usr/sbin/pppd {port} {baudrate} noauth defaultroute usepeerdns \\
  noipdefault novj novjccomp noccp nocrtscts local lock \\
  dump debug
"""
        script_path = "/tmp/direct_ppp_connect.sh"
        with open(script_path, "w") as f:
            f.write(script_content)
        
        os.chmod(script_path, 0o755)
        
        # Start pppd via the script
        logger.info(f"Running PPP script: {script_path}")
        process = subprocess.Popen(
            ["sudo", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for PPP to initialize
        logger.info("Waiting for PPP interface...")
        max_wait = 10  # seconds
        for i in range(max_wait):
            check_ppp = subprocess.run(["ifconfig", "ppp0"], 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE)
            if check_ppp.returncode == 0:
                logger.info("PPP interface established successfully!")
                return True
            time.sleep(1)
            logger.info(f"Waiting for PPP ({i+1}/{max_wait})")
        
        logger.error("PPP interface not established after waiting")
        logger.info("Check pppd logs with: dmesg | grep ppp")
        return False
            
    except Exception as e:
        logger.error(f"Error starting pppd: {e}")
        return False

def main():
    args = parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Check if running as root
    if os.geteuid() != 0:
        logger.error("This script requires root privileges")
        sys.exit(1)
    
    logger.info(f"=== Direct LTE Connect ===")
    
    # Check for existing PPP connections
    if check_for_ppp() and not args.force:
        logger.warning("PPP connection already exists")
        user_response = input("Stop existing PPP connections? (y/n): ")
        if user_response.lower() == 'y':
            stop_ppp_service()
        else:
            logger.error("Cannot proceed with active PPP connection")
            return False
    
    # Find or use specified modem port
    port = args.port
    if port == DEFAULT_PORT:
        # Check if the default port exists, if not try to find another
        if not os.path.exists(port):
            logger.warning(f"Default port {port} not found")
            detected_port = find_available_modem()
            if detected_port:
                port = detected_port
            else:
                logger.error("No modem port found. Exiting.")
                return False
    
    logger.info(f"Using port: {port}, baudrate: {args.baudrate}, APN: {args.apn}")
    
    # Try to release modem if it's locked
    subprocess.run(["sudo", "fuser", "-k", port], 
                 stdout=subprocess.PIPE, 
                 stderr=subprocess.PIPE)
    time.sleep(1)
    
    try:
        # Open serial port
        logger.info(f"Opening serial port {port}...")
        ser = serial.Serial(port, args.baudrate, timeout=1)
        
        # Basic AT test
        response = send_command(ser, "AT")
        if "OK" not in response:
            logger.error("Modem not responding to AT commands")
            logger.info("Trying to reset modem...")
            
            # Try a hardware reset sequence
            ser.setDTR(False)  # Drop DTR
            time.sleep(0.5)
            ser.setDTR(True)   # Raise DTR
            time.sleep(0.5)
            
            # Try again
            response = send_command(ser, "AT")
            if "OK" not in response:
                logger.error("Modem still not responding after reset")
                ser.close()
                return False
        
        # Initialize modem
        logger.info("Initializing modem...")
        initialize_modem(ser, args.apn)
        
        # Activate PDP context
        logger.info("Activating PDP context...")
        if not activate_pdp(ser):
            if not args.auto:
                input("PDP activation failed. Press Enter to continue anyway or Ctrl+C to abort...")
        
        # Dial connection
        logger.info("Dialing connection...")
        if dial_connection(ser):
            if not args.auto:
                input("Modem in data mode. Press Enter to start PPP...")
            
            # Close serial port to release it for pppd
            ser.close()
            logger.info("Serial port closed to prepare for PPP")
            
            # Start pppd
            if start_pppd(port, args.baudrate):
                logger.info("LTE connection established successfully!")
                
                # Display interface details
                ifconfig_result = subprocess.run(["ifconfig", "ppp0"], 
                                              stdout=subprocess.PIPE, 
                                              stderr=subprocess.PIPE)
                logger.info(f"PPP interface details:\n{ifconfig_result.stdout.decode()}")
                
                # If not auto mode, wait for user to terminate
                if not args.auto:
                    input("Press Enter to terminate PPP connection...")
                    # Kill pppd
                    subprocess.run(["sudo", "killall", "pppd"])
            else:
                logger.error("Failed to establish PPP connection")
                return False
        else:
            logger.error("Failed to dial connection")
            ser.close()
            return False
    
    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
    except serial.SerialException as e:
        logger.error(f"Serial port error: {e}")
        logger.warning("The port might be in use by another process. Try stopping any PPP services first.")
    except Exception as e:
        logger.error(f"Error: {e}")
    
    return True

if __name__ == "__main__":
    sys.exit(0 if main() else 1) 