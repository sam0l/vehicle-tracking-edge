#!/usr/bin/env python3
"""
Quick IMU Test Script

This script provides a simple test of IMU functionality
to verify the device is working properly with the updated IMU class.

Usage:
python3 quick_imu_test.py
"""

import sys
import os
import time
import logging
import yaml
import math

# Add the parent directory to sys.path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.imu import IMU

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("quick_imu_test")

def main():
    """Main function to quickly test IMU functionality."""
    # Load configuration
    try:
        with open('config/config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        logger.info(f"Loaded config: IMU bus={config['imu']['i2c_bus']}, "
                   f"addresses={config['imu']['i2c_addresses']}")
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        logger.info("Using default IMU settings")
        config = {
            'imu': {
                'i2c_bus': 4,
                'i2c_addresses': ["0x68", "0x69"],
                'sample_rate': 100,
                'accel_range': 2,
                'gyro_range': 250
            }
        }

    # Initialize IMU
    try:
        imu = IMU(
            i2c_bus=config['imu']['i2c_bus'],
            i2c_addresses=config['imu']['i2c_addresses'],
            sample_rate=config['imu']['sample_rate'],
            accel_range=config['imu']['accel_range'],
            gyro_range=config['imu']['gyro_range']
        )
        
        logger.info("Initializing IMU...")
        if not imu.initialize():
            logger.error("IMU initialization failed!")
            return 1
            
        logger.info(f"IMU initialized successfully at address 0x{imu.address:02x}")
        
        # Test basic reading
        logger.info("Reading data for 2 seconds...")
        for i in range(10):
            data = imu.read_data()
            if data:
                # Format all the important data in a readable way
                logger.info(
                    f"Accel: ({data['accel_x']:.4f}, {data['accel_y']:.4f}, {data['accel_z']:.4f})g | "
                    f"Gyro: ({data['gyro_x']:.2f}, {data['gyro_y']:.2f}, {data['gyro_z']:.2f})°/s | "
                    f"Temp: {data.get('temp', 0):.1f}°C | "
                    f"Speed: {data['speed']:.2f}m/s | "
                    f"Stationary: {data['is_stationary']} | "
                    f"Heading: {data.get('heading', 0):.1f}°"
                )
            else:
                logger.warning("No data received")
            time.sleep(0.2)
            
        # Test calibration
        logger.info("\nPerforming calibration...")
        logger.info("Keep the device still during this process")
        imu.calibrate_stationary()
        
        # Test with simulated GPS data
        logger.info("\nTesting with simulated GPS data...")
        
        # Simulate a GPS reading at current position
        lat, lon = 37.7749, -122.4194  # San Francisco coordinates
        gps_data = {
            'latitude': lat,
            'longitude': lon,
            'speed': 5.0,  # 5 m/s, about 18 km/h
            'heading': 90.0,  # East
            'satellites': 8,
            'timestamp': time.time()
        }
        
        # Update IMU with GPS data
        logger.info(f"Sending GPS data: position=({lat:.6f}, {lon:.6f}), speed={gps_data['speed']}m/s")
        imu.update_gps(gps_data)
        
        # Read data after GPS update
        logger.info("Reading data after GPS update...")
        for i in range(10):
            data = imu.read_data()
            if data:
                # Format all the important data in a readable way
                if data.get('position'):
                    pos_str = f"({data['position'][0]:.6f}, {data['position'][1]:.6f})"
                else:
                    pos_str = "None"
                    
                logger.info(
                    f"Position: {pos_str} | "
                    f"Speed: {data['speed']:.2f}m/s | "
                    f"Heading: {data.get('heading', 0):.1f}° | "
                    f"Stationary: {data['is_stationary']}"
                )
            else:
                logger.warning("No data received")
            time.sleep(0.2)
            
        # Test simulated movement (no GPS)
        logger.info("\nSimulating no GPS for 2 seconds...")
        start_time = time.time()
        while time.time() - start_time < 2:
            data = imu.read_data()
            if data:
                if data.get('position'):
                    pos_str = f"({data['position'][0]:.6f}, {data['position'][1]:.6f})"
                else:
                    pos_str = "None"
                    
                logger.info(
                    f"Position: {pos_str} | "
                    f"Speed: {data['speed']:.2f}m/s | "
                    f"Heading: {data.get('heading', 0):.1f}° | "
                    f"Stationary: {data['is_stationary']}"
                )
            else:
                logger.warning("No data received")
            time.sleep(0.2)
            
        logger.info("Test completed successfully!")
        imu.close()
        return 0
        
    except Exception as e:
        logger.error(f"Error during IMU test: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 