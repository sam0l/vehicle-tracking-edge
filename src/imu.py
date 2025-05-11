import smbus2
import time
import logging

class IMU:
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

    def read_data(self):
        """Read data from the IMU, handling address changes if needed."""
        current_time = time.time()
        
        # Periodically check if we need to verify the address
        if current_time - self.last_address_check >= self.address_check_interval:
            if not self._verify_address():
                if not self._switch_to_valid_address():
                    self.logger.error("Cannot read IMU data: no valid address")
                    return None
            self.last_address_check = current_time

        try:
            # Read 14 bytes (accel x,y,z + temp + gyro x,y,z)
            data = self.bus.read_i2c_block_data(self.address, self.REG_ACCEL_XOUT_H, 14)

            # Convert to signed 16-bit
            def to_signed(val):
                return val - 65536 if val > 32767 else val

            accel_x = to_signed((data[0] << 8) | data[1]) * self.accel_scale
            accel_y = to_signed((data[2] << 8) | data[3]) * self.accel_scale
            accel_z = to_signed((data[4] << 8) | data[5]) * self.accel_scale
            gyro_x = to_signed((data[8] << 8) | data[9]) * self.gyro_scale
            gyro_y = to_signed((data[10] << 8) | data[11]) * self.gyro_scale
            gyro_z = to_signed((data[12] << 8) | data[13]) * self.gyro_scale

            return {
                "accel_x": accel_x,  # g
                "accel_y": accel_y,
                "accel_z": accel_z,
                "gyro_x": gyro_x,    # deg/s
                "gyro_y": gyro_y,
                "gyro_z": gyro_z,
            }
        except Exception as e:
            self.logger.error(f"Error reading IMU data at address 0x{self.address:02x}: {e}")
            # Try to recover by switching address
            if self._switch_to_valid_address():
                return self.read_data()  # Retry reading after address switch
            return None

    def close(self):
        """Close the I2C bus connection."""
        if self.bus:
            self.bus.close()
            self.logger.info(f"IMU I2C bus closed for address 0x{self.address:02x}")
            self.bus = None
            self.address = None
