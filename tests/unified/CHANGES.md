# Test Structure Changes

## Summary of Changes

The testing framework has been restructured to provide more comprehensive, consistent testing across all subsystems while maintaining backwards compatibility. The main changes include:

1. **Created a unified test framework** with consistent patterns for each subsystem
2. **Consolidated duplicate IMU tests** into a single comprehensive test script
3. **Added missing tests** for subsystems that lacked proper testing
4. **Improved debugging messages** across all tests
5. **Created a main test runner** that can execute all tests or specific subsystem tests

## New Test Structure

The tests are now organized as follows:

```
tests/
├── unified/                       # New unified test framework
│   ├── test_imu.py                # Comprehensive IMU tests
│   ├── test_gps.py                # GPS module tests
│   ├── test_sim_monitor.py        # SIM card monitoring tests
│   ├── test_camera_and_sign_detection.py  # Camera and sign detection tests
│   ├── run_all_tests.py           # Main test runner script (REMOVED)
│   └── CHANGES.md                 # This document
├── README.md                      # Test documentation
├── integration_test.py            # New integration test for all major subsystems
├── imu_test.py                    # Legacy IMU test (complete)
├── quick_imu_test.py              # Legacy quick IMU test
├── imu_calibration_test.py        # Legacy IMU calibration
├── test_imu.py                    # Legacy basic IMU test
├── test_gps.py                    # Legacy GPS test
├── test_camera.py                 # Legacy camera test
├── test_sign_detection_server.py  # Legacy sign detection test
└── [other legacy test scripts]    # Various legacy tests
```

## Key Improvements

### 1. Unified Testing Framework

- **Consistent Interface**: All unified tests follow the same command-line interface pattern
- **Comprehensive Coverage**: Each test thoroughly exercises its subsystem
- **Proper Error Handling**: All tests handle exceptions properly and provide detailed error messages
- **Clear Results**: Tests output clear success/failure indicators and detailed logs

### 2. IMU Testing

- **Consolidated Tests**: Merged functionality from multiple IMU test scripts
- **Extended Capabilities**: Added GPS simulation for testing dead reckoning
- **Visualization**: Added plotting capabilities for analysis
- **Calibration Testing**: Integrated calibration verification

### 3. GPS Testing

- **Enhanced Functionality**: Improved GPS testing with better error handling
- **Status Reporting**: Added detailed status reporting
- **Complete Coverage**: Tests all GPS functions including AGPS configuration

### 4. SIM Monitor Testing

- **Added Missing Tests**: Created comprehensive tests for the SIM monitor module
- **Data Usage Testing**: Added verification of data usage tracking
- **Network Status**: Tests network status reporting functionality

### 5. Camera and Sign Detection

- **Combined Testing**: Integrated camera and sign detection testing
- **Performance Measurement**: Added performance benchmarking
- **Visual Verification**: Option for visual verification of detections

### 6. Main Test Runner

- **Centralized Control**: Single script to run all tests (REMOVED - replaced by integration_test.py)
- **Selective Testing**: Can run specific subsystem tests (Individual unified tests still support this)
- **Consistent Reporting**: Unified reporting format for all tests
- **Comprehensive Logging**: Detailed logs of all test activities

## New Integration Test (`tests/integration_test.py`)

- **End-to-End Flow**: Tests data flow from sensors through processing to (mocked) backend.
- **Subsystem Interaction**: Verifies that GPS, IMU, Camera, and Sign Detection work together.
- **Simulated LTE & Backend**: Includes a mock HTTP server to simulate backend communication and allows simulating network latency and packet drops.
- **Stability & Robustness**: Designed for longer runs to test system stability under varying (simulated) network conditions.

## Backwards Compatibility

All legacy test scripts are retained for backwards compatibility. The new unified tests work alongside the existing tests without interference.

## Usage

See the `README.md` in the tests directory for detailed usage instructions. 