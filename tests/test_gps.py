import serial
import time
import yaml
import argparse
import os
import datetime
import sys

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load config
config = load_config()
gps_config = config.get("gps", {})

# GPS module settings
PORT = gps_config["port"]
BAUDRATE = gps_config["baudrate"]
TIMEOUT = gps_config["timeout"]
POWER_DELAY = gps_config["power_delay"]
AGPS_DELAY = gps_config.get("agps_delay", 5)  # Default to 5 seconds if not defined

def debug_print(message, level=0):
    """Print debug messages with formatting"""
    indent = "  " * level
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] {indent}{message}")

def send_at_command(ser, command, expected_response="OK", timeout=2, log_command=True, retry=0):
    """Send AT command with optional retry"""
    success = False
    full_response = ""
    
    for attempt in range(retry + 1):
        try:
            if log_command:
                if attempt > 0:
                    debug_print(f"\n>> Sending: {command} (Retry {attempt}/{retry})")
                else:
                    debug_print(f"\n>> Sending: {command}")
                    
            # Clear buffer before sending
            ser.reset_input_buffer()
            
            # Send command with CR+LF
            ser.write((command + "\r\n").encode())
            time.sleep(0.1)
            
            response = ""
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                if ser.in_waiting:
                    chunk = ser.read(ser.in_waiting).decode(errors="ignore")
                    response += chunk
                    full_response += chunk
                    
                    # Check if expected response is present
                    if expected_response in response:
                        if log_command:
                            debug_print(f"<< Response: {response.strip()}")
                        success = True
                        break
                        
                # Small sleep to prevent CPU overuse
                time.sleep(0.01)
            
            # If we found expected response, break retry loop
            if success:
                break
                
            # Log timeout only if we're going to retry or it's the last attempt
            if log_command:
                debug_print(f"<< Response (timeout): {response.strip()}")
                
        except Exception as e:
            debug_print(f"Error sending {command}: {e}")
            response = str(e)
            
    return full_response, success

def get_full_response(ser, timeout=5):
    """Get full response from serial port with timeout"""
    response = ""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if ser.in_waiting:
            response += ser.read(ser.in_waiting).decode(errors="ignore")
        time.sleep(0.01)
    return response.strip()

def parse_gnss_info(response):
    """Parse the CGNSSINFO response with better structure"""
    debug_print(f"Parsing GNSS info from: {response}", level=2)
    if "+CGNSSINFO: " not in response:
        debug_print("No CGNSSINFO in response", level=2)
        return None
    
    try:
        # Split by CGNSSINFO and take everything after it
        parts = response.split("+CGNSSINFO: ")[1].split("\r\n")[0].strip()
        fields = parts.split(",")
        
        debug_print(f"CGNSSINFO fields: {fields}", level=2)
        
        if len(fields) < 9:
            debug_print(f"Incomplete response: only {len(fields)} fields", level=2)
            return {'fix': False, 'reason': 'incomplete_response'}
            
        # Parse based on the observed format from minicom
        # Example: 3,17,,12,09,14.6192493,N,121.1041031,E,120525,101533.00,77.1,0.000,6
        fix_status = {'fix': False, 'reason': 'no_data'}
        
        # Check if we have latitude and longitude
        if fields[5] and fields[7]:
            fix_status = {'fix': True}
            
            # Parse main coordinates
            latitude = float(fields[5]) if fields[5] else None
            if fields[6] == 'S' and latitude is not None:
                latitude = -latitude
                
            longitude = float(fields[7]) if fields[7] else None
            if fields[8] == 'W' and longitude is not None:
                longitude = -longitude
                
            altitude = None
            if len(fields) > 11 and fields[11]:
                try:
                    altitude = float(fields[11])
                except:
                    debug_print(f"Error parsing altitude: {fields[11]}", level=2)
                
            speed = None
            if len(fields) > 12 and fields[12]:
                try:
                    speed = float(fields[12])
                except:
                    debug_print(f"Error parsing speed: {fields[12]}", level=2)
                
            # Satellites info
            satellites = None
            if fields[1]:
                try:
                    satellites = int(fields[1])
                except:
                    debug_print(f"Error parsing satellite count: {fields[1]}", level=2)
                    
            # Format the response
            result = {
                'fix': True,
                'latitude': latitude,
                'longitude': longitude,
                'satellites': satellites,
                'altitude': altitude,
                'speed': speed
            }
            
            # Add date/time if available
            date_str = fields[9] if len(fields) > 9 and fields[9] else None
            time_str = fields[10] if len(fields) > 10 and fields[10] else None
            
            if date_str and time_str:
                result['date'] = date_str
                result['time'] = time_str
                
            return result
        else:
            # We have a response but no coordinates
            satellites = None
            if fields[1]:
                try:
                    satellites = int(fields[1])
                except:
                    debug_print(f"Error parsing satellite count: {fields[1]}", level=2)
            
            return {
                'fix': False,
                'reason': 'no_coordinates',
                'satellites': satellites
            }
            
    except Exception as e:
        debug_print(f"Error parsing GNSS info: {e}", level=2)
        import traceback
        debug_print(traceback.format_exc(), level=2)
        return {'fix': False, 'reason': 'parse_error'}

