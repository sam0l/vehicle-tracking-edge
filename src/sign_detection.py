import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
from ultralytics import YOLO
import onnxruntime

logger = logging.getLogger(__name__)

class SignDetector:
    def __init__(self, config_path):
        """
        Initialize the SignDetector.

        Args:
            config_path (str): Path to the YAML config file.
        """
        self.logger = logging.getLogger(__name__)
        config = load_config(config_path)
        yolo_cfg = config.get("yolo", {})
        
        self.model = YOLO(yolo_cfg['onnx_model_path'])
        self.imgsz = yolo_cfg['imgsz']
        self.confidence_threshold = yolo_cfg['confidence_threshold']
        self.send_images = yolo_cfg.get('send_images', True)
        self.logger.info(f"Initialized YOLO model with imgsz={self.imgsz}, confidence_threshold={self.confidence_threshold}")

        # Initialize ONNX Runtime session
        self.session = onnxruntime.InferenceSession(
            yolo_cfg['model_path'],
            providers=['CPUExecutionProvider']
        )
        
        # Get model metadata
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.iou_threshold = yolo_cfg.get('iou_threshold', 0.5)
        
        # Performance tracking
        self.frame_times = []
        self.inference_times = []
        self.last_fps_update = time.time()
        self.fps_update_interval = 1.0  # Update FPS every second

    def preprocess(self, frame):
        """Preprocess frame for model input."""
        # Resize frame to model input size
        input_size = (self.input_shape[2], self.input_shape[3])
        resized = cv2.resize(frame, input_size)
        
        # Convert to float32 and normalize
        blob = cv2.dnn.blobFromImage(
            resized, 
            1/255.0, 
            input_size, 
            swapRB=True, 
            crop=False
        )
        
        return blob

    def detect(self, frame):
        """Detect traffic signs in frame."""
        start_time = time.time()
        
        # Preprocess frame
        blob = self.preprocess(frame)
        
        # Run inference
        inference_start = time.time()
        outputs = self.session.run(None, {self.input_name: blob})
        inference_time = time.time() - inference_start
        
        # Process detections
        detections = self.process_outputs(outputs[0], frame.shape)
        
        # Update performance metrics
        self.update_performance_metrics(time.time() - start_time, inference_time)
        
        return detections

    def process_outputs(self, outputs, frame_shape):
        """Process model outputs into detections."""
        detections = []
        
        # Get original frame dimensions
        height, width = frame_shape[:2]
        
        # Process each detection
        for detection in outputs[0]:
            confidence = detection[4]
            if confidence > self.confidence_threshold:
                # Get bounding box coordinates
                x1, y1, x2, y2 = detection[:4]
                
                # Convert to pixel coordinates
                x1 = int(x1 * width)
                y1 = int(y1 * height)
                x2 = int(x2 * width)
                y2 = int(y2 * height)
                
                # Get class ID
                class_id = int(detection[5])
                
                detections.append({
                    "sign_type": class_id,
                    "confidence": float(confidence),
                    "bbox": [x1, y1, x2, y2]
                })
        
        return detections

    def update_performance_metrics(self, total_time, inference_time):
        """Update and log performance metrics."""
        current_time = time.time()
        
        # Add times to rolling window
        self.frame_times.append(total_time)
        self.inference_times.append(inference_time)
        
        # Keep only last 30 frames for metrics
        if len(self.frame_times) > 30:
            self.frame_times.pop(0)
            self.inference_times.pop(0)
        
        # Update FPS and log metrics periodically
        if current_time - self.last_fps_update >= self.fps_update_interval:
            avg_fps = 1.0 / (sum(self.frame_times) / len(self.frame_times))
            avg_inference = sum(self.inference_times) / len(self.inference_times) * 1000  # Convert to ms
            
            logger.info(f"Performance - FPS: {avg_fps:.1f}, Inference: {avg_inference:.1f}ms")
            
            # Reset metrics
            self.frame_times = []
            self.inference_times = []
            self.last_fps_update = current_time

    def close(self):
        """Clean up resources."""
        if hasattr(self, 'session'):
            del self.session

def load_config(config_path="config/config.yaml"):
    """
    Load YAML configuration file.

    Args:
        config_path (str): Path to the YAML config file.

    Returns:
        dict: Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config

if __name__ == "__main__":
    # Setup logging to integrate with your codebase's logging config
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # Load config from YAML
    config = load_config()

    try:
        # Instantiate SignDetector using config values exactly as you specified
        yolo_cfg = config.get("yolo", {})
        detector = SignDetector(
            config_path=config.get('config_path', None)  # Optional, for backward compatibility
        )
        logger.info("SignDetector initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize SignDetector: {e}")
        exit(1)

    # Example usage (replace with actual frame acquisition logic)
    # frame = cv2.imread("test_image.jpg")
    # if frame is not None:
    #     detections = detector.detect(frame)
    #     print(detections)
    # else:
    #     logger.warning("No frame available for detection.")

