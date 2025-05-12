#!/usr/bin/env python3
"""
IMU Calibration and Testing Script

This script helps debug and calibrate the IMU to ensure proper speed estimation,
particularly when the device is stationary. It will:

1. Measure and log baseline values while stationary to determine noise levels
2. Test motion detection thresholds
3. Experiment with different filter parameters
4. Output detailed debug data in real-time
5. Allow live adjustment of parameters

Usage:
python3 imu_calibration_test.py --i2c_bus 4 --accel_range 2 --gyro_range 250
"""

import sys
import os
import time
import math
import argparse
import logging
import numpy as np
import matplotlib.pyplot as plt
from collections import deque

# Add the parent directory to the path so we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.imu import IMU

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("imu_calibration")

# Constants for calibration
STATIONARY_SAMPLES = 100  # Number of samples to collect for stationary calibration
MOVING_SAMPLES = 100  # Number of samples to collect for moving calibration
CALIBRATION_DELAY = 0.01  # Delay between calibration samples (seconds)

class IMUCalibration:
    def __init__(self, args):
        self.args = args
        self.imu = None
        
        # Buffers for acceleration data
        self.accel_x_buffer = deque(maxlen=50)
        self.accel_y_buffer = deque(maxlen=50)
        self.accel_z_buffer = deque(maxlen=50)
        self.total_accel_buffer = deque(maxlen=50)
        self.speed_buffer = deque(maxlen=100)
        
        # Parameters that might need tuning
        self.motion_threshold = 0.03  # Threshold for detecting motion (g)
        self.alpha = 0.2  # Low-pass filter coefficient (0-1)
        self.speed_decay = 0.1  # Speed decay factor when no acceleration (0-1)
        self.filtered_accel = 0.0  # Filtered acceleration value
        self.current_speed = 0.0  # Current estimated speed
        
        # Experiment with different values
        self.noise_filter_window = 5  # Window size for noise filtering
        
        # Initialize IMU
        self._init_imu()
    
    def _init_imu(self):
        """Initialize the IMU with given parameters."""
        logger.info(f"Initializing IMU with bus={self.args.i2c_bus}, accel_range={self.args.accel_range}g, gyro_range={self.args.gyro_range}°/s")
        try:
            self.imu = IMU(
                i2c_bus=self.args.i2c_bus,
                i2c_addresses=["0x68", "0x69"],
                sample_rate=100,
                accel_range=self.args.accel_range,
                gyro_range=self.args.gyro_range
            )
            if not self.imu.initialize():
                logger.error("IMU initialization failed!")
                sys.exit(1)
            
            logger.info(f"IMU initialized successfully at address 0x{self.imu.address:02x}")
        except Exception as e:
            logger.error(f"Error initializing IMU: {e}")
            sys.exit(1)
    
    def calibrate_stationary(self):
        """Collect data while the device is stationary to determine baseline noise and bias."""
        logger.info("Starting stationary calibration...")
        logger.info("Keep the device completely still for accurate calibration")
        
        # Wait a moment for the device to settle
        time.sleep(1.0)
        
        # Use the built-in IMU calibration routine
        logger.info("Using IMU's built-in calibration routine...")
        try:
            # Call the IMU calibration routine
            self.imu.calibrate_stationary()
            
            # Get the calibration values from the IMU
            self.accel_bias = self.imu.accel_bias
            self.gravity_norm = self.imu.gravity_norm
            self.motion_threshold = self.imu.motion_threshold
            
            logger.info("\nCalibration Results:")
            logger.info(f"Accel Bias (x,y,z): ({self.accel_bias[0]:.6f}, {self.accel_bias[1]:.6f}, {self.accel_bias[2]:.6f})g")
            logger.info(f"Gravity Norm: {self.gravity_norm:.6f}g (should be close to 1.0)")
            logger.info(f"Motion Threshold: {self.motion_threshold:.6f}g")
            logger.info(f"Stationary Threshold: {self.imu.stationary_threshold:.6f}g")
            
            return True
        
        except Exception as e:
            logger.error(f"Error during IMU calibration: {e}")
            
            # Fallback to manual calibration
            logger.info("Falling back to manual calibration...")
            
            # Collect samples
            accel_x_samples = []
            accel_y_samples = []
            accel_z_samples = []
            accel_total_samples = []
            
            logger.info(f"Collecting {STATIONARY_SAMPLES} samples...")
            for i in range(STATIONARY_SAMPLES):
                data = self.imu.read_data()
                if data:
                    accel_x_samples.append(data["accel_x"])
                    accel_y_samples.append(data["accel_y"])
                    accel_z_samples.append(data["accel_z"])
                    
                    # Calculate the total acceleration magnitude
                    total_accel = math.sqrt(data["accel_x"]**2 + data["accel_y"]**2 + data["accel_z"]**2)
                    accel_total_samples.append(total_accel)
                    
                    if i % 10 == 0:
                        logger.info(f"Sample {i+1}/{STATIONARY_SAMPLES} - x={data['accel_x']:.4f}g, y={data['accel_y']:.4f}g, z={data['accel_z']:.4f}g, total={total_accel:.4f}g")
                    
                    time.sleep(CALIBRATION_DELAY)
                else:
                    logger.warning("Failed to read IMU data, retrying...")
                    time.sleep(0.1)
                    i -= 1  # Try again
            
            # Calculate statistics
            mean_x = np.mean(accel_x_samples)
            mean_y = np.mean(accel_y_samples)
            mean_z = np.mean(accel_z_samples)
            self.accel_bias = np.array([mean_x, mean_y, mean_z])
            self.gravity_norm = np.mean(accel_total_samples)
            accel_stdev = np.std(accel_total_samples)
            
            # Set motion threshold based on standard deviation
            self.motion_threshold = max(0.03, 3 * accel_stdev)
            
            logger.info("\nManual Calibration Results:")
            logger.info(f"Accel Bias (x,y,z): ({mean_x:.6f}, {mean_y:.6f}, {mean_z:.6f})g")
            logger.info(f"Gravity Norm: {self.gravity_norm:.6f}g (should be close to 1.0)")
            logger.info(f"Accel StdDev: {accel_stdev:.6f}g")
            logger.info(f"Motion Threshold: {self.motion_threshold:.6f}g (3σ)")
            
            return True
    
    def run_speed_test(self, duration=30):
        """Run a test of speed estimation algorithms for the specified duration."""
        logger.info(f"Running speed estimation test for {duration} seconds...")
        logger.info("Keep the device stationary to verify zero speed detection")
        
        # Set up data collection
        start_time = time.time()
        end_time = start_time + duration
        
        # Data for plotting
        timestamps = []
        raw_accels = []
        filtered_accels = []
        speeds = []
        jerk_values = []  # Rate of change of acceleration
        
        # Last values for calculating derivatives
        last_accel = 0
        last_time = start_time
        
        # Initialize for test
        self.filtered_accel = 0.0
        self.current_speed = 0.0
        
        try:
            while time.time() < end_time:
                current_time = time.time()
                elapsed = current_time - start_time
                dt = current_time - last_time
                
                # Read IMU data
                data = self.imu.read_data()
                if not data:
                    logger.warning("Failed to read IMU data, skipping sample")
                    time.sleep(0.1)
                    continue
                
                # Apply calibration correction
                accel_x = data["accel_x"] - self.accel_bias[0]
                accel_y = data["accel_y"] - self.accel_bias[1]
                accel_z = data["accel_z"] - self.accel_bias[2]
                
                # Calculate total acceleration magnitude
                total_accel = math.sqrt(accel_x**2 + accel_y**2 + accel_z**2)
                
                # Adjust for gravity (should be around 0 when stationary)
                adjusted_accel = total_accel - self.gravity_norm
                
                # Store in buffers
                self.accel_x_buffer.append(accel_x)
                self.accel_y_buffer.append(accel_y)
                self.accel_z_buffer.append(accel_z)
                self.total_accel_buffer.append(adjusted_accel)
                
                # Apply low-pass filter to reduce noise
                self.filtered_accel = self.alpha * adjusted_accel + (1 - self.alpha) * self.filtered_accel
                
                # Calculate jerk (rate of change of acceleration)
                jerk = (self.filtered_accel - last_accel) / dt if dt > 0 else 0
                last_accel = self.filtered_accel
                last_time = current_time
                
                # Determine if the device is stationary using the motion threshold
                is_stationary = abs(self.filtered_accel) < self.motion_threshold and abs(jerk) < 0.1
                
                # Update speed
                if is_stationary:
                    # More aggressive speed decay when determined to be stationary
                    self.current_speed = max(0, self.current_speed - 0.2 * dt)
                    logger.debug(f"Stationary: accelerated decay, speed={self.current_speed:.4f}m/s")
                else:
                    # Integrate acceleration to update speed
                    self.current_speed += self.filtered_accel * 9.81 * dt  # Convert g to m/s²
                    
                    # Apply normal speed decay
                    self.current_speed *= (1.0 - self.speed_decay * dt)
                    
                    # Ensure non-negative speed
                    self.current_speed = max(0, self.current_speed)
                    
                    logger.debug(f"Moving: accel={self.filtered_accel:.4f}g, speed={self.current_speed:.4f}m/s")
                
                # Store speed for display
                self.speed_buffer.append(self.current_speed)
                
                # Collect data for plotting
                timestamps.append(elapsed)
                raw_accels.append(adjusted_accel)
                filtered_accels.append(self.filtered_accel)
                speeds.append(self.current_speed)
                jerk_values.append(jerk)
                
                # Display current status every 0.5 seconds
                if int(elapsed * 2) > int((elapsed - dt) * 2):
                    # Only print once per 0.5s
                    logger.info(f"[{elapsed:.1f}s] " +
                               f"Accel={adjusted_accel:.4f}g " +
                               f"Filtered={self.filtered_accel:.4f}g " +
                               f"Jerk={jerk:.4f}g/s " +
                               f"Speed={self.current_speed:.4f}m/s " +
                               f"{'[STATIONARY]' if is_stationary else ''}")
                
                # Small delay to prevent overwhelming the CPU
                time.sleep(0.01)
            
            # Plot the results
            self._plot_results(timestamps, raw_accels, filtered_accels, speeds, jerk_values)
            
            return True
                
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return False
    
    def _plot_results(self, timestamps, raw_accels, filtered_accels, speeds, jerk_values):
        """Plot the test results."""
        plt.figure(figsize=(12, 10))
        
        # Plot acceleration
        plt.subplot(3, 1, 1)
        plt.plot(timestamps, raw_accels, 'b-', label='Raw Accel')
        plt.plot(timestamps, filtered_accels, 'r-', label='Filtered Accel')
        plt.axhline(y=self.motion_threshold, color='g', linestyle='--', label='Motion Threshold')
        plt.axhline(y=-self.motion_threshold, color='g', linestyle='--')
        plt.legend()
        plt.title('Acceleration (g)')
        plt.grid(True)
        
        # Plot speed
        plt.subplot(3, 1, 2)
        plt.plot(timestamps, speeds, 'g-', label='Speed')
        plt.legend()
        plt.title('Speed (m/s)')
        plt.grid(True)
        
        # Plot jerk
        plt.subplot(3, 1, 3)
        plt.plot(timestamps, jerk_values, 'm-', label='Jerk')
        plt.legend()
        plt.title('Jerk (g/s)')
        plt.grid(True)
        
        plt.tight_layout()
        plt.savefig('imu_calibration_results.png')
        logger.info("Results saved to imu_calibration_results.png")
        plt.show()
    
    def test_parameter_values(self):
        """Test different parameter values to find optimal settings."""
        logger.info("Testing different parameter values...")
        
        # Test different alpha values
        alphas = [0.05, 0.1, 0.2, 0.3, 0.5]
        for alpha in alphas:
            logger.info(f"Testing alpha={alpha}")
            self.alpha = alpha
            self.run_speed_test(duration=10)
        
        # Test different motion thresholds
        thresholds = [0.01, 0.02, 0.05, 0.1]
        for threshold in thresholds:
            logger.info(f"Testing motion_threshold={threshold}")
            self.motion_threshold = threshold
            self.run_speed_test(duration=10)
        
        # Test different speed decay factors
        decays = [0.05, 0.1, 0.2, 0.3]
        for decay in decays:
            logger.info(f"Testing speed_decay={decay}")
            self.speed_decay = decay
            self.run_speed_test(duration=10)
            
        logger.info("Parameter testing complete")
    
    def run(self):
        """Run the full calibration and testing process."""
        logger.info("=== IMU Calibration and Testing Tool ===")
        
        # Calibrate the IMU
        if not self.calibrate_stationary():
            logger.error("Calibration failed")
            return False
        
        # Run the main speed test
        if not self.run_speed_test(duration=self.args.duration):
            return False
        
        # Test different parameters if requested
        if self.args.test_parameters:
            self.test_parameter_values()
        
        # Clean up
        if self.imu:
            self.imu.close()
        
        logger.info("Calibration and testing complete")
        return True


def parse_args():
    parser = argparse.ArgumentParser(description='IMU Calibration and Testing Tool')
    parser.add_argument('--i2c_bus', type=int, default=4, help='I2C bus number')
    parser.add_argument('--accel_range', type=int, default=2, help='Accelerometer range in g')
    parser.add_argument('--gyro_range', type=int, default=250, help='Gyroscope range in degrees/s')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in seconds')
    parser.add_argument('--test_parameters', action='store_true', help='Test different parameter values')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    calibration = IMUCalibration(args)
    calibration.run() 