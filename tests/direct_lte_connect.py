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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('lte_connect.log')
    ]
)

class LTEConnector:
    def __init__(self, port="/dev/ttyUSB2", baudrate=115200, apn="internet", debug=False):
        self.port = port
        self.baudrate = baudrate
        self.apn = apn
        self.debug = debug
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)
        self.ser = None
        self.ppp_running = False

    def open_port(self):
        """Open serial port connection to the modem."""
        logging.info(f"Opening serial port {self.port}...")
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            return True
        except Exception as e:
            logging.error(f"Failed to open serial port: {e}")
            return False

    def send_command(self, command, wait_time=2, check_ok=True):
        """Send AT command to the modem and return response."""
        if not self.ser:
            logging.error("Serial port not open")
            return None

        logging.info(f"Sending: {command}")
        try:
            # Send command
            self.ser.write(f"{command}\r".encode())
            
            # Wait for response
            time.sleep(0.1)
            response = ""
            start_time = time.time()
            
            while (time.time() - start_time) < wait_time:
                if self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting).decode(errors='ignore')
                    if self.debug:
                        logging.debug(f"Received data: {data}")
                    response += data
                
                if check_ok and ("OK" in response or "ERROR" in response or "CONNECT" in response):
                    break
                    
                time.sleep(0.1)
            
            logging.info(f"Response: {response}")
            return response
        except Exception as e:
            logging.error(f"Error sending command: {e}")
            return None

    def initialize_modem(self):
        """Initialize the modem for PPP connection."""
        logging.info("Initializing modem...")
        
        # Reset modem
        self.send_command("ATZ")
        
        # Set modem to full functionality
        self.send_command("AT+CFUN=1")
        
        # Enable verbose error reporting
        self.send_command("AT+CMEE=2")
        
        # Enable network registration URC
        self.send_command("AT+CREG=1")
        
        # Set APN
        self.send_command(f'AT+CGDCONT=1,"IP","{self.apn}"')
        
        # Attach to GPRS
        self.send_command("AT+CGATT=1")
        
        # Check registration status
        reg_response = self.send_command("AT+CREG?")
        logging.info(f"Registration status: {reg_response}")
        
        # Check PDP context
        pdp_response = self.send_command("AT+CGDCONT?")
        logging.info(f"PDP context: {pdp_response}")
        
        # Deactivate first, then reactivate PDP context
        logging.info("Activating PDP context...")
        self.send_command("AT+CGACT=0,1")
        act_response = self.send_command("AT+CGACT=1,1", wait_time=5)
        
        if "ERROR" in act_response:
            logging.error(f"Failed to activate PDP context: {act_response}")
            input("PDP activation failed. Press Enter to continue anyway or Ctrl+C to abort...")
        
        return True

    def start_ppp_call(self):
        """Start a data call to prepare for PPP."""
        logging.info("Dialing connection...")
        response = self.send_command("ATD*99#", wait_time=5, check_ok=False)
        
        if "CONNECT" in response:
            logging.info("Connected! Ready for PPP")
            input("Modem in data mode. Press Enter to start PPP...")
            return True
        else:
            logging.error(f"Failed to connect: {response}")
            return False
            
    def setup_ppp_systemd(self):
        """Create proper systemd-friendly PPP configuration."""
        try:
            # Create chat script
            chat_script = "/etc/ppp/chat-lte"
            logging.info(f"Creating chat script at {chat_script}")
            
            chat_content = f"""ABORT "BUSY"
ABORT "NO CARRIER"
ABORT "NO DIALTONE"
ABORT "ERROR"
ABORT "NO ANSWER"
TIMEOUT 45
'' AT
OK AT+CFUN=1
OK AT+CGATT=1
OK AT+CREG=1
OK 'AT+CGDCONT=1,"IP","{self.apn}"'
OK ATD*99#
CONNECT ''
"""
            with open(chat_script, 'w') as f:
                f.write(chat_content)
            os.chmod(chat_script, 0o644)
            
            # Create PPP peer config
            peer_file = "/etc/ppp/peers/lte"
            logging.info(f"Creating PPP peer config at {peer_file}")
            
            peer_content = f"""# LTE modem connection settings
{self.port}
{self.baudrate}
connect "/usr/sbin/chat -v -f {chat_script}"
noauth
defaultroute
usepeerdns
noipdefault
novj
novjccomp
noccp
nocrtscts
persist
maxfail 0
holdoff 10
debug
"""
            with open(peer_file, 'w') as f:
                f.write(peer_content)
            os.chmod(peer_file, 0o644)
            
            # Create systemd service
            service_file = "/etc/systemd/system/lte-connection.service"
            logging.info(f"Creating systemd service at {service_file}")
            
            service_content = """[Unit]
Description=LTE PPP Connection
After=network.target

[Service]
Type=simple
ExecStart=/usr/sbin/pppd call lte
Restart=always
RestartSec=30
TimeoutSec=120

[Install]
WantedBy=multi-user.target
"""
            with open(service_file, 'w') as f:
                f.write(service_content)
            os.chmod(service_file, 0o644)
            
            # Reload systemd
            subprocess.run(["systemctl", "daemon-reload"])
            subprocess.run(["systemctl", "enable", "lte-connection.service"])
            
            logging.info("PPP configuration and systemd service created successfully")
            return True
            
        except Exception as e:
            logging.error(f"Failed to setup PPP configuration: {e}")
            return False

    def start_ppp(self):
        """Start PPP connection."""
        if not self.ser:
            logging.error("Serial not initialized")
            return False
            
        # Close serial before pppd takes over
        self.ser.close()
        self.ser = None
        logging.info("Serial port closed to prepare for PPP")
        
        # Create PPP shell script
        ppp_script = "/tmp/direct_ppp_connect.sh"
        logging.info("Starting pppd...")
        
        with open(ppp_script, "w") as f:
            f.write(f"""#!/bin/bash
pppd {self.port} {self.baudrate} noauth defaultroute usepeerdns \
noipdefault novj novjccomp noccp nocrtscts debug
""")
        os.chmod(ppp_script, 0o755)
        
        logging.info(f"Running PPP script: {ppp_script}")
        subprocess.Popen(ppp_script, shell=True)
        
        # Wait for pppd to establish connection
        logging.info("Waiting for PPP interface...")
        for i in range(10):
            logging.info(f"Waiting for PPP ({i+1}/10)")
            time.sleep(1)
            
            # Check if ppp interface exists
            ifconfig = subprocess.run(["ifconfig"], stdout=subprocess.PIPE, text=True)
            if "ppp0" in ifconfig.stdout:
                self.ppp_running = True
                logging.info("PPP interface established successfully!")
                logging.info("LTE connection established successfully!")
                
                # Show interface details
                ppp_details = subprocess.run(["ifconfig", "ppp0"], stdout=subprocess.PIPE, text=True)
                logging.info(f"PPP interface details:\n{ppp_details.stdout}")
                return True
                
        logging.error("Failed to establish PPP connection")
        return False

    def stop_ppp(self):
        """Stop PPP connection."""
        if self.ppp_running:
            subprocess.run(["killall", "pppd"])
            logging.info("PPP connection terminated")
            self.ppp_running = False

    def close(self):
        """Clean up resources."""
        self.stop_ppp()
        if self.ser:
            self.ser.close()
            self.ser = None

