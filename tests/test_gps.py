import serial
import time
import yaml

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

def send_at_command(ser, command, expected_response="OK", timeout=2):
    try:
        ser.write((command + "\r\n").encode())
        time.sleep(0.1)
        response = ""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            while ser.in_waiting:
                response += ser.read(ser.in_waiting).decode(errors="ignore")
            if expected_response in response:
                return response, True
            time.sleep(0.01)
        
        return response, False
    except Exception as e:
        print(f"Error sending {command}: {e}")
        return "", False

def main():
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
        print(f"Connected to {PORT} at {BAUDRATE} baud")
        
        # Test basic communication
        print("Testing module responsiveness...")
        response, success = send_at_command(ser, "AT")
        if success:
            print("Module responded: OK")
        else:
            print(f"Failed to get OK response: {response}")
            return
        
        # Power on GNSS
        print("Powering on GNSS...")
        response, success = send_at_command(ser, "AT+CGNSSPWR=1")
        if success:
            print("GNSS powered on successfully")
            time.sleep(POWER_DELAY)  # Wait for module to stabilize
        else:
            print(f"Failed to power on GNSS: {response}")
            return
        
        # Enable AGPS
        print("Enabling AGPS...")
        response, success = send_at_command(ser, "AT+CAGPS")
        if success:
            print("AGPS enabled successfully")
            time.sleep(AGPS_DELAY)  # Wait for AGPS to initialize
        else:
            print(f"Failed to enable AGPS: {response}")
            return
        
        # Test CGNSSINFO
        print("Sending AT+CGNSSINFO...")
        response, success = send_at_command(ser, "AT+CGNSSINFO", "+CGNSSINFO:", timeout=3)
        if success:
            print(f"Response: {response.strip()}")
            if ",,,,,,,," in response or ",,,,,,,,,," in response:
                print("Success: AT+CGNSSINFO returned expected no-fix response indoors")
            else:
                print("Warning: AT+CGNSSINFO did not return expected no-fix response")
        else:
            print(f"Failed to get CGNSSINFO response: {response}")
        
    except serial.SerialException as e:
        print(f"Serial error: {e}")
        print(f"Check if {PORT} is correct, ModemManager is stopped, and module is powered")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    main()
