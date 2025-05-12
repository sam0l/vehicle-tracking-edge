#!/usr/bin/env python3
"""
Unified IMU Test Script

This script provides comprehensive testing of the IMU module with the following features:
- Basic functionality testing
- Calibration routines
- Simulated GPS data testing
- Dead reckoning evaluation
- GPS outage resilience testing

Usage:
python3 tests/unified/test_imu.py [--quick] [--calibrate] [--simulate] [--outage]
"""

import sys
import os
import time
import math
import argparse
import logging
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import yaml

# Add the parent directory to the path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.imu import IMU

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("unified_imu_test")

class IMUTester:
    """Unified IMU test class with comprehensive test capabilities."""
    
    def __init__(self, config_path='config/config.yaml'):
        """Initialize tester with configuration."""
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                logger.info(f"Loaded config: IMU bus={self.config['imu']['i2c_bus']}, "
                        f"addresses={self.config['imu']['i2c_addresses']}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            logger.info("Using default IMU settings")
            self.config = {
                'imu': {
                    'i2c_bus': 4,
                    'i2c_addresses': ["0x68", "0x69"],
                    'sample_rate': 100,
                    'accel_range': 2,
                    'gyro_range': 250
                }
            }
            
        # Create IMU instance
        self.imu = IMU(
            self.config['imu']['i2c_bus'],
            i2c_addresses=self.config['imu']['i2c_addresses'],
            sample_rate=self.config['imu']['sample_rate'],
            accel_range=self.config['imu']['accel_range'],
            gyro_range=self.config['imu']['gyro_range']
        )
        
        # Test data storage
        self.timestamps = []
        self.imu_readings = []
        self.gps_readings = []
        self.raw_speeds = []
        self.filtered_speeds = []
        self.positions = []
        self.headings = []
        
        # Create results directory
        self.results_dir = Path('test_results')
        self.results_dir.mkdir(exist_ok=True)
    
    def initialize(self):
        """Initialize the IMU."""
        logger.info("Initializing IMU...")
        result = self.imu.initialize()
        if result:
            logger.info(f"IMU initialized successfully at address 0x{self.imu.address:02x}")
        else:
            logger.error("IMU initialization failed")
        return result
    
    def quick_test(self, duration=5):
        """Run a quick test of IMU functionality."""
        logger.info(f"Running quick test for {duration} seconds...")
        
        if not self.initialize():
            return False
            
        start_time = time.time()
        sample_count = 0
        errors = 0
        
        try:
            while time.time() - start_time < duration:
                data = self.imu.read_data()
                if data is None:
                    logger.error("Failed to read IMU data")
                    errors += 1
                    time.sleep(0.1)
                    continue
                
                # Format all the important data in a readable way
                logger.info(
                    f"Accel: ({data['accel_x']:.4f}, {data['accel_y']:.4f}, {data['accel_z']:.4f})g | "
                    f"Gyro: ({data['gyro_x']:.2f}, {data['gyro_y']:.2f}, {data['gyro_z']:.2f})°/s | "
                    f"Temp: {data.get('temp', 0):.1f}°C | "
                    f"Speed: {data['speed']:.2f}m/s | "
                    f"Stationary: {data['is_stationary']} | "
                    f"Heading: {data.get('heading', 0):.1f}°"
                )
                
                sample_count += 1
                time.sleep(0.5)  # 2Hz sampling for readability
                
            logger.info(f"Quick test completed: {sample_count} samples collected, {errors} errors")
            return errors == 0 and sample_count > 0
            
        except Exception as e:
            logger.error(f"Error during quick test: {e}")
            return False
        finally:
            logger.info("Quick test complete")
    
    def calibration_test(self):
        """Test calibration functionality."""
        logger.info("Starting calibration test...")
        
        if not self.initialize():
            return False
            
        try:
            # Test stationary calibration
            logger.info("\nPerforming calibration...")
            logger.info("Keep the device still during this process")
            
            self.imu.calibrate_stationary()
            
            # Get the calibration values from the IMU
            accel_bias = self.imu.accel_bias
            gravity_norm = self.imu.gravity_norm
            motion_threshold = self.imu.motion_threshold
            
            logger.info("\nCalibration Results:")
            logger.info(f"Accel Bias (x,y,z): ({accel_bias[0]:.6f}, {accel_bias[1]:.6f}, {accel_bias[2]:.6f})g")
            logger.info(f"Gravity Norm: {gravity_norm:.6f}g (should be close to 1.0)")
            logger.info(f"Motion Threshold: {motion_threshold:.6f}g")
            logger.info(f"Stationary Threshold: {self.imu.stationary_threshold:.6f}g")
            
            # Test calibrated readings
            logger.info("\nReading calibrated data...")
            for i in range(5):
                data = self.imu.read_data()
                if data:
                    logger.info(
                        f"Calibrated Accel: ({data['accel_x']:.4f}, {data['accel_y']:.4f}, {data['accel_z']:.4f})g | "
                        f"Speed: {data['speed']:.2f}m/s | "
                        f"Stationary: {data['is_stationary']}"
                    )
                else:
                    logger.warning("No data received")
                time.sleep(0.5)
                
            logger.info("Calibration test completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error during calibration test: {e}")
            return False
    
    def simulate_gps_reading(self, time_elapsed, speed=10.0, heading=90.0, initial_pos=(37.7749, -122.4194)):
        """
        Simulate GPS readings with a constant speed vehicle moving in a straight line.
        Returns a simulated GPS data dict.
        """
        # Calculate new position based on speed, heading and time
        # 1 degree latitude ~= 111,320 meters
        # 1 degree longitude ~= 111,320 * cos(latitude) meters
        lat, lon = initial_pos
        
        # Convert heading to radians (0=North, 90=East)
        heading_rad = math.radians(heading)
        
        # Calculate distance moved in meters
        distance = speed * time_elapsed
        
        # Calculate new position
        lat_change = (distance * math.cos(heading_rad)) / 111320.0
        lon_change = (distance * math.sin(heading_rad)) / (111320.0 * math.cos(math.radians(lat)))
        
        new_lat = lat + lat_change
        new_lon = lon + lon_change
        
        # Simulate GPS noise
        noise_lat = (np.random.random() - 0.5) * 0.00001  # ~1 meter of noise
        noise_lon = (np.random.random() - 0.5) * 0.00001
        noise_speed = (np.random.random() - 0.5) * 0.5  # ±0.25 m/s noise
        
        # Create simulated GPS data
        gps_data = {
            'latitude': new_lat + noise_lat,
            'longitude': new_lon + noise_lon,
            'speed': speed + noise_speed,
            'heading': heading,
            'satellites': 8,
            'altitude': 100.0,
            'timestamp': time.time()
        }
        
        return gps_data
    
    def simulation_test(self, duration=20, scenario="constant_straight"):
        """
        Test IMU with different simulated GPS scenarios.
        
        Scenarios:
        - constant_straight: Constant speed in straight line
        - accelerating: Accelerating in straight line
        - turning: Constant speed while turning
        - variable_circle: Variable speed in a circle
        """
        logger.info(f"Running simulation test '{scenario}' for {duration} seconds...")
        
        if not self.initialize():
            return False
            
        # Clear previous data
        self.timestamps = []
        self.imu_readings = []
        self.gps_readings = []
        self.raw_speeds = []
        self.filtered_speeds = []
        self.positions = []
        self.headings = []
        
        # Set scenario parameters
        if scenario == "constant_straight":
            speed_profile = "constant"
            turning_profile = "straight"
        elif scenario == "accelerating":
            speed_profile = "accelerating"
            turning_profile = "straight"
        elif scenario == "turning":
            speed_profile = "constant"
            turning_profile = "turning"
        elif scenario == "variable_circle":
            speed_profile = "variable"
            turning_profile = "circle"
        else:
            logger.error(f"Unknown scenario: {scenario}")
            return False
            
        # Initial values
        start_time = time.time()
        last_gps_update = 0
        gps_update_interval = 1.0  # 1 second between GPS updates
        initial_pos = (37.7749, -122.4194)  # San Francisco coordinates
        initial_heading = 90.0  # East
        current_speed = 10.0  # m/s
        current_heading = initial_heading
        
        try:
            # Run the test for the specified duration
            while time.time() - start_time < duration:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Determine current speed based on profile
                if speed_profile == "constant":
                    current_speed = 10.0
                elif speed_profile == "accelerating":
                    current_speed = 5.0 + (20.0 * elapsed / duration)  # 5-25 m/s
                elif speed_profile == "variable":
                    # Sine wave between 5-15 m/s with 10s period
                    current_speed = 10.0 + 5.0 * math.sin(2 * math.pi * elapsed / 10.0)
                
                # Determine current heading based on profile
                if turning_profile == "straight":
                    current_heading = initial_heading
                elif turning_profile == "turning":
                    # Gradually turn from 90° to 180° over the duration
                    current_heading = initial_heading + (90.0 * elapsed / duration)
                elif turning_profile == "circle":
                    # Complete one circle (360°) every 20 seconds
                    current_heading = initial_heading + (360.0 * elapsed / 20.0) % 360.0
                
                # Simulate periodic GPS updates
                if elapsed - last_gps_update >= gps_update_interval:
                    gps_data = self.simulate_gps_reading(
                        elapsed, speed=current_speed, heading=current_heading, initial_pos=initial_pos
                    )
                    self.imu.update_gps(gps_data)
                    self.gps_readings.append(gps_data)
                    last_gps_update = elapsed
                    logger.info(f"GPS Update: pos=({gps_data['latitude']:.6f}, {gps_data['longitude']:.6f}), " +
                            f"speed={gps_data['speed']:.2f}m/s, heading={gps_data['heading']:.1f}°")
                
                # Read IMU data continuously
                try:
                    data = self.imu.read_data()
                    if data:
                        # Record data for analysis
                        self.timestamps.append(elapsed)
                        self.imu_readings.append(data)
                        
                        # Extract speed and position for analysis
                        raw_speed = data['speed']
                        self.raw_speeds.append(raw_speed)
                        self.filtered_speeds.append(raw_speed)
                        
                        position = data.get('position')
                        if position:
                            self.positions.append(position)
                        
                        heading = data.get('heading', 0)
                        self.headings.append(heading)
                        
                        # Log every second
                        if int(elapsed) > int(elapsed - 0.1):
                            logger.info(f"IMU Data: speed={raw_speed:.2f}m/s, heading={heading:.1f}°, " +
                                    f"stationary={data['is_stationary']}")
                    else:
                        logger.warning("No IMU data received")
                except Exception as e:
                    logger.error(f"Error reading IMU data: {e}")
                
                # Add a small delay to avoid high CPU usage
                time.sleep(0.1)
            
            logger.info(f"Simulation test '{scenario}' completed")
            
            # Generate analysis of the test results
            self.analyze_results(scenario)
            return True
            
        except Exception as e:
            logger.error(f"Error during simulation test: {e}")
            return False
    
    def gps_outage_test(self, duration=60, outage_start=15, outage_duration=30):
        """
        Test IMU dead reckoning during a GPS outage.
        
        Parameters:
        - duration: test duration in seconds
        - outage_start: when the GPS outage starts (seconds)
        - outage_duration: how long the GPS outage lasts (seconds)
        """
        logger.info(f"Testing GPS outage scenario for {duration} seconds...")
        logger.info(f"GPS updates every 1s with outage from {outage_start}s to {outage_start+outage_duration}s")
        
        if not self.initialize():
            return False
            
        # Clear previous data
        self.timestamps = []
        self.imu_readings = []
        self.gps_readings = []
        self.raw_speeds = []
        self.filtered_speeds = []
        self.positions = []
        self.headings = []
        self.gps_available = []  # Track GPS availability
        
        # Initial values
        start_time = time.time()
        last_gps_update = 0
        gps_update_interval = 1.0  # 1 second between GPS updates
        initial_pos = (37.7749, -122.4194)  # San Francisco coordinates
        initial_heading = 90.0  # East
        current_speed = 10.0  # m/s
        
        try:
            # Run the test for the specified duration
            while time.time() - start_time < duration:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Check if we're in GPS outage period
                in_outage = outage_start <= elapsed < (outage_start + outage_duration)
                self.gps_available.append(not in_outage)
                
                # Simulate periodic GPS updates (if not in outage)
                if not in_outage and elapsed - last_gps_update >= gps_update_interval:
                    gps_data = self.simulate_gps_reading(
                        elapsed, speed=current_speed, heading=initial_heading, initial_pos=initial_pos
                    )
                    self.imu.update_gps(gps_data)
                    self.gps_readings.append((elapsed, gps_data))
                    last_gps_update = elapsed
                    logger.info(f"GPS Update: pos=({gps_data['latitude']:.6f}, {gps_data['longitude']:.6f}), " +
                            f"speed={gps_data['speed']:.2f}m/s, heading={gps_data['heading']:.1f}°")
                
                # If in outage, log it
                if in_outage and int(elapsed) > int(elapsed - 0.1):
                    logger.info(f"GPS OUTAGE - {int(outage_start + outage_duration - elapsed)}s remaining")
                
                # Read IMU data continuously
                try:
                    data = self.imu.read_data()
                    if data:
                        # Record data for analysis
                        self.timestamps.append(elapsed)
                        self.imu_readings.append(data)
                        self.raw_speeds.append(data['speed'])
                        self.filtered_speeds.append(data['speed'])
                        
                        position = data.get('position')
                        if position:
                            self.positions.append((elapsed, position))
                        
                        heading = data.get('heading', 0)
                        self.headings.append(heading)
                        
                        # Log every second
                        if int(elapsed) > int(elapsed - 0.1):
                            pos_str = f"({position[0]:.6f}, {position[1]:.6f})" if position else "None"
                            logger.info(f"IMU Data: pos={pos_str}, speed={data['speed']:.2f}m/s, " +
                                    f"heading={heading:.1f}°, stationary={data['is_stationary']}")
                    else:
                        logger.warning("No IMU data received")
                except Exception as e:
                    logger.error(f"Error reading IMU data: {e}")
                
                # Add a small delay to avoid high CPU usage
                time.sleep(0.1)
            
            logger.info("GPS outage test completed")
            
            # Generate analysis of the test results
            self.analyze_results("gps_outage")
            return True
            
        except Exception as e:
            logger.error(f"Error during GPS outage test: {e}")
            return False
    
    def analyze_results(self, test_name):
        """Analyze and plot test results."""
        if not self.timestamps:
            logger.error("No data to analyze")
            return
            
        # Convert lists to numpy arrays for easier analysis
        timestamps = np.array(self.timestamps)
        
        # Extract speed data
        raw_speeds = np.array(self.raw_speeds)
        filtered_speeds = np.array(self.filtered_speeds)
        
        # Check if we have position data
        have_position_data = len(self.positions) > 0
        
        # Create plots
        plt.figure(figsize=(12, 8))
        
        # Plot speeds
        plt.subplot(2, 1, 1)
        plt.plot(timestamps, raw_speeds, 'b-', label='IMU Speed')
        
        # Add GPS speed points if available
        if self.gps_readings:
            if isinstance(self.gps_readings[0], tuple):
                # Format is (timestamp, gps_data)
                gps_times = [gps[0] for gps in self.gps_readings]
                gps_speeds = [gps[1]['speed'] for gps in self.gps_readings]
            else:
                # Format is just gps_data dict
                gps_times = [timestamps[i] for i in range(len(timestamps)) 
                            if i % int(1/0.1) == 0 and i < len(self.gps_readings)]
                gps_speeds = [gps['speed'] for gps in self.gps_readings[:len(gps_times)]]
            
            plt.plot(gps_times, gps_speeds, 'ro', label='GPS Speed')
            
        plt.xlabel('Time (s)')
        plt.ylabel('Speed (m/s)')
        plt.title(f'IMU Speed vs. Time - {test_name}')
        plt.legend()
        plt.grid(True)
        
        # Plot positions if available
        if have_position_data:
            plt.subplot(2, 1, 2)
            
            # For trajectory visualization
            if isinstance(self.positions[0], tuple):
                # Format is (timestamp, (lat, lon))
                position_times = [pos[0] for pos in self.positions]
                lats = [pos[1][0] for pos in self.positions]
                lons = [pos[1][1] for pos in self.positions]
            else:
                # Format is just (lat, lon)
                lats = [pos[0] for pos in self.positions]
                lons = [pos[1] for pos in self.positions]
                
            plt.plot(lons, lats, 'b-', label='IMU Trajectory')
            
            # Add GPS position points if available
            if self.gps_readings:
                if isinstance(self.gps_readings[0], tuple):
                    # Format is (timestamp, gps_data)
                    gps_lats = [gps[1]['latitude'] for gps in self.gps_readings]
                    gps_lons = [gps[1]['longitude'] for gps in self.gps_readings]
                else:
                    # Format is just gps_data dict
                    gps_lats = [gps['latitude'] for gps in self.gps_readings]
                    gps_lons = [gps['longitude'] for gps in self.gps_readings]
                
                plt.plot(gps_lons, gps_lats, 'ro', label='GPS Position')
            
            plt.xlabel('Longitude')
            plt.ylabel('Latitude')
            plt.title(f'IMU Trajectory - {test_name}')
            plt.legend()
            plt.grid(True)
        else:
            # If no position data, plot heading instead
            plt.subplot(2, 1, 2)
            headings = np.array(self.headings)
            plt.plot(timestamps, headings, 'g-', label='IMU Heading')
            plt.xlabel('Time (s)')
            plt.ylabel('Heading (degrees)')
            plt.title(f'IMU Heading vs. Time - {test_name}')
            plt.legend()
            plt.grid(True)
        
        # Adjust layout and save figure
        plt.tight_layout()
        plt.savefig(os.path.join(self.results_dir, f'imu_test_{test_name}.png'))
        logger.info(f"Plot saved to {os.path.join(self.results_dir, f'imu_test_{test_name}.png')}")
        
        # Output some statistics
        logger.info(f"Statistics for {test_name}:")
        logger.info(f"Average speed: {np.mean(filtered_speeds):.2f} m/s")
        logger.info(f"Speed std dev: {np.std(filtered_speeds):.2f} m/s")
        logger.info(f"Max speed: {np.max(filtered_speeds):.2f} m/s")
        logger.info(f"Min speed: {np.min(filtered_speeds):.2f} m/s")
    
    def run_all_tests(self):
        """Run a complete set of tests on the IMU."""
        if not self.initialize():
            logger.error("IMU initialization failed, cannot run tests.")
            return False
        
        try:
            # 1. Quick test of functionality
            if not self.quick_test(duration=5):
                logger.error("Quick test failed, aborting further tests")
                return False
                
            # 2. Calibration test
            if not self.calibration_test():
                logger.error("Calibration test failed, aborting further tests")
                return False
                
            # 3. Simulation tests with different scenarios
            scenarios = [
                "constant_straight",
                "accelerating",
                "turning",
                "variable_circle"
            ]
            for scenario in scenarios:
                if not self.simulation_test(duration=20, scenario=scenario):
                    logger.error(f"Simulation test '{scenario}' failed")
                    # Continue with other tests
            
            # 4. GPS outage test
            if not self.gps_outage_test(duration=60, outage_start=15, outage_duration=30):
                logger.error("GPS outage test failed")
                # Continue with other tests
                
            logger.info("All tests completed")
            return True
            
        except KeyboardInterrupt:
            logger.info("Tests interrupted by user")
            return False
        except Exception as e:
            logger.error(f"Error during testing: {e}")
            return False
        finally:
            # Clean up IMU resources
            self.imu.close()
            logger.info("IMU resources cleaned up")

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Unified IMU Testing Framework")
    parser.add_argument("--quick", action="store_true", help="Run quick functionality test only")
    parser.add_argument("--calibrate", action="store_true", help="Run calibration test only")
    parser.add_argument("--simulate", action="store_true", help="Run simulation tests only")
    parser.add_argument("--outage", action="store_true", help="Run GPS outage test only")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    return parser.parse_args()

def main():
    """Main function to run IMU tests."""
    args = parse_args()
    
    logger.info("Starting unified IMU tests...")
    
    # Create tester instance
    tester = IMUTester()
    
    # Check if any specific test was requested
    if args.quick:
        tester.quick_test(duration=10)
    elif args.calibrate:
        tester.calibration_test()
    elif args.simulate:
        for scenario in ["constant_straight", "accelerating", "turning", "variable_circle"]:
            tester.simulation_test(duration=20, scenario=scenario)
    elif args.outage:
        tester.gps_outage_test(duration=60, outage_start=15, outage_duration=30)
    else:
        # Run all tests by default
        tester.run_all_tests()
    
    logger.info("IMU testing complete")

if __name__ == "__main__":
    main() 