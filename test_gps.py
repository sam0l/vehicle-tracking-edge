import serial
import time

# GPS module settings
PORT = "/dev/ttyUSB1"
BAUDRATE = 115200
TIMEOUT = 2

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
            time.sleep(2)  # Wait for module to stabilize
        else:
            print(f"Failed to power on GNSS: {response}")
            return
        
        # Enable AGPS
        print("Enabling AGPS...")
        response, success = send_at_command(ser, "AT+CAGPS")
        if success:
            print("AGPS enabled successfully")
            time.sleep(2)  # Wait for AGPS to initialize
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
        print("Check if /dev/ttyUSB1 is correct, ModemManager is stopped, and module is powered")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    main()
