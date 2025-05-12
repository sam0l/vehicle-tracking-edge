# Vehicle Tracking Edge Tests

This directory contains test scripts for the various subsystems of the Vehicle Tracking Edge device.

## Test Organization

The tests are organized as follows:

- **`unified/`**: Contains unified test scripts that provide comprehensive testing for each subsystem
- Older individual test scripts for specific functionality

## Unified Test Framework

The unified test framework provides a consistent approach to testing each subsystem. The main advantages are:

1. **Comprehensive coverage**: Each test script thoroughly tests its respective subsystem
2. **Consistent reporting**: All tests follow the same logging and reporting format
3. **Modular execution**: Tests can be run individually or all together
4. **Command-line options**: Each test supports various options for focused testing

### Running All Tests

To run all tests at once:

```bash
python tests/unified/run_all_tests.py
```

### Running Tests for Specific Subsystems

To run tests for specific subsystems:

```bash
# Test just the IMU
python tests/unified/run_all_tests.py --imu

# Test the GPS and SIM modules
python tests/unified/run_all_tests.py --gps --sim

# Test the camera and sign detection without GUI
python tests/unified/run_all_tests.py --camera --no-gui
```

### Individual Subsystem Tests

Each subsystem has its own dedicated test script that can be run directly:

```bash
# Test IMU
python tests/unified/test_imu.py

# Test GPS
python tests/unified/test_gps.py

# Test SIM monitor
python tests/unified/test_sim_monitor.py

# Test camera and sign detection
python tests/unified/test_camera_and_sign_detection.py
```

Each individual test script also supports specific command-line options. Use the `--help` option to see available options:

```bash
python tests/unified/test_imu.py --help
```

## Legacy Test Scripts

The older individual test scripts are still available but may be less comprehensive than the unified tests. These include:

- `imu_test.py`, `quick_imu_test.py`, `imu_calibration_test.py`: Various IMU test scripts
- `test_gps.py`: GPS functionality test
- `test_camera.py`: Camera functionality test
- `test_sign_detection_server.py`: Sign detection server test
- Various LTE connectivity tests: `lte_diagnostics.py`, `direct_lte_connect.py`, etc.

These scripts may be useful for testing specific functionality or for backwards compatibility.

## Test Results

Test results are stored in the `test_results/` directory, including:
- Log files
- Test plots and images
- Performance data

## Future Improvements

Planned improvements to the test framework:
1. Automated regression testing
2. Integration with CI/CD pipeline
3. More detailed performance benchmarking
4. Comprehensive test coverage reports 