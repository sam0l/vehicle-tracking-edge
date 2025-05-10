import logging
from src.imu import IMU
import time
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imu():
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    imu = IMU(config['imu']['i2c_bus'], i2c_address=["0x68", "0x69"])
    if not imu.initialize():
        print("Failed to initialize IMU")
        return
    try:
        for _ in range(20):
            data = imu.read_data()
            if data:
                print(f"IMU Data: {data}")
                logger.debug(f"Raw IMU Data: {data}")
            else:
                print("No IMU data")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Test interrupted")
    finally:
        imu.close()

if __name__ == "__main__":
    test_imu()