def reset_gnss(ser):
    """Reset the GNSS module completely"""
    debug_print("\n=== Resetting GNSS Module ===")
    # Power off
    send_at_command(ser, "AT+CGNSSPWR=0", timeout=5, retry=1)
    time.sleep(2)
    
    # Power on
    response, success = send_at_command(ser, "AT+CGNSSPWR=1", timeout=30, retry=1)
    if "+CGNSSPWR: READY!" in response:
        debug_print("GNSS module reset and ready")
    else:
        debug_print("Warning: GNSS reset did not receive READY notification")
    
    time.sleep(POWER_DELAY)

def check_cellular_network(ser):
    """Check cellular network status which can affect A-GPS"""
    debug_print("\n=== Checking Cellular Network Status ===")
    
    # Check network registration
    response, _ = send_at_command(ser, "AT+CREG?", timeout=2)
    if "+CREG: " in response:
        try:
            status = response.split("+CREG: ")[1].split(",")[1].strip().split()[0]
            if status == "1" or status == "5":
                debug_print("Network registration: REGISTERED")
            else:
                debug_print(f"Network registration: NOT REGISTERED (status: {status})")
                debug_print("Note: A-GPS may not work properly without cellular network")
        except:
            debug_print(f"Could not parse network registration status: {response}")
    else:
        debug_print("Failed to get network registration status")
    
    # Check signal quality
    response, _ = send_at_command(ser, "AT+CSQ", timeout=2)
    if "+CSQ: " in response:
        try:
            values = response.split("+CSQ: ")[1].split(",")
            rssi = int(values[0])
            if rssi == 99:
                debug_print("Signal strength: Unknown/Not detectable")
            elif rssi >= 20:
                debug_print(f"Signal strength: Strong ({rssi}/31)")
            elif rssi >= 10:
                debug_print(f"Signal strength: Good ({rssi}/31)")
            elif rssi >= 5:
                debug_print(f"Signal strength: Fair ({rssi}/31)")
            else:
                debug_print(f"Signal strength: Poor ({rssi}/31)")
        except:
            debug_print(f"Could not parse signal strength: {response}")
    else:
        debug_print("Failed to get signal strength")

def check_nmea_output(ser):
    """Check if NMEA sentences are being output"""
    debug_print("\n=== Checking NMEA Output ===")
    
    # Try to get NMEA output status
    response, _ = send_at_command(ser, "AT+CGNSOUT?", timeout=2)
    debug_print(f"NMEA output status: {response}")
    
    # Enable NMEA output to test
    debug_print("Enabling NMEA output temporarily to check GPS data stream...")
    send_at_command(ser, "AT+CGNSOUT=1", timeout=2)
    
    # Read raw data for 5 seconds to see if we get NMEA sentences
    debug_print("Reading NMEA stream for 5 seconds...")
    nmea_data = get_full_response(ser, timeout=5)
    
    # Count NMEA sentences
    nmea_sentences = [line for line in nmea_data.split('\r\n') if line.startswith('$')]
    debug_print(f"Received {len(nmea_sentences)} NMEA sentences")
    
    if len(nmea_sentences) > 0:
        debug_print(f"Sample NMEA sentences:")
        for i, sentence in enumerate(nmea_sentences[:5]):  # Show up to 5 sample sentences
            debug_print(f"  {i+1}. {sentence}")
    else:
        debug_print("No NMEA sentences detected in the data stream!")
    
    # Disable NMEA output
    send_at_command(ser, "AT+CGNSOUT=0", timeout=2)

