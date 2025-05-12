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
            # 6 = registered, for "SMS only", home network (some networks)
            # 7 = registered, for "SMS only", roaming (some networks)
            parts = response.split("+CREG:")[1].strip().split(",")
            
            # Clean up the status value to handle line breaks and other characters
            status_str = parts[1].strip()
            status_str = status_str.split()[0]  # Take just the first part before any whitespace
            
            try:
                status = int(status_str)
            except ValueError:
                logger.error(f"Could not parse registration status: '{status_str}'")
                return False
                
            status_text = {
                0: "Not registered, not searching",
                1: "Registered, home network",
                2: "Not registered, searching",
                3: "Registration denied",
                4: "Unknown",
                5: "Registered, roaming",
                6: "Registered, for SMS only, home network",
                7: "Registered, for SMS only, roaming"
            }.get(status, f"Unknown status code: {status}")
            
            logger.info(f"Network registration: {status_text} ({status})")
            return status in [1, 5, 6, 7]  # Consider SMS-only registration as valid
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
            else:
                # Handle numeric format (no quotes)
                parts = response.split("+COPS:")[1].strip().split(",")
                if len(parts) >= 3:
                    operator = parts[2].strip()
                    if operator.startswith('"') and operator.endswith('"'):
                        operator = operator[1:-1]
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
    
    # Check if we need to attach to the network first
    attach_response = send_command(ser, "AT+CGATT=1", wait=5)
    logger.info(f"Network attachment response: {attach_response}")
    
    # Get PDP context parameters before activation
    pdp_params = send_command(ser, "AT+CGDCONT?")
    logger.info(f"PDP context parameters: {pdp_params}")
    
    # Activate context with longer timeout
    response = send_command(ser, "AT+CGACT=1,1", wait=10)
    if "ERROR" in response:
        logger.error(f"Failed to activate PDP context: {response}")
        
        # Try alternative approaches
        logger.info("Trying alternative PDP context activation...")
        
        # Some modems require explicit authentication setup
        auth_setup = send_command(ser, f'AT+CGAUTH=1,0,"{apn}","{apn}"', wait=2)
        logger.info(f"Auth setup response: {auth_setup}")
        
        # Try activation again
        response = send_command(ser, "AT+CGACT=1,1", wait=10)
        
        if "ERROR" in response:
            logger.error("PDP context activation still failed")
            return False
    
    # Check if context is activated
    context_check = send_command(ser, "AT+CGACT?")
    if "+CGACT: 1,1" in context_check:
        logger.info("PDP context successfully activated")
    
    # Dial
    logger.info(f"Dialing with command: {DIAL_COMMAND}")
    response = send_command(ser, DIAL_COMMAND, wait=10)
    
    # Look for CONNECT in response
    if "CONNECT" in response:
        logger.info("Connected! PPP handshake should begin")
        return True
    else:
        logger.error(f"Failed to connect for PPP: {response}")
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

def start_pppd(apn=APN, chatscript=None):
    """Start pppd manually with appropriate options."""
    logger.info("Starting pppd manually...")
    try:
        # Create a simple chat script if not provided
        if not chatscript:
            chat_content = f"""
ABORT "BUSY"
ABORT "NO CARRIER"
ABORT "NO DIALTONE"
ABORT "ERROR"
ABORT "NO ANSWER"
TIMEOUT 30
"" "AT"
OK "AT+CGDCONT=1,\\"IP\\",\\"{apn}\\""
OK "ATD*99#"
CONNECT ""
            """
            chatscript = "/tmp/lte_chat_script.txt"
            with open(chatscript, "w") as f:
                f.write(chat_content)
            logger.info(f"Created chat script at {chatscript}")
        
        # Build pppd command
        pppd_cmd = [
            "sudo", "pppd", PORT, str(BAUDRATE),
            "connect", f"chat -v -f {chatscript}",
            "noauth", "defaultroute", "usepeerdns", "noipdefault",
            "novj", "novjccomp", "noccp", "nocrtscts", "persist", 
            "lock", "lcp-echo-interval", "10", "lcp-echo-failure", "3"
        ]
        
        # Execute pppd
        logger.info(f"Running pppd command: {' '.join(pppd_cmd)}")
        result = subprocess.Popen(pppd_cmd, 
                                stdout=subprocess.PIPE, 
                                stderr=subprocess.PIPE)
        
        # Wait a bit for pppd to initialize
        time.sleep(5)
        return True
    except Exception as e:
        logger.error(f"Error starting pppd: {e}")
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
            logger.warning("Not registered to network - verify SIM card is active")
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
                if not initialize_ppp(ser):
                    logger.warning("AT-based PPP initialization failed. Trying direct pppd method...")
                    # Close serial to allow pppd to use it
                    ser.close()
                    start_pppd()
                    # Reopen serial for final checks
                    try:
                        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
                    except:
                        logger.info("Could not reopen serial port - it may be in use by pppd (which is good)")
                
                logger.info("PPP initialization command sent. Check network status.")
                logger.info("Wait 10-15 seconds for the connection to establish.")
                time.sleep(5)
                
                # Check if PPP interface came up
                if check_ppp_interface():
                    logger.info("PPP interface is now active!")
                    # Check internet connectivity 
                    if check_internet_connectivity():
                        logger.info("Internet connectivity established!")
                    else:
                        logger.warning("PPP interface is up but internet connectivity failed")
        
        # Summary
        logger.info("\n=== Summary ===")
        logger.info(f"Modem response: {'OK' if 'OK' in response else 'Not responding'}")
        logger.info(f"SIM status: {'Ready' if check_sim_status(ser) else 'Not ready'}")
        logger.info(f"Signal strength: {percentage}% ({signal}/31 bars)")
        logger.info(f"Network registration: {'Registered' if registered else 'Not registered'}")
        logger.info(f"Operator: {operator or 'Unknown'}")
        logger.info(f"PPP interface: {'Active' if check_ppp_interface() else 'Not active'}")
        logger.info(f"Internet connectivity: {'OK' if check_internet_connectivity() else 'No connection'}")
        
        # Next steps
        logger.info("\n=== Next Steps ===")
        if not ppp_exists or not internet_ok:
            logger.info("If PPP connection failed, try these troubleshooting steps:")
            logger.info("1. Verify your SIM card is active and has a data plan")
            logger.info("2. Check the correct APN for your provider (current: {APN})")
            logger.info("3. Ensure good signal strength and proper antenna connection")
            logger.info("4. Try manual PPP setup: sudo pppd /dev/ttyUSB2 115200 connect 'chat -v -f /etc/ppp/chat-script'")
        else:
            logger.info("LTE connection appears to be working correctly")
        
        # Close serial port
        try:
            ser.close()
            logger.info("Serial port closed")
        except:
            pass
        
    except serial.SerialException as e:
        logger.error(f"Serial error: {e}")
        logger.error(f"Check if {PORT} is the correct port and if it's accessible")
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main() 