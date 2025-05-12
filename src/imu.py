import smbus2
import time
import logging
import math
import numpy as np

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
    REG_INT_PIN_CFG = 0x37
    REG_INT_ENABLE = 0x38
    REG_TEMP_OUT_H = 0x41
    REG_TEMP_OUT_L = 0x42

    # Expected device ID for ICM-20689
    EXPECTED_WHO_AM_I = 0x98
    
    # Available ranges and their corresponding register values
    ACCEL_RANGE_MAP = {
        2: 0x00,   # ±2g
        4: 0x08,   # ±4g
        8: 0x10,   # ±8g
        16: 0x18   # ±16g
    }
    
    GYRO_RANGE_MAP = {
        250: 0x00,   # ±250 dps
        500: 0x08,   # ±500 dps
        1000: 0x10,  # ±1000 dps
        2000: 0x18   # ±2000 dps
    }
    
    # For internal calculations
    GRAVITY = 9.80665  # m/s²
    
    # Temperature conversion constants
    TEMP_SENSITIVITY = 333.87
    TEMP_OFFSET = 21.0

    def __init__(self, i2c_bus, i2c_addresses=None, sample_rate=100, accel_range=2, gyro_range=250):
        self.logger = logging.getLogger(__name__)
        self.bus = None
        self.address = None
        self.last_address_check = 0
        self.address_check_interval = 1.0  # Check address every second
        self.initialization_attempts = 0
        self.max_init_attempts = 3
        self.i2c_bus = i2c_bus
        
        # Handle default arguments properly
        if i2c_addresses is None:
            self.i2c_addresses = ["0x68", "0x69"]
        else:
            self.i2c_addresses = i2c_addresses
            
        self.sample_rate = sample_rate
        
        # Ensure valid range settings
        if accel_range not in self.ACCEL_RANGE_MAP:
            self.logger.warning(f"Invalid accel_range {accel_range}, defaulting to 2g")
            accel_range = 2
        if gyro_range not in self.GYRO_RANGE_MAP:
            self.logger.warning(f"Invalid gyro_range {gyro_range}, defaulting to 250dps")
            gyro_range = 250
            
        self.accel_range = accel_range
        self.gyro_range = gyro_range
        
        try:
            self.bus = smbus2.SMBus(i2c_bus)
            # Convert address(es) to int if provided as hex strings
            self.addresses = [
                int(addr, 16) if isinstance(addr, str) else addr
                for addr in (self.i2c_addresses if isinstance(self.i2c_addresses, list) else [self.i2c_addresses])
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
        self.accel_bias = np.zeros(3)  # Bias in each axis
        self.gyro_bias = np.zeros(3)   # Gyro bias in each axis
        self.gravity_norm = 1.0  # Expected gravity norm
        self.filtered_accel = 0.0  # Filtered acceleration value
        self.is_stationary = True  # Default to stationary
        self.stationary_duration = 0.0  # How long we've been stationary
        self.motion_threshold = 0.03  # Threshold for detecting motion (g)
        self.stationary_threshold = 0.01  # Lower threshold for confirming stationary state
        self.stationary_timeout = 0.5  # Seconds with low acceleration to declare stationary
        self.last_motion_time = 0  # Time of last detected motion
        self.consecutive_stationary_samples = 0  # Track consecutive samples below threshold
        
        # Kalman filter state for sensor fusion
        self.kalman_initialized = False
        # State vector: [x_pos, y_pos, vx, vy, ax, ay, heading]
        self.kf_state = np.zeros(7)
        # State covariance matrix
        self.kf_covariance = np.eye(7) * 100  # High initial uncertainty
        # Process noise (Q) and measurement noise (R) matrices
        self.kf_process_noise = np.eye(7) * 0.01
        self.kf_measurement_noise = np.eye(4) * 0.1  # For [vx, vy, ax, ay]
        
        # Temperature calibration
        self.temp_offset = 0.0
        self.temp_sensitivity = self.TEMP_SENSITIVITY

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

    def _wake_up_sensor(self):
        """Wake up the sensor from sleep mode."""
        # Reset device (PWR_MGMT_1[7] = 1)
        self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_1, 0x80)
        time.sleep(0.1)  # Wait for reset to complete

        # Exit sleep mode and set clock to PLL (PWR_MGMT_1[2:0] = 001)
        self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_1, 0x01)  # SLEEP = 0, CLKSEL = 001
        time.sleep(0.01)  # Wait for PLL to stabilize

        # Enable all gyro and accel axes (PWR_MGMT_2 = 0x00)
        self.bus.write_byte_data(self.address, self.REG_PWR_MGMT_2, 0x00)  # All axes on
        
        self.logger.debug("IMU woken up and all axes enabled")
    
    def _set_accel_range(self, accel_range):
        """Set the accelerometer range."""
        if accel_range not in self.ACCEL_RANGE_MAP:
            self.logger.warning(f"Invalid accel_range {accel_range}, defaulting to 2g")
            accel_range = 2
            
        reg_value = self.ACCEL_RANGE_MAP[accel_range]
        self.bus.write_byte_data(self.address, self.REG_ACCEL_CONFIG, reg_value)
        self.accel_range = accel_range
        self.accel_scale = float(accel_range) / 32768.0
        self.logger.debug(f"Accelerometer range set to ±{accel_range}g")
    
    def _set_gyro_range(self, gyro_range):
        """Set the gyroscope range."""
        if gyro_range not in self.GYRO_RANGE_MAP:
            self.logger.warning(f"Invalid gyro_range {gyro_range}, defaulting to 250dps")
            gyro_range = 250
            
        reg_value = self.GYRO_RANGE_MAP[gyro_range]
        self.bus.write_byte_data(self.address, self.REG_GYRO_CONFIG, reg_value)
        self.gyro_range = gyro_range
        self.gyro_scale = float(gyro_range) / 32768.0
        self.logger.debug(f"Gyroscope range set to ±{gyro_range}dps")
    
    def _set_sample_rate(self, sample_rate):
        """Set the sample rate divider."""
        # The sample rate is calculated as: Sample Rate = Gyroscope Output Rate / (1 + SMPLRT_DIV)
        # For ICM-20689, default gyroscope output rate is 8kHz with DLPF disabled, 1kHz with DLPF enabled
        
        # Assume 1kHz with DLPF enabled
        base_rate = 1000
        
        # Calculate divider to achieve target sample rate
        if sample_rate <= 0:
            sample_rate = 100  # Default to 100Hz if invalid
            
        if sample_rate > base_rate:
            sample_rate = base_rate  # Cap at max possible rate
            
        divider = int(base_rate / sample_rate - 1)
        divider = max(0, min(255, divider))  # Ensure within valid range (0-255)
        
        self.bus.write_byte_data(self.address, self.REG_SMPLRT_DIV, divider)
        
        # Update the actual sample rate achieved
        self.sample_rate = base_rate / (1 + divider)
        self.logger.debug(f"Sample rate set to {self.sample_rate:.1f}Hz (divider: {divider})")
    
    def _configure_dlpf(self, bandwidth_setting=1):
        """Configure Digital Low Pass Filter (DLPF)."""
        # bandwidth_setting values (for CONFIG register):
        # 0: 260Hz accel, 256Hz gyro
        # 1: 184Hz accel, 188Hz gyro
        # 2: 94Hz accel, 98Hz gyro
        # 3: 44Hz accel, 42Hz gyro
        # 4: 21Hz accel, 20Hz gyro
        # 5: 10Hz accel, 10Hz gyro
        # 6: 5Hz accel, 5Hz gyro
        
        if bandwidth_setting < 0 or bandwidth_setting > 6:
            bandwidth_setting = 1  # Default to moderate filtering
            
        self.bus.write_byte_data(self.address, self.REG_CONFIG, bandwidth_setting)
        self.logger.debug(f"DLPF configured with bandwidth setting {bandwidth_setting}")
    
    def _configure_interrupts(self, enable_data_ready=False):
        """Configure interrupt settings."""
        # Set INT pin to active high, push-pull, and latch until cleared
        int_pin_cfg = 0x10  # INT_ANYRD_2CLEAR: Interrupt status is cleared on any read
        self.bus.write_byte_data(self.address, self.REG_INT_PIN_CFG, int_pin_cfg)
        
        # Enable/disable interrupts
        int_enable = 0x00
        if enable_data_ready:
            int_enable |= 0x01  # Enable data ready interrupt
            
        self.bus.write_byte_data(self.address, self.REG_INT_ENABLE, int_enable)
        self.logger.debug(f"Interrupts configured: data_ready={enable_data_ready}")
    
    def _initialize_at_address(self):
        """Initialize IMU at the current address."""
        try:
            # Wake up the device
            self._wake_up_sensor()
            
            # Configure sensor with specified settings
            if not self.configure_sensor():
                return False

            # Reset FIFO and enable it
            self.bus.write_byte_data(self.address, self.REG_USER_CTRL, 0x04)  # FIFO_RST = 1
            time.sleep(0.001)  # Wait for reset
            self.bus.write_byte_data(self.address, self.REG_USER_CTRL, 0x40)  # FIFO_EN = 1
            self.bus.write_byte_data(self.address, self.REG_FIFO_EN, 0x78)  # Enable gyro and accel data to FIFO

            self.logger.info(f"IMU initialized at address 0x{self.address:02x}")
            
            # Perform initial calibration after initialization
            self._calibrate_imu()
            
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize IMU at address 0x{self.address:02x}: {e}")
            return False

    def _calibrate_imu(self):
        """Perform a comprehensive IMU calibration."""
        self.logger.info("Starting comprehensive IMU calibration...")
        
        # First calibrate gyroscope (must be stationary)
        self._calibrate_gyro()
        
        # Then calibrate accelerometer
        self._calibrate_accel()
        
        # Set initial state
        self.is_stationary = True
        self.consecutive_stationary_samples = 20  # Initialize with enough samples to be considered stationary
        self.current_speed = 0.0
        
        self.logger.info("IMU calibration complete")

    def _calibrate_gyro(self, num_samples=100):
        """Calibrate gyroscope bias by averaging readings while stationary."""
        self.logger.info(f"Calibrating gyroscope with {num_samples} samples...")
        
        # Collect gyroscope data
        gyro_x_sum = 0
        gyro_y_sum = 0
        gyro_z_sum = 0
        valid_samples = 0
        
        for _ in range(num_samples):
            try:
                raw_data = self.read_raw_data()
                if raw_data:
                    gyro_x_sum += raw_data['gyro_x'] * self.gyro_scale
                    gyro_y_sum += raw_data['gyro_y'] * self.gyro_scale
                    gyro_z_sum += raw_data['gyro_z'] * self.gyro_scale
                    valid_samples += 1
                time.sleep(0.01)  # Small delay between readings
            except Exception as e:
                self.logger.warning(f"Error during gyro calibration: {e}")
                continue
        
        if valid_samples < 20:
            self.logger.warning(f"Gyro calibration used only {valid_samples} samples, which may not be reliable")
            return
            
        # Calculate average bias
        self.gyro_bias[0] = gyro_x_sum / valid_samples
        self.gyro_bias[1] = gyro_y_sum / valid_samples
        self.gyro_bias[2] = gyro_z_sum / valid_samples
        
        self.logger.info(f"Gyro calibration complete: bias=[{self.gyro_bias[0]:.4f}, {self.gyro_bias[1]:.4f}, {self.gyro_bias[2]:.4f}] deg/s")
    
    def _calibrate_accel(self, num_samples=100):
        """Calibrate accelerometer bias and detect gravity direction."""
        self.logger.info(f"Calibrating accelerometer with {num_samples} samples...")
        
        # Collect accelerometer data
        samples = []
        
        for _ in range(num_samples):
            try:
                raw_data = self.read_raw_data()
                if raw_data:
                    accel_x = raw_data['accel_x'] * self.accel_scale
                    accel_y = raw_data['accel_y'] * self.accel_scale
                    accel_z = raw_data['accel_z'] * self.accel_scale
                    samples.append((accel_x, accel_y, accel_z))
                time.sleep(0.01)  # Small delay between readings
            except Exception as e:
                self.logger.warning(f"Error during accel calibration: {e}")
                continue
                
        if len(samples) < 20:
            self.logger.warning(f"Accel calibration used only {len(samples)} samples, which may not be reliable")
            return
            
        # Convert to numpy arrays for easier computation
        accel_data = np.array(samples)
        
        # Calculate mean and standard deviation
        accel_mean = np.mean(accel_data, axis=0)
        accel_std = np.std(accel_data, axis=0)
        
        # Set bias values
        self.accel_bias = accel_mean
        
        # Calculate gravity norm (magnitude of acceleration vector)
        self.gravity_norm = np.linalg.norm(accel_mean)
        
        # Dynamic threshold calculation based on noise level
        noise_factor = 5.0  # Number of standard deviations to consider as motion
        mean_std = np.mean(accel_std)
        self.motion_threshold = max(0.03, noise_factor * mean_std)  # At least 0.03g
        self.stationary_threshold = max(0.01, 0.3 * self.motion_threshold)  # Lower threshold for stationary state
        
        self.logger.info(f"Accel calibration complete: bias=[{accel_mean[0]:.4f}, {accel_mean[1]:.4f}, {accel_mean[2]:.4f}]g")
        self.logger.info(f"Gravity norm={self.gravity_norm:.4f}g, noise={mean_std:.6f}g")
        self.logger.info(f"Motion threshold={self.motion_threshold:.4f}g, stationary threshold={self.stationary_threshold:.4f}g")
        
    def configure_sensor(self):
        """Configure the IMU sensor with current settings."""
        if not self.address:
            self.logger.error("Cannot configure sensor: no valid address")
            return False
            
        try:
            # Wake up the device if it's in sleep mode
            self._wake_up_sensor()
            
            # Configure accelerometer range
            self._set_accel_range(self.accel_range)
            
            # Configure gyroscope range
            self._set_gyro_range(self.gyro_range)
            
            # Configure sample rate
            self._set_sample_rate(self.sample_rate)
            
            # Configure low-pass filter
            self._configure_dlpf()
            
            # Configure interrupts if needed
            self._configure_interrupts()
            
            self.logger.info(f"IMU configured: accel={self.accel_range}g, gyro={self.gyro_range}dps, rate={self.sample_rate}Hz")
            return True
        except Exception as e:
            self.logger.error(f"Error configuring IMU: {e}")
            return False

    def update_gps(self, gps_data):
        """
        Update IMU with latest GPS data. gps_data should be a dict with keys: 'latitude', 'longitude', 'speed', 'heading' (optional).
        """
        if gps_data is None:
            return
            
        now = time.time()
        
        # Extract GPS data
        lat = gps_data.get('latitude')
        lon = gps_data.get('longitude')
        speed = gps_data.get('speed')
        heading = gps_data.get('heading')
        
        # Basic position update (for compatibility)
        if lat is not None and lon is not None:
            self.last_position = (lat, lon)
            self.imu_position = (lat, lon)
            
        # Basic stationary detection (for compatibility)
        if speed is not None and speed < 0.5:  # Less than 0.5 m/s (1.8 km/h)
            self.is_stationary = True
            self.current_speed = 0.0
            
        # Update Kalman filter with GPS data
        self._update_kalman_with_gps(gps_data)
            
        # Store GPS data and update timestamps
        self.last_gps = gps_data
        self.last_gps_time = now  # Important: use current time, not GPS timestamp
        self.last_update_time = now

    def get_speed(self):
        """
        Return current speed estimate using Kalman filter if available, otherwise fallback to direct calculation.
        """
        current_time = time.time()
        
        # If GPS speed is recent (<5s), use it as the most reliable source
        if self.last_gps_time and (current_time - self.last_gps_time) < 5:
            return round(self.current_speed, 2)
            
        # If we're in stationary state, return 0
        if self.is_stationary:
            return 0.0
            
        # If Kalman filter is initialized, use its velocity estimate
        if self.kalman_initialized:
            # Calculate speed from velocity components
            kf_speed = math.sqrt(self.kf_state[2]**2 + self.kf_state[3]**2)
            return round(kf_speed, 2)
            
        # Otherwise, fallback to directly calculated speed
        return round(self.current_speed, 2)

    def get_position(self):
        """
        Return current position estimate using Kalman filter for dead reckoning if GPS is not recent.
        """
        current_time = time.time()
        
        # If GPS is recent (<5s), use it
        if self.last_gps_time and (current_time - self.last_gps_time) < 5 and self.last_position:
            return self.last_position
            
        # If we're stationary or very low speed, don't update position via dead reckoning
        if self.is_stationary or self.current_speed < 0.5:
            return self.last_position
            
        # If Kalman filter is initialized and we have a last GPS position, use KF for dead reckoning
        if self.kalman_initialized and self.last_position and self.imu_position:
            # Convert Kalman filter's local x,y displacement to lat/lon
            if abs(self.kf_state[0]) > 0.001 or abs(self.kf_state[1]) > 0.001:  # If there's meaningful displacement
                # Get last known position
                lat, lon = self.imu_position
                
                # Convert local x,y displacement to lat/lon
                # Approximate conversion: 1m in x = ~1/(111320*cos(lat)) degrees longitude
                # Approximate conversion: 1m in y = ~1/111320 degrees latitude
                cos_lat = math.cos(math.radians(lat))
                dlon = self.kf_state[0] / (111320.0 * cos_lat) if abs(cos_lat) > 1e-9 else 0
                dlat = self.kf_state[1] / 111320.0
                
                # Calculate new position
                new_lat = lat + dlat
                new_lon = lon + dlon
                
                # Update IMU position
                self.imu_position = (new_lat, new_lon)
                
                # Reset local x,y in Kalman filter
                self.kf_state[0:2] = 0.0
            
            return self.imu_position
            
        # If Kalman filter not initialized but we have speed and heading, use simple dead reckoning
        elif self.imu_position and self.current_speed > 0:
            dt = current_time - self.last_update_time
            
            # Use last known heading (degrees)
            heading_rad = math.radians(self.current_heading)
            
            # Distance moved in meters
            distance = self.current_speed * dt
            
            # Get last known position
            lat, lon = self.imu_position
            
            # Approximate conversion: 1 deg latitude ~ 111320m, 1 deg longitude ~ 111320*cos(lat)
            dlat = (distance * math.cos(heading_rad)) / 111320.0
            dlon = (distance * math.sin(heading_rad)) / (111320.0 * math.cos(math.radians(lat)) if lat else 1)
            
            # Calculate new position
            new_lat = lat + dlat
            new_lon = lon + dlon
            
            # Update IMU position
            self.imu_position = (new_lat, new_lon)
            
            return self.imu_position
            
        # If no data, return last known position
        return self.last_position

    def read_data(self):
        """
        Read data from the IMU, process it through Kalman filter, and return processed data.
        """
        current_time = time.time()
        dt = current_time - self.last_update_time
        if dt <= 0:
            dt = 0.01  # Prevent division by zero with a reasonable default
        
        # Check if we need to verify the IMU address
        if current_time - self.last_address_check >= self.address_check_interval:
            if not self._verify_address():
                if not self._switch_to_valid_address():
                    self.logger.error("Cannot read IMU data: no valid address")
                    return None
            self.last_address_check = current_time
            
        try:
            # Get raw sensor data
            raw_data = self.read_raw_data()
            if not raw_data:
                return None
                
            # Convert to physical units with calibration applied
            sensor_data = self.convert_raw_to_physical(raw_data)
            
            # Extract accelerometer and gyroscope data
            accel_x = sensor_data['accel_x']
            accel_y = sensor_data['accel_y']
            accel_z = sensor_data['accel_z']
            gyro_x = sensor_data['gyro_x']
            gyro_y = sensor_data['gyro_y']
            gyro_z = sensor_data['gyro_z']
            
            # --- Improved motion detection and stationary state detection ---
            
            # Calculate total acceleration magnitude
            total_accel = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)
            
            # Adjust for gravity (should be close to 0 when stationary)
            adjusted_accel = abs(total_accel - self.gravity_norm)
            
            # Apply low-pass filter to smooth acceleration readings
            alpha = 0.2  # Low pass filter coefficient (0-1)
            self.filtered_accel = alpha * adjusted_accel + (1 - alpha) * self.filtered_accel
            
            # Check if acceleration is below the stationary threshold
            if self.filtered_accel < self.stationary_threshold:
                self.consecutive_stationary_samples += 1
                
                # After several consecutive low readings, confirm stationary state
                if self.consecutive_stationary_samples >= 15:
                    if not self.is_stationary:
                        self.logger.debug(f"Device is now stationary (accel={self.filtered_accel:.4f}g)")
                    self.is_stationary = True
                    
                    # When stationary, immediately zero the speed
                    self.current_speed = 0.0
                    
                    # Also zero velocities in Kalman filter state
                    if self.kalman_initialized:
                        self.kf_state[2:6] = 0.0  # Zero out velocities and accelerations
            else:
                # Above the threshold - potential movement detected
                self.consecutive_stationary_samples = 0
                
                # Only transition to moving state if above motion threshold
                if self.filtered_accel > self.motion_threshold:
                    if self.is_stationary:
                        self.logger.debug(f"Device is now moving (accel={self.filtered_accel:.4f}g)")
                    self.is_stationary = False
                    self.last_motion_time = current_time
            
            # --- Kalman Filter Update ---
            
            # Only update Kalman filter with IMU data if GPS data is not recent
            is_gps_recent = self.last_gps_time and (current_time - self.last_gps_time) < 5
            
            if not is_gps_recent:
                # Initialize Kalman filter if not already done
                if not self.kalman_initialized and self.last_position:
                    self._initialize_kalman_filter(self.last_position, self.current_heading)
                
                # Predict step
                if self.kalman_initialized:
                    self._predict_kalman(dt)
                    
                    # Only update with IMU data if we're not stationary
                    if not self.is_stationary:
                        self._update_kalman_with_imu(accel_x, accel_y, gyro_z, dt)
            
            # Update position using dead reckoning if needed
            position = self.get_position()
            
            # Update tracking time
            self.last_update_time = current_time
            
            # Build the response object
            result = {
                # Raw sensor data
                "accel_x": accel_x,  # g
                "accel_y": accel_y,  # g
                "accel_z": accel_z,  # g
                "gyro_x": gyro_x,    # deg/s
                "gyro_y": gyro_y,    # deg/s
                "gyro_z": gyro_z,    # deg/s
                "temp": sensor_data['temp'],  # °C
                
                # Processed data
                "speed": round(self.get_speed(), 2),  # m/s, rounded to 2 decimal places
                "position": position,  # (lat, lon)
                "heading": round(self.current_heading, 2),  # degrees, rounded to 2 decimal places
                "is_stationary": self.is_stationary,  # boolean
                "filtered_accel": round(self.filtered_accel, 4)  # g, rounded to 4 decimal places
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

    # --- Raw Data Reading Methods ---
    
    def read_raw_data(self):
        """Read raw sensor data from registers."""
        if not self.address:
            return None
            
        try:
            # Read accelerometer, temperature and gyroscope data (14 bytes)
            data = self.bus.read_i2c_block_data(self.address, self.REG_ACCEL_XOUT_H, 14)
            
            # Parse raw values
            raw_accel_x = (data[0] << 8) | data[1]
            raw_accel_y = (data[2] << 8) | data[3]
            raw_accel_z = (data[4] << 8) | data[5]
            
            raw_temp = (data[6] << 8) | data[7]
            
            raw_gyro_x = (data[8] << 8) | data[9]
            raw_gyro_y = (data[10] << 8) | data[11]
            raw_gyro_z = (data[12] << 8) | data[13]
            
            # Convert to signed 16-bit values
            raw_data = {
                'accel_x': self._to_signed_int16(raw_accel_x),
                'accel_y': self._to_signed_int16(raw_accel_y),
                'accel_z': self._to_signed_int16(raw_accel_z),
                'temp': self._to_signed_int16(raw_temp),
                'gyro_x': self._to_signed_int16(raw_gyro_x),
                'gyro_y': self._to_signed_int16(raw_gyro_y),
                'gyro_z': self._to_signed_int16(raw_gyro_z)
            }
            
            return raw_data
            
        except Exception as e:
            self.logger.error(f"Error reading raw IMU data: {e}")
            return None
    
    def _to_signed_int16(self, value):
        """Convert unsigned 16-bit value to signed 16-bit value."""
        return value - 65536 if value > 32767 else value
        
    def convert_raw_to_physical(self, raw_data):
        """Convert raw sensor readings to physical units."""
        if not raw_data:
            return None
            
        # Apply scale factors
        accel_x = raw_data['accel_x'] * self.accel_scale
        accel_y = raw_data['accel_y'] * self.accel_scale
        accel_z = raw_data['accel_z'] * self.accel_scale
        
        # Temperature in degrees Celsius
        temp_celsius = raw_data['temp'] / self.temp_sensitivity + self.temp_offset
        
        gyro_x = raw_data['gyro_x'] * self.gyro_scale
        gyro_y = raw_data['gyro_y'] * self.gyro_scale
        gyro_z = raw_data['gyro_z'] * self.gyro_scale
        
        # Apply calibration (bias correction)
        accel_x -= self.accel_bias[0]
        accel_y -= self.accel_bias[1]
        accel_z -= self.accel_bias[2]
        
        gyro_x -= self.gyro_bias[0]
        gyro_y -= self.gyro_bias[1] 
        gyro_z -= self.gyro_bias[2]
        
        return {
            'accel_x': accel_x,  # g
            'accel_y': accel_y,  # g
            'accel_z': accel_z,  # g
            'temp': temp_celsius,  # °C
            'gyro_x': gyro_x,  # degrees/s
            'gyro_y': gyro_y,  # degrees/s
            'gyro_z': gyro_z,  # degrees/s
            'timestamp': time.time()
        }
        
    def read_sensor_data(self):
        """Read and convert sensor data in one step."""
        raw_data = self.read_raw_data()
        if raw_data:
            return self.convert_raw_to_physical(raw_data)
        return None

    def calibrate_stationary(self):
        """Quick calibration that can be called while running."""
        self._calibrate_imu()

    # --- Sensor Fusion Methods ---
    
    def _initialize_kalman_filter(self, position=None, heading=None):
        """Initialize Kalman filter state with known position and heading."""
        # Initialize state vector
        if position:
            lat, lon = position
            # Use simple local coordinates - we'll convert back to lat/lon later
            self.kf_state[0:2] = 0.0  # Local x,y position (relative to starting point)
        
        if heading is not None:
            self.kf_state[6] = heading  # Heading in degrees
            
        # Initialize velocities and accelerations to zero
        self.kf_state[2:6] = 0.0
        
        # Mark as initialized
        self.kalman_initialized = True
        self.logger.debug("Kalman filter initialized")
        
    def _predict_kalman(self, dt):
        """Predict step of Kalman filter."""
        if not self.kalman_initialized:
            return

        # State vector: [x_pos, y_pos, vx, vy, ax, ay, heading]
        # Create state transition matrix F
        F = np.eye(7)
        
        # Position updates based on velocity and acceleration
        F[0, 2] = dt      # x += vx*dt
        F[0, 4] = 0.5*dt*dt  # x += 0.5*ax*dt²
        F[1, 3] = dt      # y += vy*dt
        F[1, 5] = 0.5*dt*dt  # y += 0.5*ay*dt²
        
        # Velocity updates based on acceleration
        F[2, 4] = dt      # vx += ax*dt
        F[3, 5] = dt      # vy += ay*dt
        
        # Predict state
        self.kf_state = F @ self.kf_state
        
        # Update covariance: P = F*P*F' + Q
        self.kf_covariance = F @ self.kf_covariance @ F.T + self.kf_process_noise
        
    def _update_kalman_with_imu(self, accel_x, accel_y, gyro_z, dt):
        """Update Kalman filter with IMU measurements."""
        if not self.kalman_initialized:
            return
            
        # Convert heading from degrees to radians for calculation
        heading_rad = math.radians(self.kf_state[6])
        
        # Convert acceleration from sensor frame to world frame
        # This is a simplification - a proper implementation would use quaternions
        # to represent orientation and rotate the acceleration vector
        world_ax = accel_x * math.cos(heading_rad) - accel_y * math.sin(heading_rad)
        world_ay = accel_x * math.sin(heading_rad) + accel_y * math.cos(heading_rad)
        
        # Remove gravity from z-axis (if we had proper orientation)
        # world_az -= gravity_norm
        
        # Update heading directly from gyro integration
        self.kf_state[6] += gyro_z * dt
        self.kf_state[6] %= 360.0  # Normalize to 0-360 degrees
        
        # Create measurement vector: [vx, vy, ax, ay]
        # We're not directly measuring velocity, but we can estimate it
        # from previous acceleration readings
        vx_measured = self.kf_state[2] + world_ax * dt
        vy_measured = self.kf_state[3] + world_ay * dt
        
        z = np.array([vx_measured, vy_measured, world_ax, world_ay])
        
        # Create measurement matrix H (maps states to measurements)
        H = np.zeros((4, 7))
        H[0, 2] = 1.0  # vx
        H[1, 3] = 1.0  # vy
        H[2, 4] = 1.0  # ax
        H[3, 5] = 1.0  # ay
        
        # Calculate Kalman gain: K = P*H'*inv(H*P*H' + R)
        PHt = self.kf_covariance @ H.T
        S = H @ PHt + self.kf_measurement_noise
        K = PHt @ np.linalg.inv(S)
        
        # Update state: x = x + K*(z - H*x)
        measurement_residual = z - H @ self.kf_state
        self.kf_state += K @ measurement_residual
        
        # Update covariance: P = (I - K*H)*P
        I = np.eye(7)
        self.kf_covariance = (I - K @ H) @ self.kf_covariance
        
        # Update derived values
        self.current_speed = math.sqrt(self.kf_state[2]**2 + self.kf_state[3]**2)
        self.current_heading = self.kf_state[6]
        
    def _update_kalman_with_gps(self, gps_data):
        """Update Kalman filter with GPS measurements."""
        if not self.kalman_initialized:
            if gps_data.get('latitude') is not None and gps_data.get('longitude') is not None:
                position = (gps_data.get('latitude'), gps_data.get('longitude'))
                heading = gps_data.get('heading')
                self._initialize_kalman_filter(position, heading)
            return
        
        # If we have GPS speed and heading, create measurement vector
        if gps_data.get('speed') is not None:
            speed = gps_data.get('speed')
            heading = gps_data.get('heading', self.current_heading)
            heading_rad = math.radians(heading)
            
            # Convert speed and heading to velocity components
            vx = speed * math.cos(heading_rad)
            vy = speed * math.sin(heading_rad)
            
            # Create measurement vector: [vx, vy]
            z = np.array([vx, vy])
            
            # Create measurement matrix H (maps states to measurements)
            H = np.zeros((2, 7))
            H[0, 2] = 1.0  # vx
            H[1, 3] = 1.0  # vy
            
            # Measurement noise for GPS
            R = np.eye(2) * 0.5  # GPS velocity uncertainty
            
            # Calculate Kalman gain: K = P*H'*inv(H*P*H' + R)
            PHt = self.kf_covariance @ H.T
            S = H @ PHt + R
            K = PHt @ np.linalg.inv(S)
            
            # Update state: x = x + K*(z - H*x)
            measurement_residual = z - H @ self.kf_state
            self.kf_state += K @ measurement_residual
            
            # Update covariance: P = (I - K*H)*P
            I = np.eye(7)
            self.kf_covariance = (I - K @ H) @ self.kf_covariance
            
            # Direct update of heading if provided
            if gps_data.get('heading') is not None:
                self.kf_state[6] = gps_data.get('heading')
        
        # If we have GPS position, update position state directly
        # For a more sophisticated approach, we'd also update the Kalman filter
        if gps_data.get('latitude') is not None and gps_data.get('longitude') is not None:
            # For simplicity, we're just resetting our local position to 0,0
            # In a real implementation, we'd convert GPS coordinates to local x,y
            self.kf_state[0:2] = 0.0
            self.last_position = (gps_data.get('latitude'), gps_data.get('longitude'))
            self.imu_position = self.last_position
        
        # Update derived values
        self.current_speed = math.sqrt(self.kf_state[2]**2 + self.kf_state[3]**2)
        self.current_heading = self.kf_state[6]

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
                    
                    # Explicitly set initial state to stationary
                    self.is_stationary = True
                    self.current_speed = 0.0
                    self.consecutive_stationary_samples = 20  # Initialize with enough samples to be considered stationary
                    
                    return True
                self.logger.warning(f"Failed to initialize IMU at address 0x{addr:02x}")

            self.initialization_attempts += 1
            time.sleep(0.1)

        self.logger.error("IMU initialization failed after maximum attempts")
        return False

    def get_temperature(self):
        """Reads and returns the current temperature from the IMU in Celsius."""
        current_time = time.time()
        # Perform address check/switch if necessary (similar to read_data)
        if current_time - self.last_address_check >= self.address_check_interval:
            if not self._verify_address():
                if not self._switch_to_valid_address():
                    self.logger.error("Cannot read IMU temperature: no valid IMU address found or configured.")
                    return None
            self.last_address_check = current_time

        if not self.address:
            self.logger.error("Cannot read IMU temperature: IMU address not set.")
            return None
        
        try:
            # Read temperature registers (TEMP_OUT_H and TEMP_OUT_L)
            # These are at 0x41 and 0x42
            temp_h = self.bus.read_byte_data(self.address, self.REG_TEMP_OUT_H)
            temp_l = self.bus.read_byte_data(self.address, self.REG_TEMP_OUT_L)
            raw_temp = (temp_h << 8) | temp_l
            
            # Convert to signed 16-bit value
            signed_raw_temp = self._to_signed_int16(raw_temp)
            
            # Convert to Celsius using the formula from datasheet/existing code
            # Temperature in Degrees Centigrade = (TEMP_OUT / TEMP_SENSITIVITY) + TEMP_OFFSET
            temperature_celsius = signed_raw_temp / self.TEMP_SENSITIVITY + self.TEMP_OFFSET
            
            return temperature_celsius
        except Exception as e:
            self.logger.error(f"Failed to read temperature from IMU address 0x{self.address:02x}: {e}")
            # Attempt to switch address if read fails, then retry once.
            if self._switch_to_valid_address():
                self.logger.info(f"Retrying temperature read on new address 0x{self.address:02x}")
                try:
                    temp_h = self.bus.read_byte_data(self.address, self.REG_TEMP_OUT_H)
                    temp_l = self.bus.read_byte_data(self.address, self.REG_TEMP_OUT_L)
                    raw_temp = (temp_h << 8) | temp_l
                    signed_raw_temp = self._to_signed_int16(raw_temp)
                    temperature_celsius = signed_raw_temp / self.TEMP_SENSITIVITY + self.TEMP_OFFSET
                    return temperature_celsius
                except Exception as e2:
                    self.logger.error(f"Failed to read temperature even after address switch to 0x{self.address:02x}: {e2}")
                    return None
            return None
