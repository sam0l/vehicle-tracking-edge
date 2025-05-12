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
        else:
            self.logger.info("GNSS already powered on")

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

        self.logger.info("GPS initialized successfully")
        return True

    def get_data(self):
        try:
            self.serial.write(b'AT+CGNSSINFO\r\n')
            response = self.read_response()
            self.logger.debug(f"CGNSSINFO response: {response}")

            if "+CGNSSINFO: " not in response or ",,,,,,,," in response:
                self.logger.warning(f"Invalid CGNSSINFO response: {response}")
                return None

            # Parse response (example: +CGNSSINFO: 2,06,48.123456,N,123.123456,E,...)
            fields = response.split(': ')[1].split(',')
            if len(fields) < 8:
                self.logger.warning(f"Incomplete CGNSSINFO response: {response}")
                return None

            try:
                latitude = float(fields[2]) if fields[2] else None
                if fields[3] == 'S' and latitude is not None:
                    latitude = -latitude
                longitude = float(fields[4]) if fields[4] else None
                if fields[5] == 'W' and longitude is not None:
                    longitude = -longitude
                speed = float(fields[7]) if fields[7] else None

                return {
                    "latitude": latitude,
                    "longitude": longitude,
                    "speed": speed
                }
            except ValueError as e:
                self.logger.error(f"Error parsing CGNSSINFO: {e}")
                return None
        except Exception as e:
            self.logger.error(f"Error getting GPS data: {e}")
            return None

    def close(self):
        if self.serial:
            self.serial.close()
            self.logger.info("GPS serial port closed")
