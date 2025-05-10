import yaml
import logging
import time
from src.imu import IMU

# Configure logging to match project setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('vehicle_tracker.log'),
        logging.StreamHandler()
    ]
)

def test_imu():
    logger = logging.getLogger(__name__)
    
    # Load configuration
    try:
        with open("config/config.yaml", "r") as f:
            config = yaml.safe_load(f)
        imu_config = config["imu"]
        i2c_bus = imu_config["i2c_bus"]
        logger.info(f"Loaded IMU config: bus={i2c_bus}, trying addresses [0x68, 0x69]")
    except Exception as e:
        logger.error(f"Failed to load config.yaml: {e}")
        return

    # Initialize IMU with both possible addresses
    imu = None
    try:
        imu = IMU(i2c_bus, i2c_address=["0x68", "0x69"])
        if not imu.initialize():
            logger.error("IMU initialization failed at all addresses")
            return
        logger.info(f"IMU initialized successfully at address 0x{imu.address:02x}")
    except Exception as e:
        logger.error(f"Failed to initialize IMU: {e}")
        return

    # Test data reading for 30 seconds
    start_time = time.time()
    test_duration = 30  # seconds
    sample_count = 0
    errors = 0

    logger.info(f"Starting IMU data test for {test_duration} seconds...")
    try:
        while time.time() - start_time < test_duration:
            data = imu.read_data()
            if data is None:
                logger.error("Failed to read IMU data")
                errors += 1
                time.sleep(0.1)
                continue

            # Validate data ranges (approximate, based on ±16g and ±2000 dps)
            accel_valid = all(-20 < data[f"accel_{axis}"] < 20 for axis in ['x', 'y', 'z'])
            gyro_valid = all(-2200 < data[f"gyro_{axis}"] < 2200 for axis in ['x', 'y', 'z'])
            
            if not (accel_valid and gyro_valid):
                logger.warning(f"Data out of expected range: {data}")
                errors += 1
            else:
                logger.debug(f"IMU Data: accel_x={data['accel_x']:.3f}g, "
                            f"accel_y={data['accel_y']:.3f}g, "
                            f"accel_z={data['accel_z']:.3f}g, "
                            f"gyro_x={data['gyro_x']:.3f}°/s, "
                            f"gyro_y={data['gyro_y']:.3f}°/s, "
                            f"gyro_z={data['gyro_z']:.3f}°/s")
            
            sample_count += 1
            time.sleep(0.1)  # ~10Hz sampling

    except KeyboardInterrupt:
        logger.info("Test stopped by user")
    except Exception as e:
        logger.error(f"Error during IMU test: {e}")
        errors += 1
    finally:
        if imu:
            imu.close()
            logger.info("IMU I2C bus closed")

    # Summarize results
    logger.info(f"Test completed: {sample_count} samples collected, {errors} errors")
    if errors == 0 and sample_count > 0:
        logger.info("IMU test passed successfully")
    else:
        logger.error("IMU test failed due to errors or insufficient samples")

if __name__ == "__main__":
    test_imu()
