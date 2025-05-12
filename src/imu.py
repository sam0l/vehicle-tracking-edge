import smbus2
import time
import logging
import math

class IMU:
    """
    IMU class for ICM-20689 with speed estimation and simple dead reckoning.
    Use update_gps(gps_data) to provide latest GPS data (dict with 'latitude', 'longitude', 'speed', 'heading').
    Use get_speed() and get_position() to get current speed and position estimates.
    """
    # ICM-20689 registers (from datasheet)
    REG_PWR_MGMT_1 = 0x6B
    REG_PWR_MGMT_2 = 0x6C
    REG_GYRO_CONFIG = 0x1B
    REG_ACCEL_CONFIG = 0x1C
    REG_CONFIG = 0x1A
    REG_SMPLRT_DIV = 0x19
    REG_USER_CTRL = 0x6A
    REG_FIFO_EN = 0x23
    REG_ACCEL_XOUT_H = 0x3B
    REG_GYRO_XOUT_H = 0x43
    REG_WHO_AM_I = 0x75

    # Expected device ID for ICM-20689
    EXPECTED_WHO_AM_I = 0x98

    def __init__(self, i2c_bus, i2c_addresses=["0x68", "0x69"], sample_rate=100, accel_range=2, gyro_range=250):
        self.logger = logging.getLogger(__name__)
        self.bus = None
        self.address = None
        self.last_address_check = 0
        self.address_check_interval = 1.0  # Check address every second
        self.initialization_attempts = 0
        self.max_init_attempts = 3
        self.i2c_bus = i2c_bus
        self.i2c_addresses = i2c_addresses
        self.sample_rate = sample_rate
        self.accel_range = accel_range
        self.gyro_range = gyro_range
        try:
            self.bus = smbus2.SMBus(i2c_bus)
            # Convert address(es) to int if provided as hex strings
            self.addresses = [
                int(addr, 16) if isinstance(addr, str) else addr
                for addr in (i2c_addresses if isinstance(i2c_addresses, list) else [i2c_addresses])
            ]
            # Set scale based on config
            self.accel_scale = float(accel_range) / 32768.0
            self.gyro_scale = float(gyro_range) / 32768.0
        except Exception as e:
            self.logger.error(f"Failed to open I2C bus {i2c_bus}: {e}")
            raise
        # Dead reckoning state
        self.last_gps = None
        self.last_gps_time = None
        self.last_position = None  # (lat, lon)
        self.last_heading = None   # degrees
        self.last_update_time = None
        self.current_speed = 0.0  # m/s
        self.current_heading = 0.0  # degrees
        self.imu_position = None  # (lat, lon)

    def _scan_for_imu(self):
        """Scan all possible addresses for the IMU."""
        valid_addresses = []
        for addr in self.addresses:
            try:
                device_id = self.bus.read_byte_data(addr, self.REG_WHO_AM_I)
                if device_id == self.EXPECTED_WHO_AM_I:
                    valid_addresses.append(addr)
                    self.logger.debug(f"Found IMU at address 0x{addr:02x} (WHO_AM_I: 0x{device_id:02x})")
            except Exception as e:
                self.logger.debug(f"No IMU at address 0x{addr:02x}: {e}")
                continue
        return valid_addresses

    def _verify_address(self):
        """Verify if the current address is valid."""
        if not self.address:
            return False
        try:
            device_id = self.bus.read_byte_data(self.address, self.REG_WHO_AM_I)
            if device_id == self.EXPECTED_WHO_AM_I:
                return True
            self.logger.warning(f"Invalid WHO_AM_I 0x{device_id:02x} at address 0x{self.address:02x}")
        except Exception as e:
            self.logger.warning(f"Failed to verify address 0x{self.address:02x}: {e}")
        return False

    def _switch_to_valid_address(self):
        """Switch to a valid IMU address if current one is invalid."""
        valid_addresses = self._scan_for_imu()
        if not valid_addresses:
            self.logger.error("No valid IMU addresses found")
            return False

        # If current address is not in valid addresses, switch to first valid one
        if self.address not in valid_addresses:
            new_address = valid_addresses[0]
            self.logger.info(f"Switching IMU address from 0x{self.address:02x} to 0x{new_address:02x}")
            self.address = new_address
            if not self._initialize_at_address():
                self.logger.error(f"Failed to initialize IMU at new address 0x{new_address:02x}")
                return False
        return True

    def _initialize_at_address(self):
        """Initialize IMU at the current address."""
        try:
            # Reset device (PWR_MGMT_1[7] = 1)
            self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_1, 0x80)
            time.sleep(0.1)  # Wait for reset to complete

            # Exit sleep mode and set clock to PLL (PWR_MGMT_1[2:0] = 001)
            self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_1, 0x01)  # SLEEP = 0, CLKSEL = 001
            time.sleep(0.01)  # Wait for PLL to stabilize

            # Enable all gyro and accel axes (PWR_MGMT_2 = 0x00)
            self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_2, 0x00)  # All axes on

            # Configure gyroscope: ±2000 dps (FS_SEL = 3)
            self.bus.write_byte_data(self.address, self.REG_GYRO_CONFIG, 0x18)  # FS_SEL = 3, no self-test

            # Configure accelerometer: ±16g (AFS_SEL = 3)
            self.bus.write_byte_data(self.address, self.REG_ACCEL_CONFIG, 0x18)  # AFS_SEL = 3, no self-test

            # Set sample rate to 1kHz (SMPLRT_DIV = 0, assuming 8kHz internal rate)
            self.bus.write_byte_data(self.address, self.REG_SMPLRT_DIV, 0x00)

            # Configure DLPF for reasonable bandwidth (gyro: 176Hz, accel: 188Hz)
            self.bus.write_byte_data(self.address, self.REG_CONFIG, 0x01)  # DLPF_CFG = 1

            # Reset FIFO and enable it
            self.bus.write_byte_data(self.address, self.REG_USER_CTRL, 0x04)  # FIFO_RST = 1
            time.sleep(0.001)  # Wait for reset
            self.bus.write_byte_data(self.address, self.REG_USER_CTRL, 0x40)  # FIFO_EN = 1
            self.bus.write_byte_data(self.address, self.REG_FIFO_EN, 0x78)  # Enable gyro and accel data to FIFO

            self.logger.info(f"IMU initialized at address 0x{self.address:02x}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize IMU at address 0x{self.address:02x}: {e}")
            return False

    def initialize(self):
        """Initialize the IMU, scanning for valid addresses and setting up the device."""
        self.initialization_attempts = 0
        while self.initialization_attempts < self.max_init_attempts:
            valid_addresses = self._scan_for_imu()
            if not valid_addresses:
                self.logger.error("No valid IMU addresses found")
                self.initialization_attempts += 1
                time.sleep(0.1)
                continue

            # Try each valid address
            for addr in valid_addresses:
                self.address = addr
                if self._initialize_at_address():
                    self.last_address_check = time.time()
                    return True
                self.logger.warning(f"Failed to initialize IMU at address 0x{addr:02x}")

            self.initialization_attempts += 1
            time.sleep(0.1)

        self.logger.error("IMU initialization failed after maximum attempts")
        return False

    def update_gps(self, gps_data):
        """
        Update IMU with latest GPS data. gps_data should be a dict with keys: 'latitude', 'longitude', 'speed', 'heading' (optional).
        """
        if gps_data is None:
            return
        lat = gps_data.get('latitude')
        lon = gps_data.get('longitude')
        speed = gps_data.get('speed')
        heading = gps_data.get('heading')
        now = time.time()
        if lat is not None and lon is not None:
            self.last_position = (lat, lon)
            self.imu_position = (lat, lon)
        if speed is not None:
            self.current_speed = speed
        if heading is not None:
            self.current_heading = heading
        self.last_gps = gps_data
        self.last_gps_time = now
        self.last_update_time = now

    def get_speed(self):
        """
        Return current speed estimate (prefer GPS, fallback to IMU integration).
        """
        # If GPS speed is recent (<5s), use it
        if self.last_gps_time and (time.time() - self.last_gps_time) < 5:
            return self.current_speed
        # Otherwise, fallback to IMU speed estimate
        return self.current_speed

    def get_position(self):
        """
        Return current position estimate (prefer GPS, fallback to dead reckoning).
        """
        # If GPS is recent (<5s), use it
        if self.last_gps_time and (time.time() - self.last_gps_time) < 5 and self.last_position:
            return self.last_position
        # Otherwise, use dead reckoning
        if self.imu_position and self.current_speed > 0:
            dt = time.time() - (self.last_update_time or time.time())
            # Use last known heading (degrees)
            heading_rad = math.radians(self.current_heading)
            # Distance moved in meters
            distance = self.current_speed * dt
            # Approximate conversion: 1 deg latitude ~ 111320m, 1 deg longitude ~ 111320*cos(lat)
            lat, lon = self.imu_position
            dlat = (distance * math.cos(heading_rad)) / 111320.0
            dlon = (distance * math.sin(heading_rad)) / (111320.0 * math.cos(math.radians(lat)) if lat else 1)
            new_lat = lat + dlat
            new_lon = lon + dlon
            self.imu_position = (new_lat, new_lon)
            self.last_update_time = time.time()
            return self.imu_position
        # If no data, return None
        return self.last_position

    def read_data(self):
        """
        Read data from the IMU, handling address changes if needed. Also update speed estimate by integrating acceleration.
        """
        current_time = time.time()
        if current_time - self.last_address_check >= self.address_check_interval:
            if not self._verify_address():
                if not self._switch_to_valid_address():
                    self.logger.error("Cannot read IMU data: no valid address")
                    return None
            self.last_address_check = current_time
        try:
            data = self.bus.read_i2c_block_data(self.address, self.REG_ACCEL_XOUT_H, 14)
            def to_signed(val):
                return val - 65536 if val > 32767 else val
            accel_x = to_signed((data[0] << 8) | data[1]) * self.accel_scale
            accel_y = to_signed((data[2] << 8) | data[3]) * self.accel_scale
            accel_z = to_signed((data[4] << 8) | data[5]) * self.accel_scale
            gyro_x = to_signed((data[8] << 8) | data[9]) * self.gyro_scale
            gyro_y = to_signed((data[10] << 8) | data[11]) * self.gyro_scale
            gyro_z = to_signed((data[12] << 8) | data[13]) * self.gyro_scale
            
            # --- Improved Speed estimation (more reliable without GPS) ---
            now = time.time()
            dt = now - (self.last_update_time or now)
            
            # Use a more robust method to calculate absolute speed
            # Only integrate if GPS is not recent (>5s old)
            is_gps_recent = self.last_gps_time and (now - self.last_gps_time) < 5
            
            if not is_gps_recent:
                # Calculate total horizontal acceleration (ignore gravity component)
                # For a properly aligned IMU, this would use just accel_x and accel_y
                # But we'll use all components to be robust to orientation issues
                
                # First calculate the gravity vector magnitude
                total_accel_magnitude = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)
                
                # Assuming 1g is approximately 9.81 m/s², any magnitude above this
                # likely represents the vehicle's motion
                motion_accel = max(0, total_accel_magnitude - 1.0)  # Subtract 1g (approximate)
                
                # Apply a smoothing filter to reduce noise in the acceleration measurement
                # Using a simple low-pass filter with alpha=0.3
                alpha = 0.3
                self.filtered_accel = motion_accel if not hasattr(self, 'filtered_accel') else \
                                     alpha * motion_accel + (1 - alpha) * self.filtered_accel
                
                # Detect if vehicle is likely stopped (very low acceleration over time)
                if self.filtered_accel < 0.05 and self.current_speed < 0.5:
                    # Vehicle is probably stopped, slowly reduce speed to zero
                    self.current_speed = max(0, self.current_speed - 0.1 * dt)
                else:
                    # Integrate acceleration to update speed, with dampening factor to prevent drift
                    self.current_speed += self.filtered_accel * dt
                    
                    # Apply speed decay to simulate friction and prevent unlimited speed growth
                    # Speed naturally decreases about 5% per second if no acceleration
                    self.current_speed *= (1.0 - 0.05 * dt)
                
                # Limit maximum speed to a reasonable value when no GPS data is available
                # Max speed of 120 km/h (33.3 m/s) without GPS validation seems reasonable
                self.current_speed = min(self.current_speed, 33.3)
                
                # Update heading from gyro_z (yaw rate, deg/s) for dead reckoning
                self.current_heading += gyro_z * dt
                self.current_heading = self.current_heading % 360
            
            self.last_update_time = now
            
            return {
                "accel_x": accel_x,  # g
                "accel_y": accel_y,
                "accel_z": accel_z,
                "gyro_x": gyro_x,    # deg/s
                "gyro_y": gyro_y,
                "gyro_z": gyro_z,
                "speed": self.get_speed(),
                "position": self.get_position(),
                "heading": self.current_heading
            }
        except Exception as e:
            self.logger.error(f"Error reading IMU data at address 0x{self.address:02x}: {e}")
            if self._switch_to_valid_address():
                return self.read_data()
            return None

    def close(self):
        """Close the I2C bus connection."""
        if self.bus:
            self.bus.close()
            self.logger.info(f"IMU I2C bus closed for address 0x{self.address:02x}")
            self.bus = None
            self.address = None
