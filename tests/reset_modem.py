#!/usr/bin/env python3
"""
Modem hardware reset tool

This script performs a hardware reset on the cellular modem by toggling
serial control lines and triggering a physical reset.
"""

import serial
import time
import sys
import os
import glob
import subprocess
import argparse
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Modem hardware reset tool")
    parser.add_argument("--port", "-p", default="/dev/ttyUSB2", help="Serial port for the modem")
    parser.add_argument("--all", "-a", action="store_true", help="Try all available USB serial ports")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    return parser.parse_args()

def find_modem_ports():
    """Find all potential modem ports."""
    logger.info("Scanning for potential modem ports...")
    
    # Common patterns for modem devices
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyHS*"]
    ports = []
    
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    
    logger.info(f"Found potential ports: {ports}")
    return ports

def kill_port_users(port):
    """Kill any processes using the serial port."""
    logger.info(f"Killing any processes using {port}")
    try:
        # Use fuser to find and kill processes
        subprocess.run(["sudo", "fuser", "-k", port], 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
        
        # Kill any pppd processes
        subprocess.run(["sudo", "killall", "pppd"],
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
        
        # Stop any system services that might be using the modem
        subprocess.run(["sudo", "systemctl", "stop", "lte-connection"], 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
        
        # Give processes time to die
        time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Error killing port users: {e}")
        return False

def hardware_reset(port):
    """Perform hardware reset of the modem via serial control lines."""
    logger.info(f"Attempting hardware reset of modem on {port}")
    
    try:
        # Kill any processes that might be using the port
        kill_port_users(port)
        
        # Open serial port
        ser = serial.Serial(port, 115200, timeout=1)
        
        # Method 1: Toggle DTR (Data Terminal Ready)
        logger.info("Reset method 1: Toggling DTR")
        ser.setDTR(False)  # Set DTR low
        time.sleep(1)
        ser.setDTR(True)   # Set DTR high
        time.sleep(2)
        
        # Method 2: Toggle RTS (Request to Send)
        logger.info("Reset method 2: Toggling RTS")
        ser.setRTS(False)  # Set RTS low
        time.sleep(1)
        ser.setRTS(True)   # Set RTS high
        time.sleep(2)
        
        # Method 3: Send ATZ command for soft reset
        logger.info("Reset method 3: Sending ATZ command")
        ser.write(b"ATZ\r\n")
        time.sleep(1)
        
        # Method 4: Send AT+CFUN=1,1 for full factory reset
        logger.info("Reset method 4: Sending AT+CFUN=1,1 command")
        ser.write(b"AT+CFUN=1,1\r\n")
        time.sleep(5)  # This takes longer
        
        # Close and reopen to reset serial port state
        ser.close()
        time.sleep(1)
        
        # Test if modem responds after reset
        logger.info("Testing modem response after reset...")
        ser = serial.Serial(port, 115200, timeout=3)
        
        # Send AT command to test
        ser.write(b"AT\r\n")
        time.sleep(2)
        
        # Read response
        response = ser.read(ser.in_waiting).decode(errors='ignore')
        ser.close()
        
        if "OK" in response:
            logger.info("Modem is responding correctly after reset!")
            return True
        else:
            logger.warning(f"Modem not responding properly after reset: {response}")
            return False
            
    except Exception as e:
        logger.error(f"Error during hardware reset: {e}")
        return False

def main():
    args = parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Check if running as root
    if os.geteuid() != 0:
        logger.error("This script must be run as root")
        return False
    
    # Kill existing connections and processes
    logger.info("Stopping any active PPP connections")
    subprocess.run(["sudo", "systemctl", "stop", "lte-connection.service"], 
                 stdout=subprocess.PIPE, 
                 stderr=subprocess.PIPE)
    subprocess.run(["sudo", "killall", "pppd"], 
                 stdout=subprocess.PIPE, 
                 stderr=subprocess.PIPE)
    time.sleep(2)
    
    # Reset specific port or try all
    if args.all:
        ports = find_modem_ports()
        success = False
        for port in ports:
            logger.info(f"Trying to reset modem on {port}")
            if hardware_reset(port):
                logger.info(f"Successfully reset modem on {port}")
                success = True
                break
        if not success:
            logger.error("Failed to reset modem on any port")
            return False
    else:
        # Just reset the specified port
        if not hardware_reset(args.port):
            logger.error(f"Failed to reset modem on {args.port}")
            return False
    
    # Final verification
    logger.info("\n=== Final Modem Check ===")
    logger.info("Waiting 5 seconds for modem to fully initialize...")
    time.sleep(5)
    
    try:
        port = args.port if not args.all else ports[0]
        ser = serial.Serial(port, 115200, timeout=2)
        
        # Try extended AT commands to verify modem functionality
        test_commands = [
            "AT",          # Basic test
            "ATI",         # Modem information
            "AT+CPIN?",    # SIM status
            "AT+CSQ",      # Signal quality
            "AT+CREG?"     # Network registration
        ]
        
        all_passed = True
        for cmd in test_commands:
            ser.write(f"{cmd}\r\n".encode())
            time.sleep(1)
            response = ser.read(ser.in_waiting).decode(errors='ignore')
            
            if "OK" in response or "+CREG:" in response or "+CSQ:" in response or "+CPIN:" in response:
                logger.info(f"Command {cmd}: SUCCESS - {response.strip()}")
            else:
                logger.warning(f"Command {cmd}: FAILED - {response.strip()}")
                all_passed = False
        
        ser.close()
        
        if all_passed:
            logger.info("✅ Modem reset and verification successful!")
            logger.info("You can now run the connection script:")
            logger.info("sudo python3 tests/direct_lte_connect.py --debug")
            return True
        else:
            logger.warning("⚠️ Modem responding but some tests failed")
            logger.info("You may need to physically power cycle the modem")
            return False
        
    except Exception as e:
        logger.error(f"Error verifying modem: {e}")
        logger.error("❌ Modem reset failed - you may need to physically power cycle the device")
        return False

if __name__ == "__main__":
    sys.exit(0 if main() else 1) 