def log_results(results, filename="gps_log.csv"):
    """Log results to a CSV file for analysis"""
    # Create header if file doesn't exist
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            f.write("timestamp,fix,satellites,latitude,longitude,altitude,speed,raw_response\n")
    
    # Append data
    with open(filename, "a") as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fix = "1" if results.get('fix', False) else "0"
        satellites = str(results.get('satellites', '')) if results.get('satellites') is not None else ''
        lat = str(results.get('latitude', '')) if results.get('latitude') is not None else ''
        lon = str(results.get('longitude', '')) if results.get('longitude') is not None else ''
        alt = str(results.get('altitude', '')) if results.get('altitude') is not None else ''
        speed = str(results.get('speed', '')) if results.get('speed') is not None else ''
        raw = results.get('raw_response', '').replace(',', ';').replace('\n', ' ').replace('\r', '')
        
        f.write(f"{timestamp},{fix},{satellites},{lat},{lon},{alt},{speed},\"{raw}\"\n")

def continuous_monitor(ser, duration=300, interval=5, extended_wait=False, agps_enabled=False):
    """Monitor GPS fix status continuously for a specified duration"""
    debug_print(f"\n=== Starting Continuous GPS Monitoring ({duration}s) ===")
    debug_print(f"Data will be logged to gps_log.csv")
    debug_print(f"Press Ctrl+C to stop monitoring early")
    
    # Give AGPS more time to initialize if enabled
    if agps_enabled and extended_wait:
        extra_wait = 60  # 1 minute extra wait after AGPS
        debug_print(f"Waiting {extra_wait} seconds for AGPS data to be processed...")
        for i in range(extra_wait, 0, -10):
            debug_print(f"AGPS initialization: {i} seconds remaining...")
            time.sleep(10)
    
    start_time = time.time()
    fix_count = 0
    total_checks = 0
    consecutive_no_fix = 0  # Track consecutive failed fixes
    
    try:
        while time.time() - start_time < duration:
            total_checks += 1
            elapsed = int(time.time() - start_time)
            remaining = duration - elapsed
            
            debug_print(f"\n[Time: {elapsed}s / {duration}s remaining: {remaining}s]")
            
            # Check GNSS status
            response, _ = send_at_command(ser, "AT+CGNSSINFO", timeout=3, log_command=False)
            results = parse_gnss_info(response)
            
            # Add raw response for debugging
            if results:
                results['raw_response'] = response
            
            if results:
                if results['fix']:
                    fix_count += 1
                    consecutive_no_fix = 0  # Reset counter
                    debug_print(f"✅ GPS FIX: Lat {results.get('latitude')}, Lon {results.get('longitude')}")
                    debug_print(f"   Satellites: {results.get('satellites')}, Speed: {results.get('speed')}, Altitude: {results.get('altitude')}")
                else:
                    consecutive_no_fix += 1
                    debug_print(f"❌ NO FIX: {results.get('reason')} (Satellites: {results.get('satellites')})")
                    
                    # After several consecutive failures, try to get more diagnostics
                    if consecutive_no_fix % 10 == 0:
                        debug_print("\n=== Performing Additional Diagnostics Due to Continued Fix Failures ===")
                        check_satellites(ser)
                
                # Log results
                log_results(results)
            else:
                consecutive_no_fix += 1
                debug_print("❌ NO FIX: Invalid response format")
                log_results({'fix': False, 'reason': 'invalid_response', 'raw_response': response})
            
            # Sleep for the interval
            time.sleep(interval)
    
    except KeyboardInterrupt:
        debug_print("\nMonitoring stopped by user")
    
    # Print summary
    debug_print("\n=== Monitoring Summary ===")
    debug_print(f"Duration: {int(time.time() - start_time)}s")
    if total_checks > 0:
        debug_print(f"Fix rate: {fix_count}/{total_checks} ({fix_count/total_checks*100:.1f}%)")
    else:
        debug_print("No checks were completed")
    debug_print(f"Results saved to gps_log.csv")

