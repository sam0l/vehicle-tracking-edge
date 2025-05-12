#!/usr/bin/env python3
"""
Unified Test Runner

This script runs all the unified tests for the vehicle tracking system.
It allows running individual subsystem tests or all tests together.

Usage:
python3 tests/unified/run_all_tests.py [--imu] [--gps] [--sim] [--camera] [--all]
"""

import sys
import os
import argparse
import logging
import subprocess
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'test_results/unified_tests_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("test_runner")

# Define test modules
TEST_MODULES = {
    'imu': {
        'name': 'IMU Module',
        'script': 'test_imu.py',
        'description': 'Tests inertial measurement unit functionality'
    },
    'gps': {
        'name': 'GPS Module',
        'script': 'test_gps.py',
        'description': 'Tests GPS module functionality'
    },
    'sim': {
        'name': 'SIM Monitor',
        'script': 'test_sim_monitor.py',
        'description': 'Tests SIM card monitoring functionality'
    },
    'camera': {
        'name': 'Camera & Sign Detection',
        'script': 'test_camera_and_sign_detection.py',
        'description': 'Tests camera and sign detection functionality'
    }
}

def ensure_test_results_dir():
    """Ensure the test results directory exists."""
    os.makedirs('test_results', exist_ok=True)

def run_test(module_key, additional_args=None):
    """Run the test for a specific module."""
    if module_key not in TEST_MODULES:
        logger.error(f"Unknown module: {module_key}")
        return False
    
    module = TEST_MODULES[module_key]
    logger.info(f"===== Running {module['name']} Tests =====")
    
    # Build the command
    script_path = os.path.join(os.path.dirname(__file__), module['script'])
    cmd = [sys.executable, script_path]
    
    # Add any additional arguments
    if additional_args:
        cmd.extend(additional_args)
    
    # Run the test
    try:
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - start_time
        
        # Log output
        logger.info(f"Test completed in {elapsed:.1f} seconds with return code {result.returncode}")
        
        if result.stdout:
            for line in result.stdout.splitlines():
                logger.info(f"[{module_key} stdout] {line}")
        
        if result.stderr:
            for line in result.stderr.splitlines():
                logger.warning(f"[{module_key} stderr] {line}")
        
        success = result.returncode == 0
        logger.info(f"===== {module['name']} Tests: {'PASSED' if success else 'FAILED'} =====")
        return success
    except Exception as e:
        logger.error(f"Error running {module['name']} test: {e}")
        return False

def run_all_tests(args):
    """Run all the tests."""
    ensure_test_results_dir()
    
    logger.info("Starting unified test run")
    start_time = time.time()
    
    # Determine which tests to run
    tests_to_run = []
    for module_key in TEST_MODULES:
        arg_key = f"run_{module_key}"
        if hasattr(args, arg_key) and getattr(args, arg_key):
            tests_to_run.append(module_key)
    
    # If no specific tests were requested, run all tests
    if not tests_to_run:
        tests_to_run = list(TEST_MODULES.keys())
    
    # Run the tests
    results = {}
    for module_key in tests_to_run:
        # Build additional args for each test
        additional_args = ['--all']
        if hasattr(args, 'no_gui') and args.no_gui and module_key == 'camera':
            additional_args.append('--no-gui')
        
        # Run the test
        results[module_key] = run_test(module_key, additional_args)
    
    # Calculate overall result
    overall_success = all(results.values())
    elapsed = time.time() - start_time
    
    # Print summary
    logger.info("\n===== Test Run Summary =====")
    logger.info(f"Total execution time: {elapsed:.1f} seconds")
    for module_key, success in results.items():
        logger.info(f"{TEST_MODULES[module_key]['name']}: {'PASSED' if success else 'FAILED'}")
    logger.info(f"Overall result: {'PASSED' if overall_success else 'FAILED'}")
    
    return overall_success

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Unified Test Runner")
    
    # Add module-specific arguments
    for module_key, module in TEST_MODULES.items():
        parser.add_argument(
            f"--{module_key}",
            dest=f"run_{module_key}",
            action="store_true",
            help=f"Run {module['name']} tests ({module['description']})"
        )
    
    # Add global arguments
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    parser.add_argument("--no-gui", action="store_true", help="Run tests without GUI visualization")
    
    return parser.parse_args()

def main():
    """Main function to run the tests."""
    args = parse_args()
    success = run_all_tests(args)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main()) 