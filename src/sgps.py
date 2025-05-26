import serial
import time
import logging
import pynmea2

class SGPS:
    def __init__(self, port, baudrate, timeout=1, fix_check_interval=5):
        """
        Initialize the NEO-6M GPS module.
        
        Args:
            port: Serial port (e.g., '/dev/ttyS4')
            baudrate: Baud rate for serial communication (e.g., 9600)
            timeout: Serial read timeout in seconds
            fix_check_interval: How often to update fix status (simulated, as NMEA provides it directly)
        """
        self.logger = logging.getLogger(__name__)
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None
        self.last_data_time = 0

        # GPS data attributes
        self.latitude = 0.0
        self.longitude = 0.0
        self.altitude = 0.0
        self.speed_knots = 0.0
        self.speed_kmh = 0.0
        self.course = 0.0
        self.satellites = 0
        self.hdop = 0.0
        self.timestamp = None # UTC time from GPS
        self.datestamp = None # UTC date from GPS
        self.has_fix = False

        # For simulating fix_check_interval if needed, though NMEA provides fix status directly
        self.fix_check_interval = fix_check_interval 
        self.last_fix_check = 0

    def initialize(self):
        """
        Initialize the serial connection to the GPS module.
        
        Returns:
            Boolean indicating initialization success
        """
        try:
            if self.serial and self.serial.is_open:
                self.serial.close()
            self.serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            self.logger.info(f"Successfully connected to GPS module on {self.port} at {self.baudrate} baud.")
            # NEO-6M usually starts sending NMEA data automatically, no specific init commands needed.
            # We can try to read a line to confirm it's working.
            if self.serial.in_waiting > 0:
                self.serial.readline()
            return True
        except serial.SerialException as e:
            self.logger.error(f"Error initializing GPS on {self.port}: {e}")
            self.serial = None
            return False
        except Exception as e:
            self.logger.error(f"An unexpected error occurred during GPS initialization: {e}")
            self.serial = None
            return False

    def _parse_nmea_sentence(self, sentence_str):
        """
        Parse a single NMEA sentence string.
        """
        try:
            msg = pynmea2.parse(sentence_str)
            self.last_data_time = time.time()

            if isinstance(msg, pynmea2.types.talker.GGA):
                self.timestamp = msg.timestamp
                if msg.latitude:
                    self.latitude = msg.latitude
                if msg.longitude:
                    self.longitude = msg.longitude
                if msg.altitude:
                    self.altitude = msg.altitude
                self.satellites = msg.num_sats
                if msg.horizontal_dilution:
                    self.hdop = msg.horizontal_dilution
                self.has_fix = msg.gps_qual > 0
                self.logger.debug(f"Parsed GGA: Lat={self.latitude}, Lon={self.longitude}, Alt={self.altitude}, Sats={self.satellites}, Fix={self.has_fix}")

            elif isinstance(msg, pynmea2.types.talker.RMC):
                self.timestamp = msg.timestamp
                self.datestamp = msg.datestamp # RMC has date
                if msg.latitude:
                    self.latitude = msg.latitude
                if msg.longitude:
                    self.longitude = msg.longitude
                if msg.spd_over_grnd_kts:
                    self.speed_knots = msg.spd_over_grnd_kts
                    self.speed_kmh = self.speed_knots * 1.852 # Convert knots to km/h
                if msg.true_course:
                    self.course = msg.true_course
                self.has_fix = msg.status == 'A' # 'A' for Active/OK, 'V' for Void/Warning
                self.logger.debug(f"Parsed RMC: Lat={self.latitude}, Lon={self.longitude}, Speed={self.speed_kmh} km/h, Course={self.course}, Fix={self.has_fix}")
            
            elif isinstance(msg, pynmea2.types.talker.GSA):
                # GSA can also provide fix status and HDOP
                if msg.mode_fix_type:
                     self.has_fix = msg.mode_fix_type in [2,3] # 2D or 3D fix
                if msg.hdop:
                    self.hdop = float(msg.hdop)
                self.logger.debug(f"Parsed GSA: Fix mode={msg.mode_fix_type}, HDOP={self.hdop}")

            elif isinstance(msg, pynmea2.types.talker.GSV):
                # GSV provides detailed satellite information, we can count total visible satellites
                # msg.num_messages, msg.msg_num, msg.num_sv_in_view
                # For simplicity, we rely on GGA's num_sats for satellites in use.
                pass

        except pynmea2.ParseError as e:
            self.logger.debug(f"Could not parse NMEA sentence: {sentence_str} - Error: {e}")
        except AttributeError as e:
            self.logger.debug(f"Attribute error parsing NMEA sentence ({type(msg).__name__ if 'msg' in locals() else 'Unknown'}): {sentence_str} - Error: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error parsing NMEA sentence: {sentence_str} - Error: {e}")

    def read_data(self):
        """
        Read and process NMEA data from the GPS module.
        This method should be called periodically in a loop.
        """
        if not self.serial or not self.serial.is_open:
            self.logger.warning("Serial port not open. Attempting to reinitialize.")
            if not self.initialize():
                return None # Cannot read if not initialized
        
        try:
            if self.serial.in_waiting > 0:
                line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    self.logger.debug(f"Raw NMEA: {line}")
                    self._parse_nmea_sentence(line)
            
            # Update fix status based on fix_check_interval (more for consistency with original gps.py)
            # NMEA directly gives fix, so this is less critical but can be used for logging/events
            current_time = time.time()
            if current_time - self.last_fix_check > self.fix_check_interval:
                self.last_fix_check = current_time
                # self.has_fix is updated by NMEA parsing, so just log current status
                self.logger.debug(f"Fix status check: {'Acquired' if self.has_fix else 'Not Acquired'}")

            # Sensor fusion: Data from GGA and RMC (and GSA) are combined into the class attributes.
            # The latest valid data for each field (lat, lon, alt, speed, course, etc.) is stored.
            # has_fix is updated by multiple sentences, ensuring robustness.

            return self.get_current_location()

        except serial.SerialException as e:
            self.logger.error(f"Serial error during read: {e}")
            self.close() # Close port on error, re-init will be attempted next call
            return None
        except Exception as e:
            self.logger.error(f"Error reading GPS data: {e}")
            return None

    def get_current_location(self):
        """
        Return the current GPS data.
        """
        if not self.has_fix and (time.time() - self.last_data_time > 10): # If no fix and no data for 10s
             self.logger.warning("No GPS fix or data recently.")
             # Reset some values if stale and no fix
             # self.latitude, self.longitude = 0.0, 0.0 # Keep last known if preferred

        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'datestamp': self.datestamp.isoformat() if self.datestamp else None,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'altitude': self.altitude,
            'speed_kmh': self.speed_kmh,
            'course': self.course,
            'satellites': self.satellites,
            'hdop': self.hdop,
            'has_fix': self.has_fix
        }

    def close(self):
        """
        Close the serial connection.
        """
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.logger.info("GPS serial connection closed.")
        self.serial = None

# Example Usage (for testing purposes)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Configuration for NEO-6M
    # These would typically come from your config file (e.g., config.yaml)
    gps_port = '/dev/ttyS4' # Change to your actual port, e.g., 'COM3' on Windows
    gps_baudrate = 9600
    
    sgps_module = SGPS(port=gps_port, baudrate=gps_baudrate)
    
    if sgps_module.initialize():
        try:
            start_time = time.time()
            while time.time() - start_time < 600: # Run for 10 minutes
                data = sgps_module.read_data()
                if data:
                    if data['has_fix']:
                        print(f"Fix: Lat={data['latitude']:.6f}, Lon={data['longitude']:.6f}, Alt={data['altitude']:.1f}m, "
                              f"Sats={data['satellites']}, Speed={data['speed_kmh']:.2f}km/h, Course={data['course']:.1f}")
                    else:
                        print("Waiting for GPS fix...")
                time.sleep(1) # Read data every second
        except KeyboardInterrupt:
            print("Stopping GPS test...")
        finally:
            sgps_module.close()
    else:
        print("Failed to initialize GPS module.")
