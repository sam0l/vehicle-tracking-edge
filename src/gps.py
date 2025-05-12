import serial
import time
import logging
import random

class GPS:
    def __init__(self, port, baudrate, timeout, power_delay, agps_delay, fix_check_interval=5, max_buffer_size=8192):
        """
        Initialize the GPS module with improved parameters.
        
        Args:
            port: Serial port to use
            baudrate: Baud rate for serial communication
            timeout: Serial timeout in seconds
            power_delay: Delay after powering on GPS in seconds
            agps_delay: Delay after enabling AGPS in seconds
            fix_check_interval: How often to check for a GPS fix in seconds
            max_buffer_size: Maximum buffer size for serial reads
        """
        self.logger = logging.getLogger(__name__)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.power_delay = power_delay
        self.agps_delay = agps_delay
        # Explicitly initialize serial to None
        self.serial = None
        self.has_fix = False
        self.last_fix_check = 0
        # Make fix check interval configurable
        self.fix_check_interval = fix_check_interval
        self.satellites = 0
        # Add maximum buffer size to prevent memory issues
        self.max_buffer_size = max_buffer_size
        # Track connection attempts
        self.connection_attempts = 0

    def read_response(self, timeout=5, return_all_lines=False):
        """
        Read response from the serial port with improved buffer management.
        
        Args:
            timeout: Maximum time to wait for response in seconds
            return_all_lines: Whether to return all lines or just the first meaningful line
            
        Returns:
            String response or list of response lines when return_all_lines=True
        """
        start_time = time.time()
        response = ""
        all_lines = []
        
        while time.time() - start_time < timeout:
            if self.serial and self.serial.in_waiting:
                # Limit read size for better memory management
                bytes_to_read = min(self.serial.in_waiting, self.max_buffer_size)
                chunk = self.serial.read(bytes_to_read).decode('utf-8', errors='ignore')
                response += chunk
                
                # Process complete lines
                if '\n' in response:
                    lines = response.split('\n')
                    # Keep the last incomplete line in the buffer
                    response = lines.pop()
                    
                    for line in lines:
                        line = line.strip()
                        if line:
                            all_lines.append(line)
                            if not return_all_lines and line != 'OK' and not line.startswith('AT+'):
                                self.logger.debug(f"Read response: {line}")
                                return line
            
            # Non-blocking read with small delay
            time.sleep(0.01)
        
        # Add any remaining content to all_lines
        if response.strip():
            all_lines.append(response.strip())
            
        if return_all_lines:
            self.logger.debug(f"Read all lines: {all_lines}")
            return all_lines
        
        response_text = response.strip() if not all_lines else all_lines[0] 
        self.logger.debug(f"Raw response after {timeout}s: {response_text}")
        return response_text

    def wait_for_response(self, expected_response, timeout):
        """
        Wait for an expected response with improved handling.
        
        Args:
            expected_response: The response string to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            Boolean indicating whether the expected response was received
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Get all response lines
            response_lines = self.read_response(timeout=1, return_all_lines=True)
            
            if isinstance(response_lines, list):
                for line in response_lines:
                    if expected_response in line:
                        self.logger.debug(f"Received expected response: {line}")
                        return True
                    self.logger.debug(f"Waiting for '{expected_response}', got: {line}")
            else:
                # Handle case where response_lines is a string
                if expected_response in response_lines:
                    self.logger.debug(f"Received expected response: {response_lines}")
                    return True
                self.logger.debug(f"Waiting for '{expected_response}', got: {response_lines}")
                
        self.logger.warning(f"Timeout waiting for '{expected_response}' after {timeout}s")
        return False

    def send_command(self, command, expected_response=None, timeout=5, retry=0):
        """
        Send AT command with exponential backoff for retries.
        
        Args:
            command: AT command to send
            expected_response: Expected response string
            timeout: Maximum time to wait for response
            retry: Number of retries if command fails
            
        Returns:
            Tuple of (success, response) where success is a boolean and response is the received text
        """
        full_response = []
        success = False
        
        for attempt in range(retry + 1):
            try:
                self.logger.debug(f"Sending: {command}{' (retry ' + str(attempt) + ')' if attempt > 0 else ''}")
                if self.serial:
                    self.serial.write((command + '\r\n').encode('utf-8'))
                else:
                    self.logger.error("Serial connection not established")
                    return False, []
                
                if not expected_response:
                    time.sleep(0.1)  # Brief delay for commands without expected response
                    return True, []
                    
                # Wait for expected response
                start_time = time.time()
                response_lines = []
                
                while time.time() - start_time < timeout:
                    if self.serial and self.serial.in_waiting:
                        chunk = self.serial.read(self.serial.in_waiting).decode('utf-8', errors='ignore')
                        
                        # Process lines
                        lines = chunk.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line:
                                response_lines.append(line)
                                full_response.append(line)
                                
                        # Check if any line contains the expected response
                        if any(expected_response in line for line in response_lines):
                            self.logger.debug(f"Received expected response in: {response_lines}")
                            return True, response_lines
                    time.sleep(0.01)
                
                self.logger.debug(f"Timeout waiting for '{expected_response}', got: {response_lines}")
                
                # Exponential backoff for retries
                if attempt < retry:
                    backoff_time = min(2 ** attempt + random.random(), 10)
                    self.logger.debug(f"Retrying after {backoff_time:.2f}s")
                    time.sleep(backoff_time)
            except Exception as e:
                self.logger.error(f"Command: {command}, Error: {e}")
                # Exponential backoff for retries after errors
                if attempt < retry:
                    backoff_time = min(2 ** attempt + random.random(), 10)
                    self.logger.debug(f"Retrying after error in {backoff_time:.2f}s")
                    time.sleep(backoff_time)
                
        return False, full_response

    def initialize(self):
        """
        Initialize the GPS module with improved reliability.
        
        Returns:
            Boolean indicating initialization success
        """
        # Track connection attempts for exponential backoff
        self.connection_attempts += 1
        
        try:
            # Close any existing connection first
            if self.serial:
                try:
                    self.serial.close()
                    self.logger.info("Closed existing GPS serial connection")
                except:
                    pass
                self.serial = None
            
            # Exponential backoff if this is a retry
            if self.connection_attempts > 1:
                backoff_time = min(2 ** (self.connection_attempts - 1) + random.random(), 30)
                self.logger.info(f"Retry attempt {self.connection_attempts}, waiting {backoff_time:.2f}s before reconnecting")
                time.sleep(backoff_time)
            
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
            success, power_response = self.send_command("AT+CGNSSPWR=1", "+CGNSSPWR: READY!", timeout=30, retry=2)
            if not success:
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
            success, mode_check_response = self.send_command("AT+CGNSSMODE?", timeout=2) 
            self.logger.debug(f"GNSS mode check response: {mode_check_response}")
            
            # Mode 3 typically means GPS+GLONASS+BEIDOU, which is good
            response_text = '\n'.join(mode_check_response) if isinstance(mode_check_response, list) else str(mode_check_response)
            if "+CGNSSMODE: 3" in response_text:
                self.logger.info("GNSS already configured to use multiple satellite systems (mode 3)")
            else:
                self.logger.info("Setting GNSS mode to 3 (GPS+GLONASS+BEIDOU)")
                self.send_command("AT+CGNSSMODE=3", "OK", timeout=2)
        except Exception as e:
            self.logger.warning(f"Failed to configure GNSS mode: {e}, continuing with default mode")
        
        # Enable AGPS with proper response handling
        self.logger.info("Enabling AGPS...")
        success, agps_response = self.send_command("AT+CAGPS", timeout=2, retry=1)
        
        # Wait for the specified AGPS delay before continuing
        self.logger.info(f"Waiting {self.agps_delay} seconds for AGPS to initialize...")
        time.sleep(self.agps_delay)
        
        # Check AGPS response
        response_text = '\n'.join(agps_response) if isinstance(agps_response, list) else str(agps_response)
        if "+AGPS: success" in response_text:
            self.logger.info("AGPS enabled successfully")
        else:
            self.logger.info("Continuing after AGPS command (success status unknown)")

        # Initial check for GPS fix - may not have fix yet
        self.check_gps_fix()
        
        # Reset connection attempts counter on successful connection
        self.connection_attempts = 0
        
        self.logger.info("GPS initialized successfully")
        return True

    def check_gps_fix(self):
        """
        Check if GPS has a fix by querying CGNSSINFO with improved handling.
        
        Returns:
            Boolean indicating whether GPS has a fix
        """
        current_time = time.time()
        
        # Skip if we checked recently
        if current_time - self.last_fix_check < self.fix_check_interval:
            return self.has_fix
            
        self.last_fix_check = current_time
        
        try:
            self.logger.debug("Checking for GPS fix...")
            success, response_lines = self.send_command("AT+CGNSSINFO", timeout=2)
            
            if not success or not response_lines:
                self.logger.debug("No response when checking for GPS fix")
                self.has_fix = False
                return False
                
            # Convert list to string for logging/processing
            response_text = '\n'.join(response_lines) if isinstance(response_lines, list) else str(response_lines)
            self.logger.debug(f"CGNSSINFO response: {response_text}")
            
            # Look for CGNSSINFO response with non-empty lat/lon fields
            cgnssinfo_line = None
            for line in response_lines if isinstance(response_lines, list) else [response_text]:
                if "+CGNSSINFO: " in line:
                    cgnssinfo_line = line
                    break
                    
            if cgnssinfo_line:
                fields = cgnssinfo_line.split(': ')[1].split(',')
                
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
        """
        Get GPS data with improved reliability and raw response return.
        
        Returns:
            Dictionary containing parsed GPS data and raw response
        """
        try:
            # First check if we have a fix
            if not self.check_gps_fix():
                self.logger.warning(f"No GPS fix yet, waiting for satellite acquisition (visible satellites: {self.satellites})")
                return None
                
            success, response_lines = self.send_command("AT+CGNSSINFO", timeout=2)
            
            if not success or not response_lines:
                self.logger.warning("Failed to get CGNSSINFO response")
                self.has_fix = False
                return None
                
            # Convert list to string for logging
            response_text = '\n'.join(response_lines) if isinstance(response_lines, list) else str(response_lines)
            self.logger.debug(f"CGNSSINFO response: {response_text}")
            
            # Find the CGNSSINFO line in the response
            cgnssinfo_line = None
            for line in response_lines if isinstance(response_lines, list) else [response_text]:
                if "+CGNSSINFO: " in line:
                    cgnssinfo_line = line
                    break

            if not cgnssinfo_line:
                self.logger.warning(f"Invalid CGNSSINFO response: {response_text}")
                self.has_fix = False
                return None

            # Format observed in working diagnostic:
            # +CGNSSINFO: 3,17,,09,10,14.6198673,N,121.1038513,E,120525,112149.00,78.0,0.000,15.78,1.91,0.95,1.6
            # Position in array:           0  1  2  3  4  5          6  7          8  9      10        11   12    13+
            # Lat is field 5, lat dir is field 6, lon is field 7, lon dir is field 8, alt is field 11, speed is field 12

            # Extract all fields from the response
            fields = cgnssinfo_line.split(': ')[1].split(',')
            self.logger.debug(f"Parsed CGNSSINFO fields: {fields}")
            
            # Based on successful diagnostic, we need at least 9 fields for lat/lon
            if len(fields) < 9:
                self.logger.warning(f"Incomplete CGNSSINFO response: {cgnssinfo_line}")
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
                
                # Return both parsed data and raw response
                result = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "speed": speed,
                    "satellites": self.satellites,
                    "raw_response": response_text
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
        """Safely close the serial connection"""
        if self.serial:
            try:
                self.serial.close()
                self.logger.info("GPS serial port closed")
            except Exception as e:
                self.logger.error(f"Error closing GPS serial port: {e}")
            finally:
                self.serial = None