def check_satellites(ser):
    """Check detailed satellite information"""
    debug_print("\n=== Checking Satellite Details ===")
    
    # Some modules support AT+CGNSSINFO=2 for detailed info
    response, success = send_at_command(ser, "AT+CGNSSINFO=2", timeout=5)
    if success:
        debug_print("Detailed satellite info successful")
        debug_print(f"Response: {response}")
    else:
        debug_print("Detailed satellite info not supported or failed")
    
    # Try alternative commands that might be supported
    commands = [
        "AT+CGNSS?",       # Check GNSS status
        "AT+CGNSSFIX?",    # Check fix status
        "AT+CGPSSTATUS?",  # Alternative GPS status
        "AT+CGPS?",        # Another status variant
        "AT+GSV"           # Request satellite details
    ]
    
    for cmd in commands:
        debug_print(f"Trying {cmd}...")
        response, _ = send_at_command(ser, cmd, timeout=3)
        debug_print(f"Response: {response}")

    # Try to read NMEA directly for 2 seconds
    debug_print("Reading raw data for 2 seconds to check for NMEA...")
    raw_data = get_full_response(ser, timeout=2)
    if raw_data:
        debug_print(f"Raw data received: {raw_data[:100]}...")  # Show first 100 chars

def check_gnss_mode(ser):
    """Check and set the GNSS mode for optimal performance"""
    debug_print("\n=== Checking GNSS Mode ===")
    
    # Try different commands - some modules use different variants
    mode_commands = [
        "AT+CGNSMODE?",
        "AT+CGNSSMODE?",
        "AT+CGNSMODECFG?"
    ]
    
    mode_detected = False
    for cmd in mode_commands:
        response, success = send_at_command(ser, cmd, timeout=2)
        if success and not "ERROR" in response:
            debug_print(f"Current GNSS mode detected with {cmd}: {response.strip()}")
            mode_detected = True
            break
    
    if not mode_detected:
        debug_print("Could not detect GNSS mode with standard commands")
    
    # Try to set optimal mode with different commands
    set_commands = [
        "AT+CGNSMODE=1,1,1,1",
        "AT+CGNSSMODE=1,1,1,1",
        "AT+CGNSMODECFG=1,1,1,1"
    ]
    
    mode_set = False
    for cmd in set_commands:
        debug_print(f"Trying to set GNSS mode with: {cmd}")
        response, success = send_at_command(ser, cmd, timeout=2)
        if success and not "ERROR" in response:
            debug_print("Successfully configured GNSS to use all satellite systems")
            mode_set = True
            break
        else:
            debug_print(f"Command {cmd} not supported")
    
    if not mode_set:
        debug_print("Could not set GNSS mode with standard commands")
    
    time.sleep(1)

def cold_start(ser):
    """Perform a cold start (reset almanac/ephemeris data)"""
    debug_print("\n=== Performing Cold Start ===")
    
    # Try different cold start commands
    cold_commands = [
        "AT+CGNSCOLD",
        "AT+CGPSCOLD",
        "AT+CGNSAID=31,1"
    ]
    
    for cmd in cold_commands:
        debug_print(f"Trying cold start with: {cmd}")
        response, success = send_at_command(ser, cmd, timeout=5)
        if success and not "ERROR" in response:
            debug_print(f"Cold start command accepted: {cmd}")
            break
        else:
            debug_print(f"Command {cmd} not supported or failed")
    
    time.sleep(POWER_DELAY)
    debug_print("Waiting for GNSS to initialize after cold start...")
    time.sleep(10)

def enable_agps(ser, delay_factor=2):
    """Enable and verify AGPS status with extended delay"""
    debug_print("\n=== Enabling AGPS ===")
    
    # Send AGPS command directly without checking current status
    debug_print("Sending AT+CAGPS command...")
    response, _ = send_at_command(ser, "AT+CAGPS", timeout=10, retry=2)
    
    # Use extended delay for AGPS
    extended_delay = AGPS_DELAY * delay_factor
    debug_print(f"Waiting {extended_delay} seconds for AGPS to initialize...")
    
    for i in range(0, extended_delay, 5):
        remaining = extended_delay - i
        if remaining > 0:
            debug_print(f"AGPS initialization: {remaining} seconds remaining...")
            time.sleep(min(5, remaining))
    
    # Check for success message in the response
    if "+AGPS: success" in response:
        debug_print("✅ AGPS enabled successfully")
        return True
    else:
        debug_print(f"⚠️ AGPS status unclear: {response}")
        debug_print("Continuing without confirmed AGPS success")
        return False