def detect_modem_port():
    """Try to automatically detect the correct modem port."""
    for port in ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3"]:
        try:
            ser = serial.Serial(port, 115200, timeout=1)
            ser.write(b"AT\r")
            time.sleep(0.5)
            response = ser.read(ser.in_waiting).decode(errors='ignore')
            ser.close()
            
            if "OK" in response:
                logging.info(f"Found modem at {port}")
                return port
        except:
            pass
    
    return "/dev/ttyUSB2"  # Default fallback

def main():
    parser = argparse.ArgumentParser(description="Connect to LTE network using PPP")
    parser.add_argument("--port", help="Serial port of the modem", default=None)
    parser.add_argument("--baudrate", type=int, help="Baudrate", default=115200)
    parser.add_argument("--apn", help="APN name", default="internet")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--systemd", action="store_true", help="Set up systemd service for auto-connect")
    args = parser.parse_args()
    
    logging.info("=== Direct LTE Connect ===")
    
    # Auto-detect port if not specified
    port = args.port if args.port else detect_modem_port()
    
    logging.info(f"Using port: {port}, baudrate: {args.baudrate}, APN: {args.apn}")
    
    connector = LTEConnector(port, args.baudrate, args.apn, args.debug)
    
    try:
        if not connector.open_port():
            sys.exit(1)
            
        if not connector.initialize_modem():
            sys.exit(1)
        
        if args.systemd:
            if connector.setup_ppp_systemd():
                logging.info("PPP configuration set up for systemd auto-connect on boot")
                logging.info("To enable and start the service:")
                logging.info("  sudo systemctl enable lte-connection.service")
                logging.info("  sudo systemctl start lte-connection.service")
                sys.exit(0)
            else:
                logging.error("Failed to set up systemd configuration")
                sys.exit(1)
            
        if not connector.start_ppp_call():
            sys.exit(1)
            
        if not connector.start_ppp():
            sys.exit(1)
            
        input("Press Enter to terminate PPP connection...")
            
    except KeyboardInterrupt:
        logging.info("Operation cancelled by user")
    finally:
        connector.close()

if __name__ == "__main__":
    main() 