import serial
import time
import yaml
import argparse
import os
import datetime

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
AGPS_DELAY = gps_config["agps_delay"]

def send_at_command(ser, command, expected_response="OK", timeout=2, log_command=True):
    try:
        if log_command:
            print(f"\n>> Sending: {command}")
        ser.write((command + "\r\n").encode())
        time.sleep(0.1)
        response = ""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            while ser.in_waiting:
                response += ser.read(ser.in_waiting).decode(errors="ignore")
            if expected_response in response:
                if log_command:
                    print(f"<< Response: {response.strip()}")
                return response, True
            time.sleep(0.01)
        
        if log_command:
            print(f"<< Response (timeout): {response.strip()}")
        return response, False
    except Exception as e:
        print(f"Error sending {command}: {e}")
        return "", False

def parse_gnss_info(response):
    """Parse the CGNSSINFO response with better structure"""
    if "+CGNSSINFO: " not in response:
        return None
    
    try:
        # Split by CGNSSINFO and take everything after it
        parts = response.split("+CGNSSINFO: ")[1].split("\r\n")[0].strip()
        fields = parts.split(",")
        
        if len(fields) < 9:
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
                    pass
                
            speed = None
            if len(fields) > 12 and fields[12]:
                try:
                    speed = float(fields[12])
                except:
                    pass
                
            # Satellites info
            satellites = None
            if fields[1]:
                try:
                    satellites = int(fields[1])
                except:
                    pass
                    
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
                    pass
            
            return {
                'fix': False,
                'reason': 'no_coordinates',
                'satellites': satellites
            }
            
    except Exception as e:
        print(f"Error parsing GNSS info: {e}")
        return {'fix': False, 'reason': 'parse_error'}

def reset_gnss(ser):
    """Reset the GNSS module completely"""
    print("\n=== Resetting GNSS Module ===")
    # Power off
    send_at_command(ser, "AT+CGNSSPWR=0", timeout=5)
    time.sleep(2)
    
    # Power on
    response, success = send_at_command(ser, "AT+CGNSSPWR=1", timeout=30)
    if "+CGNSSPWR: READY!" in response:
        print("GNSS module reset and ready")
    else:
        print("Warning: GNSS reset did not receive READY notification")
    
    time.sleep(POWER_DELAY)

def check_cellular_network(ser):
    """Check cellular network status which can affect A-GPS"""
    print("\n=== Checking Cellular Network Status ===")
    
    # Check network registration
    response, _ = send_at_command(ser, "AT+CREG?", timeout=2)
    if "+CREG: " in response:
        status = response.split("+CREG: ")[1].split(",")[1].strip()
        if status == "1" or status == "5":
            print("Network registration: REGISTERED")
        else:
            print(f"Network registration: NOT REGISTERED (status: {status})")
            print("Note: A-GPS may not work properly without cellular network")
    else:
        print("Failed to get network registration status")
    
    # Check signal quality
    response, _ = send_at_command(ser, "AT+CSQ", timeout=2)
    if "+CSQ: " in response:
        values = response.split("+CSQ: ")[1].split(",")
        rssi = int(values[0])
        if rssi == 99:
            print("Signal strength: Unknown/Not detectable")
        elif rssi >= 20:
            print(f"Signal strength: Strong ({rssi}/31)")
        elif rssi >= 10:
            print(f"Signal strength: Good ({rssi}/31)")
        elif rssi >= 5:
            print(f"Signal strength: Fair ({rssi}/31)")
        else:
            print(f"Signal strength: Poor ({rssi}/31)")
    else:
        print("Failed to get signal strength")

def log_results(results, filename="gps_log.csv"):
    """Log results to a CSV file for analysis"""
    # Create header if file doesn't exist
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            f.write("timestamp,fix,satellites,latitude,longitude,altitude,speed\n")
    
    # Append data
    with open(filename, "a") as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fix = "1" if results.get('fix', False) else "0"
        satellites = str(results.get('satellites', '')) if results.get('satellites') is not None else ''
        lat = str(results.get('latitude', '')) if results.get('latitude') is not None else ''
        lon = str(results.get('longitude', '')) if results.get('longitude') is not None else ''
        alt = str(results.get('altitude', '')) if results.get('altitude') is not None else ''
        speed = str(results.get('speed', '')) if results.get('speed') is not None else ''
        
        f.write(f"{timestamp},{fix},{satellites},{lat},{lon},{alt},{speed}\n")

