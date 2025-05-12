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
    return parser.parse_args()

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
        
        # Prepare PPP command
        ppp_cmd = [
            "sudo", "pppd", 
            port, str(baudrate),
            "noauth", "defaultroute", "usepeerdns", "noipdefault",
            "novj", "novjccomp", "noccp", "nocrtscts",
            "local", "lock"
        ]
        
        logger.info(f"PPP command: {' '.join(ppp_cmd)}")
        
        # Start pppd process
        process = subprocess.Popen(
            ppp_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait a bit for pppd to initialize
        time.sleep(5)
        
        # Check if ppp0 interface exists
        check_ppp = subprocess.run(["ifconfig", "ppp0"], 
                                  stdout=subprocess.PIPE, 
                                  stderr=subprocess.PIPE)
        
        if check_ppp.returncode == 0:
            logger.info("PPP interface established successfully!")
            return True
        else:
            logger.error("PPP interface not established")
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
    logger.info(f"Using port: {args.port}, baudrate: {args.baudrate}, APN: {args.apn}")
    
    try:
        # Open serial port
        logger.info(f"Opening serial port {args.port}...")
        ser = serial.Serial(args.port, args.baudrate, timeout=1)
        
        # Basic AT test
        response = send_command(ser, "AT")
        if "OK" not in response:
            logger.error("Modem not responding to AT commands")
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
            
            # Start pppd
            if start_pppd(args.port, args.baudrate):
                logger.info("LTE connection established successfully!")
                
                # Display interface details
                subprocess.run(["ifconfig", "ppp0"])
                
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
    except Exception as e:
        logger.error(f"Error: {e}")
    
    return True

if __name__ == "__main__":
    sys.exit(0 if main() else 1) 