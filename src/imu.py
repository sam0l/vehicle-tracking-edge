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

    def __init__(self, i2c_bus, i2c_address=["0x68", "0x69"]):
        self.logger = logging.getLogger(__name__)
        self.bus = None
        self.address = None
        try:
            self.bus = smbus2.SMBus(i2c_bus)
            # Convert address(es) to int if provided as hex strings
            self.addresses = [
                int(addr, 16) if isinstance(addr, str) else addr
                for addr in (i2c_address if isinstance(i2c_address, list) else [i2c_address])
            ]
            self.accel_scale = 16.0 / 32768.0  # ±16g, 16-bit (2048 LSB/g)
            self.gyro_scale = 2000.0 / 32768.0  # ±2000dps, 16-bit (16.4 LSB/(°/s))
        except Exception as e:
            self.logger.error(f"Failed to open I2C bus {i2c_bus}: {e}")
            raise

    def _check_and_switch_address(self):
        """Check if the current address is valid, switch to another if needed."""
        try:
            # Verify current address by reading WHO_AM_I
            device_id = self.bus.read_byte_data(self.address, self.REG_WHO_AM_I)
            if device_id == 0x98:
                self.logger.debug(f"IMU address 0x{self.address:02x} is valid (WHO_AM_I: 0x{device_id:02x})")
                return True
            else:
                self.logger.warning(f"Invalid WHO_AM_I 0x{device_id:02x} at address 0x{self.address:02x}, expected 0x98")
        except Exception as e:
            self.logger.warning(f"Failed to read WHO_AM_I at address 0x{self.address:02x}: {e}")

        # Try other addresses
        for addr in self.addresses:
            if addr == self.address:
                continue
            try:
                device_id = self.bus.read_byte_data(addr, self.REG_WHO_AM_I)
                if device_id == 0x98:
                    self.logger.info(f"Switching IMU address from 0x{self.address:02x} to 0x{addr:02x} (WHO_AM_I: 0x{device_id:02x})")
                    self.address = addr
                    # Reinitialize IMU at new address
                    if not self._initialize_at_address():
                        self.logger.error(f"Failed to reinitialize IMU at new address 0x{addr:02x}")
                        return False
                    return True
                else:
                    self.logger.warning(f"Invalid WHO_AM_I 0x{device_id:02x} at address 0x{addr:02x}, expected 0x98")
            except Exception as e:
                self.logger.warning(f"Failed to read WHO_AM_I at address 0x{addr:02x}: {e}")
                continue

        self.logger.error("No valid IMU address found")
        return False

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

            # Configure DLPF for reasonable bandwidth (gyro: RoachHz, accel: 188Hz)
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
        try:
            for addr in self.addresses:
                self.address = addr
                try:
                    # Verify device ID
                    device_id = self.bus.read_byte_data(self.address, self.REG_WHO_AM_I)
                    if device_id != 0x98:
                        self.logger.warning(f"IMU WHO_AM_I returned 0x{device_id:02x} at address 0x{self.address:02x}, expected 0x98")
                        continue
                    self.logger.info(f"IMU device ID confirmed: 0x{device_id:02x} at address 0x{self.address:02x}")

                    # Initialize IMU at this address
                    if self._initialize_at_address():
                        return True
                except Exception as e:
                    self.logger.warning(f"Failed to initialize IMU at address 0x{self.address:02x}: {e}")
                    continue

            self.logger.error("IMU initialization failed at all addresses")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during IMU initialization: {e}")
            return False

    def read_data(self):
        try:
            # Check if current address is valid, switch if needed
            if not self._check_and_switch_address():
                self.logger.error("Cannot read IMU data: no valid address")
                return None

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
            return None

    def close(self):
        if self.bus:
            self.bus.close()
            self.logger.info(f"IMU I2C bus closed for address 0x{self.address:02x}")
            self.bus = None
            self.address = None
