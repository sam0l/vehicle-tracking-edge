import serial
import time
import logging

class GPS:
    def __init__(self, port, baudrate, timeout, power_delay, agps_delay):
        self.logger = logging.getLogger(__name__)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.power_delay = power_delay
        self.agps_delay = agps_delay
        self.serial = None
        self.has_fix = False
        self.last_fix_check = 0
        self.fix_check_interval = 5  # Check for fix every 5 seconds
        self.satellites = 0

    def read_response(self, timeout=5):
        start_time = time.time()
        response = ""
        while time.time() - start_time < timeout:
            if self.serial.in_waiting:
                response += self.serial.read(self.serial.in_waiting).decode('utf-8', errors='ignore')
                if '\n' in response:
                    lines = response.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and line != 'OK' and not line.startswith('AT+'):
                            return line
            time.sleep(0.01)
        self.logger.debug(f"Raw response after {timeout}s: {response}")
        return response.strip()

    def wait_for_response(self, expected_response, timeout):
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self.read_response(timeout=1)
            if expected_response in response:
                self.logger.debug(f"Received expected response: {response}")
                return True
            self.logger.debug(f"Waiting for '{expected_response}', got: {response}")
        self.logger.warning(f"Timeout waiting for '{expected_response}' after {timeout}s")
        return False

    def send_command(self, command, expected_response=None, timeout=5, retry=0):
        """Send AT command with optional retry"""
        full_response = ""
        success = False
        
        for attempt in range(retry + 1):
            try:
                self.logger.debug(f"Sending: {command}{' (retry ' + str(attempt) + ')' if attempt > 0 else ''}")
                self.serial.write((command + '\r\n').encode('utf-8'))
                
                if not expected_response:
                    time.sleep(0.1)  # Brief delay for commands without expected response
                    return True
                    
                # Wait for expected response
                start_time = time.time()
                response = ""
                
                while time.time() - start_time < timeout:
                    if self.serial.in_waiting:
                        chunk = self.serial.read(self.serial.in_waiting).decode('utf-8', errors='ignore')
                        response += chunk
                        full_response += chunk
                        
                        if expected_response in response:
                            self.logger.debug(f"Received: {response.strip()}")
                            return True
                    time.sleep(0.01)
                
                self.logger.debug(f"Timeout waiting for '{expected_response}', got: {response.strip()}")
                
                # If this is not the last attempt, wait before retrying
                if attempt < retry:
                    time.sleep(1)
            except Exception as e:
                self.logger.error(f"Command: {command}, Error: {e}")
                time.sleep(1)
                
        return False

    def initialize(self):
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.logger.info("GPS serial port opened")
        except Exception as e:
            self.logger.error(f"Failed to open GPS serial port: {e}")
            return False

        # Check if GNSS is powered on
        self.serial.write(b'AT+CGNSSPWR?\r\n')
        response = self.read_response(timeout=2)
        self.logger.debug(f"GNSS power check response: {response}")
        if "+CGNSSPWR: 1" not in response:
            # Power on GNSS
            if not self.send_command("AT+CGNSSPWR=1", "+CGNSSPWR: READY!", timeout=30, retry=2):
                self.logger.error("Failed to power on GNSS")
                return False
            self.logger.info("GNSS powered on successfully")
            
            # Wait after powering on
            time.sleep(self.power_delay)
        else:
            self.logger.info("GNSS already powered on")

        # Configure GNSS Mode to enable all satellite systems
        # From test results, we found CGNSSMODE is the correct command for this module
        self.logger.info("Configuring GNSS to use all satellite systems")
        try:
            self.serial.write(b'AT+CGNSSMODE?\r\n')
            response = self.read_response(timeout=2)
            self.logger.debug(f"GNSS mode check response: {response}")
            
            # Mode 3 typically means GPS+GLONASS+BEIDOU, which is good
            if "+CGNSSMODE: 3" in response:
                self.logger.info("GNSS already configured to use multiple satellite systems (mode 3)")
            else:
                self.logger.info("Setting GNSS mode to 3 (GPS+GLONASS+BEIDOU)")
                self.send_command("AT+CGNSSMODE=3", "OK", timeout=2)
        except Exception as e:
            self.logger.warning(f"Failed to configure GNSS mode: {e}, continuing with default mode")
        
        # Enable AGPS directly without checking status first
        self.logger.info("Enabling AGPS...")
        self.serial.write(b'AT+CAGPS\r\n')
        
        # Wait for the specified AGPS delay before continuing
        self.logger.info(f"Waiting {self.agps_delay} seconds for AGPS to initialize...")
        time.sleep(self.agps_delay)
        
        # Read any response but don't require success message
        response = self.read_response(timeout=2)
        if "+AGPS: success" in response:
            self.logger.info("AGPS enabled successfully")
        else:
            self.logger.info("Continuing after AGPS command (success status unknown)")

        # Initial check for GPS fix - may not have fix yet
        self.check_gps_fix()
        
        self.logger.info("GPS initialized successfully")
        return True

    def check_gps_fix(self):
        """Check if GPS has a fix by querying CGNSSINFO"""
        current_time = time.time()
        
        # Skip if we checked recently
        if current_time - self.last_fix_check < self.fix_check_interval:
            return self.has_fix
            
        self.last_fix_check = current_time
        
        try:
            self.logger.debug("Checking for GPS fix...")
            self.serial.write(b'AT+CGNSSINFO\r\n')
            response = self.read_response()
            self.logger.debug(f"CGNSSINFO response: {response}")
            
            # Look for CGNSSINFO response with non-empty lat/lon fields
            if "+CGNSSINFO: " in response:
                fields = response.split(': ')[1].split(',')
                
                # Update satellites count if available
                if len(fields) > 1 and fields[1]:
                    try:
                        self.satellites = int(fields[1])
                    except ValueError:
                        pass
                
                # For this device, latitude is at index 5, longitude at index 7
                if len(fields) >= 9 and fields[5] and fields[7]:
                    self.has_fix = True
                    self.logger.info(f"GPS has acquired a fix (satellites: {self.satellites})")
                else:
                    self.has_fix = False
                    self.logger.debug(f"GPS has not yet acquired a fix (satellites: {self.satellites}, missing lat/lon)")
            else:
                self.has_fix = False
                self.logger.debug("GPS has not yet acquired a fix (invalid response)")
        except Exception as e:
            self.logger.error(f"Error checking GPS fix: {e}")
            self.has_fix = False
            
        return self.has_fix

    def get_data(self):
        try:
            # First check if we have a fix
            if not self.check_gps_fix():
                self.logger.warning(f"No GPS fix yet, waiting for satellite acquisition (visible satellites: {self.satellites})")
                return None
                
            self.serial.write(b'AT+CGNSSINFO\r\n')
            response = self.read_response()
            self.logger.debug(f"CGNSSINFO response: {response}")

            # Format observed in working diagnostic:
            # +CGNSSINFO: 3,17,,09,10,14.6198673,N,121.1038513,E,120525,112149.00,78.0,0.000,15.78,1.91,0.95,1.6
            # Position in array:           0  1  2  3  4  5          6  7          8  9      10        11   12    13+
            # Lat is field 5, lat dir is field 6, lon is field 7, lon dir is field 8, alt is field 11, speed is field 12

            if "+CGNSSINFO: " not in response:
                self.logger.warning(f"Invalid CGNSSINFO response: {response}")
                self.has_fix = False
                return None

            # Extract all fields from the response
            fields = response.split(': ')[1].split(',')
            self.logger.debug(f"Parsed CGNSSINFO fields: {fields}")
            
            # Based on successful diagnostic, we need at least 9 fields for lat/lon
            if len(fields) < 9:
                self.logger.warning(f"Incomplete CGNSSINFO response: {response}")
                self.has_fix = False
                return None

            try:
                # Check if latitude and longitude fields exist and are non-empty
                # Latitude is at index 5, longitude at index 7
                if not fields[5] or not fields[7]:
                    self.logger.warning("Empty latitude or longitude fields")
                    self.has_fix = False
                    return None
                
                # Update satellites count
                if fields[1]:
                    try:
                        self.satellites = int(fields[1])
                    except ValueError:
                        pass
                
                # Parse latitude (index 5) and direction (index 6)
                latitude = float(fields[5]) if fields[5] else None
                if fields[6] == 'S' and latitude is not None:
                    latitude = -latitude
                
                # Parse longitude (index 7) and direction (index 8)
                longitude = float(fields[7]) if fields[7] else None
                if fields[8] == 'W' and longitude is not None:
                    longitude = -longitude
                
                # Parse altitude (index 11)
                altitude = None
                if len(fields) > 11 and fields[11]:
                    try:
                        altitude = float(fields[11])
                    except ValueError:
                        pass
                
                # Parse speed (index 12)
                speed = None
                if len(fields) > 12 and fields[12]:
                    try:
                        speed = float(fields[12])
                    except ValueError:
                        speed = 0.0
                
                if speed is None:
                    speed = 0.0

                # Log successful GPS data retrieval
                self.logger.info(f"GPS data: lat={latitude}, lon={longitude}, alt={altitude}, speed={speed}, satellites={self.satellites}")
                
                result = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "speed": speed,
                    "satellites": self.satellites
                }
                
                if altitude is not None:
                    result["altitude"] = altitude
                    
                return result
                
            except ValueError as e:
                self.logger.error(f"Error parsing CGNSSINFO: {e}")
                return None
            except IndexError as e:
                self.logger.error(f"Index error parsing CGNSSINFO (fields: {len(fields)}): {e}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting GPS data: {e}")
            return None

    def close(self):
        if self.serial:
            self.serial.close()
            self.logger.info("GPS serial port closed")
