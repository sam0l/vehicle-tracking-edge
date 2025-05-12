#!/usr/bin/env python3
"""
GPS Module Test Script

This script tests the GPS functionality, including:
- Serial communication with the GPS module
- NMEA sentence parsing
- Position and speed calculation
- Status monitoring

Usage:
python3 tests/unified/test_gps.py
"""

import sys
import os
import time
import logging
import yaml
import argparse
from datetime import datetime

# Add the parent directory to the path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.gps import GPS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("gps_test")

class GPSTester:
    """Test class for the GPS module."""
    
    def __init__(self, config_path='config/config.yaml'):
        """Initialize tester with configuration."""
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                gps_config = self.config.get('gps', {})
                self.port = gps_config.get('port', "/dev/ttyUSB3")
                self.baudrate = gps_config.get('baudrate', 115200)
                self.timeout = gps_config.get('timeout', 1.0)
                self.power_delay = gps_config.get('power_delay', 5)
                self.agps_delay = gps_config.get('agps_delay', 5)
                logger.info(f"Loaded config: GPS port={self.port}, baudrate={self.baudrate}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            logger.info("Using default GPS settings")
            self.port = "/dev/ttyUSB3"
            self.baudrate = 115200
            self.timeout = 1.0
            self.power_delay = 5
            self.agps_delay = 5
        
        # Create GPS instance
        self.gps = None
    
    def initialize_gps(self):
        """Initialize the GPS module."""
        logger.info("Initializing GPS module...")
        
        try:
            self.gps = GPS(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                power_delay=self.power_delay,
                agps_delay=self.agps_delay
            )
            
            result = self.gps.initialize()
            if result:
                logger.info("GPS initialized successfully")
                return True
            else:
                logger.error("GPS initialization failed")
                return False
        except Exception as e:
            logger.error(f"Error during GPS initialization: {e}")
            return False
    
    def test_basic_communication(self):
        """Test basic communication with the GPS module."""
        logger.info("Testing basic GPS communication...")
        
        if not self.gps:
            logger.error("GPS not initialized")
            return False
        
        try:
            # Test sending a basic AT command
            response = self.gps.send_command("AT", expected_response="OK")
            logger.info(f"Basic AT command response: {response}")
            
            # Test getting module information
            response = self.gps.send_command("ATI", expected_response=None)
            logger.info(f"Module information: {response}")
            
            # Check if GPS is powered on
            response = self.gps.send_command("AT+CGNSPWR?", expected_response="+CGNSPWR:")
            logger.info(f"GPS power status: {response}")
            
            # Ensure GPS is powered on
            if "+CGNSPWR: 0" in response:
                logger.info("GPS is powered off, turning it on...")
                response = self.gps.send_command("AT+CGNSPWR=1", expected_response="OK")
                logger.info(f"GPS power on response: {response}")
                # Wait for GPS to initialize
                time.sleep(2)
            
            logger.info("Basic GPS communication test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during basic GPS communication test: {e}")
            return False
    
    def test_gps_data_reading(self, duration=30, interval=1.0):
        """Test reading GPS data for a specified duration."""
        logger.info(f"Reading GPS data for {duration} seconds...")
        
        if not self.gps:
            logger.error("GPS not initialized")
            return False
        
        try:
            start_time = time.time()
            end_time = start_time + duration
            readings = []
            
            while time.time() < end_time:
                # Get GPS data
                gps_data = self.gps.read_gps_data()
                
                if gps_data and gps_data.get('fix'):
                    # Format GPS data for logging
                    lat = gps_data.get('latitude', 0)
                    lon = gps_data.get('longitude', 0)
                    speed = gps_data.get('speed', 0)
                    satellites = gps_data.get('satellites', 0)
                    
                    logger.info(f"GPS Data: lat={lat:.6f}, lon={lon:.6f}, "
                               f"speed={speed:.2f}m/s, satellites={satellites}")
                    
                    readings.append(gps_data)
                else:
                    reason = gps_data.get('reason', 'unknown') if gps_data else 'no_data'
                    satellites = gps_data.get('satellites', 0) if gps_data else 0
                    logger.warning(f"No GPS fix: {reason}, satellites={satellites}")
                
                # Wait for next reading
                time.sleep(interval)
            
            # Summarize results
            fix_count = sum(1 for r in readings if r.get('fix'))
            total_readings = len(readings)
            if total_readings > 0:
                fix_percentage = (fix_count / total_readings) * 100
            else:
                fix_percentage = 0
                
            logger.info(f"GPS data reading test completed: {fix_count}/{total_readings} readings with fix ({fix_percentage:.1f}%)")
            
            return fix_count > 0  # Success if we got at least one fix
        except Exception as e:
            logger.error(f"Error during GPS data reading test: {e}")
            return False
    
    def test_gps_status(self):
        """Test GPS status functions."""
        logger.info("Testing GPS status functions...")
        
        if not self.gps:
            logger.error("GPS not initialized")
            return False
        
        try:
            # Check GPS power status
            power_status = self.gps.get_power_status()
            logger.info(f"GPS power status: {power_status}")
            
            # Check GPS navigation status
            nav_status = self.gps.get_navigation_status()
            logger.info(f"GPS navigation status: {nav_status}")
            
            # Check satellite information
            satellite_info = self.gps.get_satellite_info()
            logger.info(f"Satellite information: {satellite_info}")
            
            logger.info("GPS status test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during GPS status test: {e}")
            return False
    
    def test_gps_commands(self):
        """Test GPS-specific commands."""
        logger.info("Testing GPS-specific commands...")
        
        if not self.gps:
            logger.error("GPS not initialized")
            return False
        
        try:
            # Test setting GPS operation mode
            logger.info("Setting GPS to autonomous mode...")
            result = self.gps.set_gps_mode("autonomous")
            logger.info(f"Set GPS mode result: {result}")
            
            # Test cold start (if implemented)
            if hasattr(self.gps, 'cold_start'):
                logger.info("Testing cold start...")
                result = self.gps.cold_start()
                logger.info(f"Cold start result: {result}")
            else:
                logger.info("Cold start not implemented, skipping")
            
            # Test hot start (if implemented)
            if hasattr(self.gps, 'hot_start'):
                logger.info("Testing hot start...")
                result = self.gps.hot_start()
                logger.info(f"Hot start result: {result}")
            else:
                logger.info("Hot start not implemented, skipping")
            
            logger.info("GPS commands test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during GPS commands test: {e}")
            return False
    
    def run_all_tests(self):
        """Run all GPS tests."""
        logger.info("Running all GPS tests...")
        
        # Initialize GPS
        if not self.initialize_gps():
            logger.error("GPS initialization failed, aborting further tests")
            return False
        
        # Run individual tests
        test_basic = self.test_basic_communication()
        test_status = self.test_gps_status()
        test_commands = self.test_gps_commands()
        
        # Run data reading test last as it takes longer
        test_data = self.test_gps_data_reading(duration=30)
        
        # Clean up
        if self.gps:
            self.gps.close()
            logger.info("Closed GPS connection")
        
        # Overall result
        overall = test_basic and test_status and test_commands and test_data
        logger.info(f"All tests completed. Overall result: {'SUCCESS' if overall else 'FAILURE'}")
        return overall

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="GPS Testing Framework")
    parser.add_argument("--basic", action="store_true", help="Test basic communication only")
    parser.add_argument("--status", action="store_true", help="Test GPS status functions only")
    parser.add_argument("--commands", action="store_true", help="Test GPS-specific commands only")
    parser.add_argument("--data", action="store_true", help="Test GPS data reading only")
    parser.add_argument("--duration", type=int, default=30, help="Duration for data reading test")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    return parser.parse_args()

def main():
    """Main function to run GPS tests."""
    args = parse_args()
    
    logger.info("Starting GPS tests...")
    
    # Create tester instance
    tester = GPSTester()
    
    # Check if any specific test was requested
    if args.basic:
        if tester.initialize_gps():
            tester.test_basic_communication()
    elif args.status:
        if tester.initialize_gps():
            tester.test_gps_status()
    elif args.commands:
        if tester.initialize_gps():
            tester.test_gps_commands()
    elif args.data:
        if tester.initialize_gps():
            tester.test_gps_data_reading(duration=args.duration)
    else:
        # Run all tests by default
        tester.run_all_tests()
    
    logger.info("GPS testing complete")

if __name__ == "__main__":
    main() 