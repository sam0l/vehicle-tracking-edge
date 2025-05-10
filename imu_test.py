import logging
from src.imu import IMU
import time
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_imu():
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    imu = IMU(config['imu']['bus'], config['imu']['address'])
    if not imu.start():
        print("Failed to initialize IMU")
        return
    try:
        for _ in range(20):
            data = imu.read()
            if data:
                print(f"IMU Data: {data}")
                logger.debug(f"Raw IMU Data: {data}")
            else:
                print("No IMU data")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("Test interrupted")
    finally:
        imu.stop()

if __name__ == "__main__":
    test_imu()
