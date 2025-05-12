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
        self.fix_check_interval = 10  # Check for fix every 10 seconds

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

    def send_command(self, command, expected_response=None, timeout=5):
        try:
            self.serial.write((command + '\r\n').encode('utf-8'))
            if expected_response:
                return self.wait_for_response(expected_response, timeout)
            return True
        except Exception as e:
            self.logger.error(f"Command: {command}, Error: {e}")
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
            if not self.send_command("AT+CGNSSPWR=1", "+CGNSSPWR: READY!", timeout=30):
                self.logger.error("Failed to power on GNSS")
                return False
            self.logger.info("GNSS powered on successfully")
            
            # Wait after powering on
            time.sleep(self.power_delay)
        else:
            self.logger.info("GNSS already powered on")

        # Configure GNSS Mode to enable all satellite systems
        self.logger.info("Configuring GNSS to use all satellite systems")
        if not self.send_command("AT+CGNSMODE=1,1,1,1", "OK", timeout=5):
            self.logger.warning("Failed to configure GNSS mode, continuing with default mode")
        
        # Check if AGPS is enabled
        self.serial.write(b'AT+CAGPS?\r\n')
        response = self.read_response(timeout=2)
        self.logger.debug(f"AGPS check response: {response}")
        if "+CAGPS: 1" not in response:
            # Attempt to enable AGPS with exactly 'AT+CAGPS' command
            self.logger.info("Enabling AGPS...")
            self.serial.write(b'AT+CAGPS\r\n')
            
            # Wait for the specified AGPS delay before checking for success
            self.logger.debug(f"Waiting for {self.agps_delay} seconds before checking for AGPS success...")
            time.sleep(self.agps_delay)
            
            # Now check for success response
            response = self.read_response(timeout=10)
            if "+AGPS: success" in response:
                self.logger.info("AGPS enabled successfully")
            else:
                self.logger.warning(f"Failed to enable AGPS, continuing without AGPS. Response: {response}")
        else:
            self.logger.info("AGPS already enabled")

        # Check if we have a GPS fix
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
            
            # Look for CGNSSINFO response with non-empty lat/lon fields
            if "+CGNSSINFO: " in response:
                fields = response.split(': ')[1].split(',')
                # For this device, latitude is at index 5, longitude at index 7
                if len(fields) >= 9 and fields[5] and fields[7]:
                    self.has_fix = True
                    self.logger.info("GPS has acquired a fix")
                else:
                    self.has_fix = False
                    self.logger.debug("GPS has not yet acquired a fix (missing lat/lon)")
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
                self.logger.warning("No GPS fix yet, still waiting for satellite acquisition")
                return None
                
            self.serial.write(b'AT+CGNSSINFO\r\n')
            response = self.read_response()
            self.logger.debug(f"CGNSSINFO response: {response}")

            # Example from minicom: +CGNSSINFO: 3,17,,12,09,14.6192493,N,121.1041031,E,120525,101533.00,77.1,0.000,6
            # Position in response array:           0  1  2  3  4  5          6  7          8  9      10        11   12    13
            # Lat is field 5, lat dir is field 6, lon is field 7, lon dir is field 8, speed is field 12

            if "+CGNSSINFO: " not in response:
                self.logger.warning(f"Invalid CGNSSINFO response: {response}")
                self.has_fix = False
                return None

            # Extract all fields from the response
            fields = response.split(': ')[1].split(',')
            self.logger.debug(f"Parsed CGNSSINFO fields: {fields}")
            
            # For this specific device, we're expecting a format with at least 13 fields
            # for a valid reading (lat, lat_dir, lon, lon_dir, etc.)
            if len(fields) < 13:
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
                
                # Parse latitude (index 5) and direction (index 6)
                latitude = float(fields[5]) if fields[5] else None
                if fields[6] == 'S' and latitude is not None:
                    latitude = -latitude
                
                # Parse longitude (index 7) and direction (index 8)
                longitude = float(fields[7]) if fields[7] else None
                if fields[8] == 'W' and longitude is not None:
                    longitude = -longitude
                
                # Parse speed (index 12)
                speed = float(fields[12]) if len(fields) > 12 and fields[12] else 0.0

                # Log successful GPS data retrieval
                self.logger.info(f"GPS data: lat={latitude}, lon={longitude}, speed={speed}")
                
                return {
                    "latitude": latitude,
                    "longitude": longitude,
                    "speed": speed
                }
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
