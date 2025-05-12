#!/usr/bin/env python3
"""
Camera and Sign Detection Test Script

This script tests the camera and sign detection functionality, including:
- Camera initialization and frame capture
- Sign detection model loading and inference
- Visualization of detection results
- Performance measurement

Usage:
python3 tests/unified/test_camera_and_sign_detection.py
"""

import sys
import os
import time
import logging
import yaml
import argparse
import cv2
import numpy as np
from pathlib import Path

# Add the parent directory to the path to allow importing from src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from src.camera import Camera
from src.sign_detection import SignDetector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("camera_sign_test")

class CameraSignTester:
    """Test class for the camera and sign detection modules."""
    
    def __init__(self, config_path='config/config.yaml'):
        """Initialize tester with configuration."""
        # Load configuration
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
                camera_config = self.config.get('camera', {})
                self.device_id = camera_config.get('device_id', 0)
                self.width = camera_config.get('width', 1280)
                self.height = camera_config.get('height', 720)
                self.fps = camera_config.get('fps', 30)
                logger.info(f"Loaded config: Camera device={self.device_id}, "
                           f"resolution={self.width}x{self.height}, fps={self.fps}")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            logger.info("Using default camera settings")
            self.device_id = 0
            self.width = 1280
            self.height = 720
            self.fps = 30
        
        # Create camera and detector instances
        self.camera = None
        self.detector = None
        
        # Create results directory
        self.results_dir = Path('test_results')
        self.results_dir.mkdir(exist_ok=True)
    
    def initialize(self):
        """Initialize camera and sign detector."""
        logger.info("Initializing camera and sign detector...")
        
        try:
            # Initialize camera
            self.camera = Camera(
                device_id=self.device_id,
                width=self.width,
                height=self.height,
                fps=self.fps
            )
            
            camera_result = self.camera.initialize()
            if not camera_result:
                logger.error("Camera initialization failed")
                return False
            logger.info("Camera initialized successfully")
            
            # Initialize sign detector
            self.detector = SignDetector('config/config.yaml')
            detector_result = self.detector.initialize()
            if not detector_result:
                logger.error("Sign detector initialization failed")
                return False
            logger.info("Sign detector initialized successfully")
            
            return True
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            return False
    
    def test_camera_basic(self, num_frames=10):
        """Test basic camera functionality."""
        logger.info(f"Testing basic camera functionality with {num_frames} frames...")
        
        if not self.camera:
            logger.error("Camera not initialized")
            return False
        
        try:
            for i in range(num_frames):
                frame = self.camera.get_frame()
                if frame is None:
                    logger.error(f"Failed to capture frame {i+1}/{num_frames}")
                    continue
                
                logger.info(f"Captured frame {i+1}/{num_frames} with shape {frame.shape}")
                
                # Save the first and last frame
                if i == 0 or i == num_frames - 1:
                    filename = os.path.join(self.results_dir, f"camera_frame_{i+1}.jpg")
                    cv2.imwrite(filename, frame)
                    logger.info(f"Saved frame to {filename}")
                
                time.sleep(0.1)  # Short delay between frames
            
            logger.info("Basic camera test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during basic camera test: {e}")
            return False
    
    def test_detector_basic(self):
        """Test basic sign detector functionality with a static image."""
        logger.info("Testing basic sign detector functionality...")
        
        if not self.detector:
            logger.error("Sign detector not initialized")
            return False
        
        try:
            # Check if we have any test images
            test_image_path = os.path.join(self.results_dir, "camera_frame_1.jpg")
            if not os.path.exists(test_image_path):
                logger.error(f"No test image found at {test_image_path}")
                # Try to capture a frame directly
                if self.camera:
                    frame = self.camera.get_frame()
                    if frame is not None:
                        cv2.imwrite(test_image_path, frame)
                        logger.info(f"Captured and saved a test frame to {test_image_path}")
                    else:
                        logger.error("Failed to capture a test frame")
                        return False
                else:
                    logger.error("Camera not initialized, cannot capture test frame")
                    return False
            
            # Load test image
            image = cv2.imread(test_image_path)
            if image is None:
                logger.error(f"Failed to load test image from {test_image_path}")
                return False
            
            logger.info(f"Loaded test image with shape {image.shape}")
            
            # Run detection
            start_time = time.time()
            detections = self.detector.detect(image)
            inference_time = time.time() - start_time
            
            logger.info(f"Detection completed in {inference_time:.3f} seconds")
            logger.info(f"Found {len(detections)} detections")
            
            # Draw detections on image
            if len(detections) > 0:
                for det in detections:
                    # Extract bounding box coordinates
                    if 'bbox' in det:
                        x1, y1, x2, y2 = det['bbox']
                    elif 'box' in det:
                        box = det['box']
                        # Convert center format (cx, cy, w, h) to corner format (x1, y1, x2, y2)
                        cx, cy, w, h = box
                        x1 = int(cx - w/2)
                        y1 = int(cy - h/2)
                        x2 = int(cx + w/2)
                        y2 = int(cy + h/2)
                    else:
                        logger.warning(f"Detection missing bbox or box: {det}")
                        continue
                    
                    # Draw rectangle
                    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    
                    # Add label
                    label = det.get('label', 'Unknown')
                    confidence = det.get('confidence', 0)
                    text = f"{label}: {confidence:.2f}"
                    cv2.putText(image, text, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                # Save annotated image
                output_path = os.path.join(self.results_dir, "detection_result.jpg")
                cv2.imwrite(output_path, image)
                logger.info(f"Saved detection results to {output_path}")
            
            logger.info("Basic sign detector test completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during basic sign detector test: {e}")
            return False
    
    def test_live_detection(self, duration=10, visualize=True):
        """Test live sign detection for a specified duration."""
        logger.info(f"Testing live sign detection for {duration} seconds...")
        
        if not self.camera or not self.detector:
            logger.error("Camera or detector not initialized")
            return False
        
        try:
            start_time = time.time()
            end_time = start_time + duration
            frame_count = 0
            detection_count = 0
            
            # Create a window for visualization if needed
            if visualize:
                cv2.namedWindow("Live Detection", cv2.WINDOW_NORMAL)
            
            while time.time() < end_time:
                # Get frame
                frame = self.camera.get_frame()
                if frame is None:
                    logger.error("Failed to capture frame")
                    time.sleep(0.1)
                    continue
                
                frame_count += 1
                
                # Run detection
                detections = self.detector.detect(frame)
                detection_count += len(detections)
                
                # Visualize results
                if visualize:
                    # Draw detections
                    for det in detections:
                        if 'bbox' in det:
                            x1, y1, x2, y2 = det['bbox']
                        elif 'box' in det:
                            box = det['box']
                            cx, cy, w, h = box
                            x1 = int(cx - w/2)
                            y1 = int(cy - h/2)
                            x2 = int(cx + w/2)
                            y2 = int(cy + h/2)
                        else:
                            continue
                        
                        label = det.get('label', 'Unknown')
                        confidence = det.get('confidence', 0)
                        
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"{label}: {confidence:.2f}", (x1, y1-10),
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    
                    # Add frame rate info
                    elapsed = time.time() - start_time
                    if elapsed > 0:
                        fps = frame_count / elapsed
                        cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                                  cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    
                    # Show frame
                    cv2.imshow("Live Detection", frame)
                    
                    # Exit if 'q' is pressed
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                
                # Log stats every second
                elapsed = time.time() - start_time
                if int(elapsed) > int(elapsed - 0.1):
                    if elapsed > 0:
                        fps = frame_count / elapsed
                        logger.info(f"Processed {frame_count} frames at {fps:.1f} FPS, "
                                  f"found {detection_count} detections")
            
            # Clean up
            if visualize:
                cv2.destroyAllWindows()
            
            # Log final stats
            elapsed = time.time() - start_time
            if elapsed > 0:
                fps = frame_count / elapsed
                logger.info(f"Live detection test completed: {frame_count} frames at {fps:.1f} FPS, "
                          f"found {detection_count} detections")
            
            return True
        except Exception as e:
            logger.error(f"Error during live detection test: {e}")
            return False
    
    def test_performance(self, num_iterations=100):
        """Test detection performance on a single frame repeated multiple times."""
        logger.info(f"Testing detection performance with {num_iterations} iterations...")
        
        if not self.camera or not self.detector:
            logger.error("Camera or detector not initialized")
            return False
        
        try:
            # Capture a frame
            frame = self.camera.get_frame()
            if frame is None:
                logger.error("Failed to capture frame")
                return False
            
            # Run detection multiple times and measure performance
            inference_times = []
            detection_counts = []
            
            for i in range(num_iterations):
                start_time = time.time()
                detections = self.detector.detect(frame)
                inference_time = time.time() - start_time
                
                inference_times.append(inference_time)
                detection_counts.append(len(detections))
                
                if i % 10 == 0:
                    logger.info(f"Iteration {i+1}/{num_iterations}: "
                              f"{len(detections)} detections in {inference_time:.3f}s")
            
            # Calculate statistics
            avg_time = sum(inference_times) / len(inference_times)
            avg_fps = 1.0 / avg_time
            avg_detections = sum(detection_counts) / len(detection_counts)
            
            logger.info(f"Performance test results:")
            logger.info(f"  Average inference time: {avg_time:.3f}s")
            logger.info(f"  Average FPS: {avg_fps:.1f}")
            logger.info(f"  Average detections per frame: {avg_detections:.1f}")
            
            return True
        except Exception as e:
            logger.error(f"Error during performance test: {e}")
            return False
    
    def run_all_tests(self, visualize=True):
        """Run all camera and sign detection tests."""
        logger.info("Running all camera and sign detection tests...")
        
        # Initialize camera and detector
        if not self.initialize():
            logger.error("Initialization failed, aborting further tests")
            return False
        
        # Run individual tests
        test_camera = self.test_camera_basic(num_frames=5)
        test_detector = self.test_detector_basic()
        test_performance = self.test_performance(num_iterations=20)
        test_live = self.test_live_detection(duration=10, visualize=visualize)
        
        # Clean up
        if self.camera:
            self.camera.close()
            logger.info("Closed camera")
        
        if self.detector:
            self.detector.close()
            logger.info("Closed detector")
        
        # Overall result
        overall = test_camera and test_detector and test_performance and test_live
        logger.info(f"All tests completed. Overall result: {'SUCCESS' if overall else 'FAILURE'}")
        return overall

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Camera and Sign Detection Testing Framework")
    parser.add_argument("--camera", action="store_true", help="Test camera functionality only")
    parser.add_argument("--detector", action="store_true", help="Test sign detector only")
    parser.add_argument("--live", action="store_true", help="Test live detection only")
    parser.add_argument("--performance", action="store_true", help="Test detection performance only")
    parser.add_argument("--duration", type=int, default=10, help="Duration for live detection test")
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI visualization")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    return parser.parse_args()

def main():
    """Main function to run camera and sign detection tests."""
    args = parse_args()
    
    logger.info("Starting camera and sign detection tests...")
    
    # Create tester instance
    tester = CameraSignTester()
    
    # Check if any specific test was requested
    if args.camera:
        if tester.initialize():
            tester.test_camera_basic(num_frames=10)
    elif args.detector:
        if tester.initialize():
            tester.test_detector_basic()
    elif args.live:
        if tester.initialize():
            tester.test_live_detection(duration=args.duration, visualize=not args.no_gui)
    elif args.performance:
        if tester.initialize():
            tester.test_performance(num_iterations=100)
    else:
        # Run all tests by default
        tester.run_all_tests(visualize=not args.no_gui)
    
    logger.info("Camera and sign detection testing complete")

if __name__ == "__main__":
    main() 