def continuous_monitor(ser, duration=300, interval=5):
    """Monitor GPS fix status continuously for a specified duration"""
    print(f"\n=== Starting Continuous GPS Monitoring ({duration}s) ===")
    print(f"Data will be logged to gps_log.csv")
    print(f"Press Ctrl+C to stop monitoring early")
    
    start_time = time.time()
    fix_count = 0
    total_checks = 0
    
    try:
        while time.time() - start_time < duration:
            total_checks += 1
            elapsed = int(time.time() - start_time)
            remaining = duration - elapsed
            
            print(f"\n[Time: {elapsed}s / {duration}s remaining: {remaining}s]")
            
            # Check GNSS status
            response, _ = send_at_command(ser, "AT+CGNSSINFO", timeout=3, log_command=False)
            results = parse_gnss_info(response)
            
            if results:
                if results['fix']:
                    fix_count += 1
                    print(f"✅ GPS FIX: Lat {results.get('latitude')}, Lon {results.get('longitude')}")
                    print(f"   Satellites: {results.get('satellites')}, Speed: {results.get('speed')}, Altitude: {results.get('altitude')}")
                else:
                    print(f"❌ NO FIX: {results.get('reason')} (Satellites: {results.get('satellites')})")
                
                # Log results
                log_results(results)
            else:
                print("❌ NO FIX: Invalid response format")
                log_results({'fix': False, 'reason': 'invalid_response'})
            
            # Sleep for the interval
            time.sleep(interval)
    
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
    
    # Print summary
    print("\n=== Monitoring Summary ===")
    print(f"Duration: {int(time.time() - start_time)}s")
    print(f"Fix rate: {fix_count}/{total_checks} ({fix_count/total_checks*100:.1f}%)")
    print(f"Results saved to gps_log.csv")

def check_gnss_mode(ser):
    """Check and set the GNSS mode for optimal performance"""
    print("\n=== Checking GNSS Mode ===")
    
    # Check current mode
    response, _ = send_at_command(ser, "AT+CGNSMODE?", timeout=2)
    if "+CGNSMODE: " in response:
        print(f"Current GNSS mode: {response.strip()}")
    
    # Set optimal mode: GPS+GLONASS+GALILEO+BEIDOU
    print("Setting GNSS to use all satellite systems...")
    response, success = send_at_command(ser, "AT+CGNSMODE=1,1,1,1", timeout=2)
    if success:
        print("Successfully configured GNSS to use all satellite systems")
    else:
        print(f"Failed to set GNSS mode: {response}")
    
    time.sleep(1)

def cold_start(ser):
    """Perform a cold start (reset almanac/ephemeris data)"""
    print("\n=== Performing Cold Start ===")
    response, success = send_at_command(ser, "AT+CGNSCOLD", timeout=5)
    if success:
        print("Cold start command accepted")
    else:
        print(f"Failed to perform cold start: {response}")
        # Try alternative command if available
        send_at_command(ser, "AT+CGNSAID=31,1", timeout=5)
    
    time.sleep(POWER_DELAY)
    print("Waiting for GNSS to initialize after cold start...")
    time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description='GPS Diagnostic Tool')
    parser.add_argument('--time', '-t', type=int, default=300, help='Monitoring time in seconds (default: 300)')
    parser.add_argument('--interval', '-i', type=int, default=5, help='Sampling interval in seconds (default: 5)')
    parser.add_argument('--reset', '-r', action='store_true', help='Reset GNSS module before testing')
    parser.add_argument('--cold', '-c', action='store_true', help='Perform cold start (reset almanac/ephemeris)')
    args = parser.parse_args()
    
    try:
        print(f"=== GPS Diagnostic Tool ===")
        print(f"Port: {PORT}, Baudrate: {BAUDRATE}")
        
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
        print(f"Connected to {PORT} at {BAUDRATE} baud")
        
        # Test basic communication
        print("\n=== Testing Module Responsiveness ===")
        response, success = send_at_command(ser, "AT")
        if success:
            print("✅ Module responded successfully")
        else:
            print(f"❌ Failed to get OK response: {response}")
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
        print("\n=== Checking GNSS Power Status ===")
        response, _ = send_at_command(ser, "AT+CGNSSPWR?")
        if "+CGNSSPWR: 1" in response:
            print("✅ GNSS is powered ON")
        else:
            print("❌ GNSS is powered OFF, turning it ON...")
            response, success = send_at_command(ser, "AT+CGNSSPWR=1", timeout=30)
            if "+CGNSSPWR: READY!" in response or "OK" in response:
                print("✅ GNSS powered on successfully")
                time.sleep(POWER_DELAY)
            else:
                print(f"❌ Failed to power on GNSS: {response}")
                return
        
        # Configure GNSS mode
        check_gnss_mode(ser)
        
        # Enable AGPS
        print("\n=== Checking AGPS Status ===")
        response, _ = send_at_command(ser, "AT+CAGPS?")
        if "+CAGPS: 1" in response:
            print("✅ AGPS is already enabled")
        else:
            print("Enabling AGPS...")
            response, _ = send_at_command(ser, "AT+CAGPS", timeout=10)
            time.sleep(AGPS_DELAY)
            
            if "+AGPS: success" in response:
                print("✅ AGPS enabled successfully")
            else:
                print(f"⚠️ AGPS status unclear: {response}")
                print("Continuing without confirmed AGPS")
        
        # Start monitoring
        continuous_monitor(ser, duration=args.time, interval=args.interval)
        
    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        print(f"Check if {PORT} is correct, ModemManager is stopped, and module is powered")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        try:
            ser.close()
            print("\nSerial port closed")
        except:
            pass

if __name__ == "__main__":
    main()
