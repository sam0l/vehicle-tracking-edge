#!/usr/bin/env python3
"""
SIM Card Monitor Test Script

This script tests the SimMonitor class that is responsible for:
- Monitoring SIM card status and cellular network connectivity
- Tracking data usage statistics
- Providing network information

Usage:
python3 tests/unified/test_sim_monitor.py
"""

import sys
import os
import time
import logging
import yaml
import json
from pathlib import Path
import argparse

# Add the parent directory to the path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.sim_monitor import SimMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("sim_monitor_test")

class SimMonitorTester:
    """Test class for the SimMonitor module."""
    
    def __init__(self, config_path='config/config.yaml'):
        """Initialize tester with configuration."""
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                sim_config = self.config.get('sim', {})
                self.port = sim_config.get('port', "/dev/ttyUSB1")
                self.baudrate = sim_config.get('baudrate', 115200)
                self.apn = sim_config.get('apn', "internet")
                logger.info(f"Loaded config: SIM port={self.port}, baudrate={self.baudrate}, APN={self.apn}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            logger.info("Using default SIM settings")
            self.port = "/dev/ttyUSB1"
            self.baudrate = 115200
            self.apn = "internet"
        
        # Create a test-specific usage file to avoid affecting production data
        self.test_usage_file = "test_data_usage.json"
        
        # Create SimMonitor instance with test parameters
        self.sim_monitor = SimMonitor(
            port=self.port,
            baudrate=self.baudrate,
            check_interval=10,  # Use shorter interval for testing
            usage_file=self.test_usage_file,
            interfaces=["eth0", "wlan0"],  # Use available network interfaces for testing
            apn=self.apn
        )
    
    def test_initialization(self):
        """Test initialization of the SIM monitor."""
        logger.info("Testing SIM monitor initialization...")
        
        try:
            result = self.sim_monitor.initialize()
            if result:
                logger.info("SIM monitor initialized successfully")
                return True
            else:
                logger.error("SIM monitor initialization failed")
                return False
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            return False
    
    def test_basic_commands(self):
        """Test basic AT commands."""
        logger.info("Testing basic AT commands...")
        
        if not hasattr(self.sim_monitor, 'serial') or self.sim_monitor.serial is None:
            logger.error("Serial connection not initialized")
            return False
        
        try:
            # Test AT command
            response = self.sim_monitor.send_at_command("AT")
            logger.info(f"AT command response: {response}")
            if not response or "OK" not in response:
                logger.error("Basic AT command test failed")
                return False
            
            # Test SIM status
            response = self.sim_monitor.send_at_command("AT+CPIN?")
            logger.info(f"SIM status response: {response}")
            
            # Test signal strength
            response = self.sim_monitor.send_at_command("AT+CSQ")
            logger.info(f"Signal strength response: {response}")
            
            # Test network registration
            response = self.sim_monitor.send_at_command("AT+CREG?")
            logger.info(f"Network registration response: {response}")
            
            # Test operator info
            response = self.sim_monitor.send_at_command("AT+COPS?")
            logger.info(f"Operator info response: {response}")
            
            logger.info("Basic AT command tests completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during basic command tests: {e}")
            return False
    
    def test_data_usage_tracking(self):
        """Test data usage tracking functionality."""
        logger.info("Testing data usage tracking...")
        
        try:
            # Get initial counters
            initial_counters = self.sim_monitor.get_current_counters()
            logger.info(f"Initial data counters: {initial_counters}")
            
            # Update data usage
            self.sim_monitor.update_data_usage()
            logger.info("Updated data usage")
            
            # Generate some network traffic (if possible)
            logger.info("Generating network traffic...")
            try:
                import requests
                for _ in range(3):
                    try:
                        requests.get("https://www.google.com", timeout=5)
                        time.sleep(1)
                    except:
                        pass
            except ImportError:
                logger.warning("Requests library not available, skipping traffic generation")
            
            # Update data usage again
            self.sim_monitor.update_data_usage()
            logger.info("Updated data usage after traffic")
            
            # Get usage statistics
            stats = self.sim_monitor.get_usage_stats()
            logger.info(f"Current usage stats: {stats}")
            
            # Verify that the usage file was created
            if not os.path.exists(self.test_usage_file):
                logger.error(f"Usage file {self.test_usage_file} was not created")
                return False
            
            # Check file content
            with open(self.test_usage_file, 'r') as f:
                usage_data = json.load(f)
                logger.info(f"Loaded {len(usage_data)} usage records from file")
            
            logger.info("Data usage tracking test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during data usage tracking test: {e}")
            return False
    
    def test_network_info(self):
        """Test network information retrieval."""
        logger.info("Testing network information retrieval...")
        
        try:
            # Get signal strength
            signal = self.sim_monitor.get_signal_strength()
            logger.info(f"Signal strength: {signal}")
            
            # Get network info
            network = self.sim_monitor.get_network_info()
            logger.info(f"Network info: {network}")
            
            logger.info("Network information test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during network information test: {e}")
            return False
    
    def run_all_tests(self):
        """Run all SIM monitor tests."""
        logger.info("Running all SIM monitor tests...")
        
        # Initialize SIM monitor
        if not self.test_initialization():
            logger.error("Initialization test failed, aborting further tests")
            return False
        
        # Run individual tests
        test_basic = self.test_basic_commands()
        test_usage = self.test_data_usage_tracking()
        test_network = self.test_network_info()
        
        # Clean up
        if hasattr(self.sim_monitor, 'serial') and self.sim_monitor.serial:
            self.sim_monitor.close()
            logger.info("Closed serial connection")
        
        # Remove test usage file
        try:
            if os.path.exists(self.test_usage_file):
                os.remove(self.test_usage_file)
                logger.info(f"Removed test usage file {self.test_usage_file}")
        except Exception as e:
            logger.warning(f"Failed to remove test usage file: {e}")
        
        # Overall result
        overall = test_basic and test_usage and test_network
        logger.info(f"All tests completed. Overall result: {'SUCCESS' if overall else 'FAILURE'}")
        return overall

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="SIM Monitor Testing Framework")
    parser.add_argument("--init", action="store_true", help="Test initialization only")
    parser.add_argument("--basic", action="store_true", help="Test basic AT commands only")
    parser.add_argument("--usage", action="store_true", help="Test data usage tracking only")
    parser.add_argument("--network", action="store_true", help="Test network information only")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    return parser.parse_args()

def main():
    """Main function to run SIM monitor tests."""
    args = parse_args()
    
    logger.info("Starting SIM monitor tests...")
    
    # Create tester instance
    tester = SimMonitorTester()
    
    # Check if any specific test was requested
    if args.init:
        tester.test_initialization()
    elif args.basic:
        if tester.test_initialization():
            tester.test_basic_commands()
    elif args.usage:
        if tester.test_initialization():
            tester.test_data_usage_tracking()
    elif args.network:
        if tester.test_initialization():
            tester.test_network_info()
    else:
        # Run all tests by default
        tester.run_all_tests()
    
    logger.info("SIM monitor testing complete")

if __name__ == "__main__":
    main() 