def main():
    parser = argparse.ArgumentParser(description='GPS Diagnostic Tool')
    parser.add_argument('--time', '-t', type=int, default=300, help='Monitoring time in seconds (default: 300)')
    parser.add_argument('--interval', '-i', type=int, default=5, help='Sampling interval in seconds (default: 5)')
    parser.add_argument('--reset', '-r', action='store_true', help='Reset GNSS module before testing')
    parser.add_argument('--cold', '-c', action='store_true', help='Perform cold start (reset almanac/ephemeris)')
    parser.add_argument('--nmea', '-n', action='store_true', help='Check NMEA output')
    parser.add_argument('--wait', '-w', type=int, default=0, help='Additional wait time in seconds after AGPS init')
    args = parser.parse_args()
    
    # Create log dir if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    # Set up logging to both console and file
    log_file = f"logs/gps_diagnostic_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    debug_print(f"Logging diagnostic output to {log_file}")
    
    # Redirect stdout and stderr to both console and file
    tee = Tee(log_file)
    sys.stdout = tee
    sys.stderr = tee
    
    try:
        debug_print(f"=== GPS Diagnostic Tool ===")
        debug_print(f"Port: {PORT}, Baudrate: {BAUDRATE}")
        debug_print(f"Power delay: {POWER_DELAY}s, AGPS delay: {AGPS_DELAY}s")
        
        if args.wait > 0:
            debug_print(f"Using additional wait time after AGPS: {args.wait}s")
        
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
        debug_print(f"Connected to {PORT} at {BAUDRATE} baud")
        
        # Test basic communication
        debug_print("\n=== Testing Module Responsiveness ===")
        response, success = send_at_command(ser, "AT")
        if success:
            debug_print("✅ Module responded successfully")
        else:
            debug_print(f"❌ Failed to get OK response: {response}")
            return
        
        # Check cellular status (affects A-GPS)
        check_cellular_network(ser)
        
        # Reset if requested
        if args.reset:
            reset_gnss(ser)
        
        # Cold start if requested
        if args.cold:
            cold_start(ser)
        
        # Check GNSS power status
        debug_print("\n=== Checking GNSS Power Status ===")
        response, _ = send_at_command(ser, "AT+CGNSSPWR?")
        if "+CGNSSPWR: 1" in response:
            debug_print("✅ GNSS is powered ON")
        else:
            debug_print("❌ GNSS is powered OFF, turning it ON...")
            response, success = send_at_command(ser, "AT+CGNSSPWR=1", timeout=30, retry=1)
            if "+CGNSSPWR: READY!" in response or "OK" in response:
                debug_print("✅ GNSS powered on successfully")
                time.sleep(POWER_DELAY)
            else:
                debug_print(f"❌ Failed to power on GNSS: {response}")
                return
        
        # Configure GNSS mode
        check_gnss_mode(ser)
        
        # Enable AGPS directly
        agps_enabled = enable_agps(ser, delay_factor=2)
        
        # Check NMEA output if requested
        if args.nmea:
            check_nmea_output(ser)
        
        # Additional satellite check before monitoring
        check_satellites(ser)
        
        # Start monitoring
        continuous_monitor(ser, duration=args.time, interval=args.interval, 
                           extended_wait=(args.wait > 0), agps_enabled=agps_enabled)
        
    except serial.SerialException as e:
        debug_print(f"❌ Serial error: {e}")
        debug_print(f"Check if {PORT} is correct, ModemManager is stopped, and module is powered")
    except Exception as e:
        debug_print(f"❌ Error: {e}")
        import traceback
        debug_print(traceback.format_exc())
    finally:
        try:
            ser.close()
            debug_print("\nSerial port closed")
        except:
            pass
        
        # Restore stdout and stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

class Tee:
    """Class to redirect stdout to both file and console"""
    def __init__(self, filename):
        self.terminal = sys.__stdout__
        self.logfile = open(filename, "w")
        
    def write(self, message):
        self.terminal.write(message)
        self.logfile.write(message)
        self.logfile.flush()
        
    def flush(self):
        self.terminal.flush()
        self.logfile.flush()

if __name__ == "__main__":
    main()
