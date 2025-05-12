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
        self.last_gps_time = 0  # Initialize to 0 instead of None to avoid timestamp errors
        self.last_position = None  # (lat, lon)
        self.last_heading = None   # degrees
        self.last_update_time = time.time()  # Initialize to current time
        self.current_speed = 0.0  # m/s
        self.current_heading = 0.0  # degrees
        self.imu_position = None  # (lat, lon)
        
        # Calibration and filtering values
        self.accel_bias = [0, 0, 0]  # Bias in each axis
        self.gravity_norm = 1.0  # Expected gravity norm
        self.filtered_accel = 0.0  # Filtered acceleration value
        self.is_stationary = True  # Default to stationary
        self.stationary_duration = 0.0  # How long we've been stationary
        self.motion_threshold = 0.03  # Threshold for detecting motion (g)
        self.stationary_threshold = 0.02  # Lower threshold for confirming stationary state
        self.stationary_timeout = 0.5  # Seconds with low acceleration to declare stationary
        self.last_motion_time = 0  # Time of last detected motion
        self.consecutive_stationary_samples = 0  # Track consecutive samples below threshold

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
            
            # Perform initial calibration after initialization
            self._calibrate_stationary()
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize IMU at address 0x{self.address:02x}: {e}")
            return False
            
    def _calibrate_stationary(self):
        """Perform a quick calibration to set baseline values."""
        samples = []
        self.logger.info("Performing quick IMU calibration...")
        
        # Collect multiple samples to determine bias and gravity norm
        for _ in range(20):  # 20 samples is enough for a quick calibration
            try:
                data = self.bus.read_i2c_block_data(self.address, self.REG_ACCEL_XOUT_H, 14)
                def to_signed(val):
                    return val - 65536 if val > 32767 else val
                    
                accel_x = to_signed((data[0] << 8) | data[1]) * self.accel_scale
                accel_y = to_signed((data[2] << 8) | data[3]) * self.accel_scale
                accel_z = to_signed((data[4] << 8) | data[5]) * self.accel_scale
                
                # Store readings
                samples.append((accel_x, accel_y, accel_z))
                time.sleep(0.01)
            except Exception as e:
                self.logger.warning(f"Error during calibration: {e}")
                continue
                
        if not samples:
            self.logger.warning("Calibration failed: could not get samples")
            return
            
        # Calculate average for each axis
        accel_x_sum = sum(s[0] for s in samples)
        accel_y_sum = sum(s[1] for s in samples)
        accel_z_sum = sum(s[2] for s in samples)
        count = len(samples)
        
        # Calculate average values
        avg_x = accel_x_sum / count
        avg_y = accel_y_sum / count
        avg_z = accel_z_sum / count
        
        # Set bias values for x and y axes (assuming device is aligned with gravity along z-axis)
        self.accel_bias[0] = avg_x
        self.accel_bias[1] = avg_y
        self.accel_bias[2] = 0  # For Z, we don't remove bias since it includes gravity
        
        # Calculate gravity norm (magnitude of acceleration vector)
        self.gravity_norm = math.sqrt(avg_x**2 + avg_y**2 + avg_z**2)
        
        self.logger.info(f"Calibration complete: bias=[{avg_x:.4f}, {avg_y:.4f}, {avg_z:.4f}], gravity_norm={self.gravity_norm:.4f}")

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
                    # Reset timestamp fields to prevent problems
                    self.last_update_time = time.time()
                    self.last_gps_time = 0  # Not None to prevent type errors
                    self.last_motion_time = time.time()
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
            # If GPS speed is very low, treat as stopped
            if speed < 0.5:  # Less than 0.5 m/s (1.8 km/h)
                self.current_speed = 0.0
                self.is_stationary = True
            else:
                self.current_speed = speed
                self.is_stationary = False
        if heading is not None:
            self.current_heading = heading
        self.last_gps = gps_data
        self.last_gps_time = now  # Important: use current time, not GPS timestamp
        self.last_update_time = now

    def get_speed(self):
        """
        Return current speed estimate (prefer GPS, fallback to IMU integration).
        """
        current_time = time.time()
        
        # If GPS speed is recent (<5s), use it
        if self.last_gps_time and (current_time - self.last_gps_time) < 5:
            return self.current_speed
            
        # Check if we've been stationary for a while
        if self.is_stationary:
            return 0.0
            
        # Otherwise, fallback to IMU speed estimate
        return self.current_speed

    def get_position(self):
        """
        Return current position estimate (prefer GPS, fallback to dead reckoning).
        """
        current_time = time.time()
        
        # If GPS is recent (<5s), use it
        if self.last_gps_time and (current_time - self.last_gps_time) < 5 and self.last_position:
            return self.last_position
            
        # If we're stationary or very low speed, don't update position via dead reckoning
        if self.is_stationary or self.current_speed < 0.5:
            return self.last_position
            
        # Otherwise, use dead reckoning
        if self.imu_position and self.current_speed > 0:
            dt = current_time - (self.last_update_time or current_time)
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
            self.last_update_time = current_time
            return self.imu_position
            
        # If no data, return None
        return self.last_position

    def read_data(self):
        """
        Read data from the IMU, handling address changes if needed. Also update speed estimate by integrating acceleration.
        """
        current_time = time.time()
        dt = max(0.001, current_time - (self.last_update_time or current_time))  # Prevent division by zero
        
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
            
            # Apply calibration correction to x and y axes
            accel_x -= self.accel_bias[0]
            accel_y -= self.accel_bias[1]
            
            # --- Improved Speed estimation for stationary detection ---
            # Only update speed if GPS data is not recent
            is_gps_recent = self.last_gps_time and (current_time - self.last_gps_time) < 5
            
            if not is_gps_recent:
                # Calculate total acceleration magnitude
                total_accel = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)
                
                # Adjust for gravity (should be close to 0 when stationary)
                adjusted_accel = abs(total_accel - self.gravity_norm)
                
                # Apply low-pass filter to smooth acceleration readings
                alpha = 0.2  # Low pass filter coefficient (0-1)
                self.filtered_accel = alpha * adjusted_accel + (1 - alpha) * (self.filtered_accel if hasattr(self, 'filtered_accel') else 0)
                
                # Check if acceleration is below the stationary threshold
                if self.filtered_accel < self.stationary_threshold:
                    self.consecutive_stationary_samples += 1
                    
                    # After several consecutive low readings, confirm stationary state
                    if self.consecutive_stationary_samples >= 10:  # About 0.1s at 100Hz
                        if not self.is_stationary:
                            self.logger.debug(f"Device is now stationary (accel={self.filtered_accel:.4f}g)")
                        self.is_stationary = True
                        
                        # When stationary, aggressively reduce speed to zero
                        self.current_speed = max(0, self.current_speed - 0.5 * dt)
                        if self.current_speed < 0.1:  # Below 0.1 m/s (0.36 km/h)
                            self.current_speed = 0.0
                else:
                    # Above the threshold - potential movement detected
                    self.consecutive_stationary_samples = 0
                    
                    # Only transition to moving state if above motion threshold
                    if self.filtered_accel > self.motion_threshold:
                        if self.is_stationary:
                            self.logger.debug(f"Device is now moving (accel={self.filtered_accel:.4f}g)")
                        self.is_stationary = False
                        self.last_motion_time = current_time
                        
                        # Integrate acceleration to update speed, scaled to m/s²
                        accel_ms2 = self.filtered_accel * 9.81  # Convert g to m/s²
                        self.current_speed += accel_ms2 * dt
                        
                        # Apply dampening to prevent drift in speed estimation
                        self.current_speed *= (1.0 - 0.05 * dt)  # 5% decay per second
                
                # Limit maximum speed to reasonable values
                self.current_speed = min(33.3, max(0, self.current_speed))  # 0-120 km/h
                
                # Update heading from gyro_z (yaw rate, deg/s)
                self.current_heading += gyro_z * dt
                self.current_heading = self.current_heading % 360
            
            self.last_update_time = current_time
            
            # Build the response object
            result = {
                "accel_x": accel_x,  # g
                "accel_y": accel_y,
                "accel_z": accel_z,
                "gyro_x": gyro_x,    # deg/s
                "gyro_y": gyro_y,
                "gyro_z": gyro_z,
                "speed": self.get_speed(),
                "position": self.get_position(),
                "heading": self.current_heading,
                "is_stationary": self.is_stationary,
                "filtered_accel": self.filtered_accel
            }
            
            return result
            
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
