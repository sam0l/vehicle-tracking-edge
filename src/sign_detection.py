import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
import onnxruntime

logger = logging.getLogger(__name__)

class SignDetector:
    def __init__(self, config_path):
        self.logger = logging.getLogger(__name__)
        config = load_config(config_path)
        yolo_cfg = config.get("yolo", {})
        
        # ONNX Runtime session with multi-threading
        session_options = onnxruntime.SessionOptions()
        session_options.intra_op_num_threads = 4  # Use 4 threads, adjust as needed
        session_options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(
            yolo_cfg['model_path'],
            sess_options=session_options,
            providers=['CPUExecutionProvider']
        )
        
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.confidence_threshold = yolo_cfg['confidence_threshold']
        self.iou_threshold = yolo_cfg.get('iou_threshold', 0.5)
        self.send_images = yolo_cfg.get('send_images', True)
        
        # Only two classes: 0 and 1
        self.class_names = [
            "Green Light", "Red Light", "Speed Limit 10", "Speed Limit 100", "Speed Limit 110",
            "Speed Limit 120", "Speed Limit 20", "Speed Limit 30", "Speed Limit 40", "Speed Limit 50",
            "Speed Limit 60", "Speed Limit 70", "Speed Limit 80", "Speed Limit 90", "Stop"
        ]
        
        self.logger.info(f"Initialized ONNX model with confidence_threshold={self.confidence_threshold}")
        
        # Performance tracking
        self.frame_times = []
        self.inference_times = []
        self.last_fps_update = time.time()
        self.fps_update_interval = 1.0  # Update FPS every second

    def preprocess(self, frame):
        input_size = (self.input_shape[2], self.input_shape[3])
        resized = cv2.resize(frame, input_size)
        blob = cv2.dnn.blobFromImage(
            resized, 
            1/255.0, 
            input_size, 
            swapRB=True, 
            crop=False
        )
        return blob

    def detect(self, frame):
        start_time = time.time()
        input_size = (self.input_shape[2], self.input_shape[3])
        img = cv2.resize(frame, input_size)
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[None]  # NCHW
        inference_start = time.time()
        outputs = self.session.run(None, {self.input_name: img})
        inference_time = time.time() - inference_start
        detections = []
        for det in outputs[0][0]:  # [num_detections, 6]
            x1, y1, x2, y2, conf, class_id = det
            class_id = int(class_id)
            if conf > self.confidence_threshold and 0 <= class_id < len(self.class_names):
                detections.append({
                    "sign_type": self.class_names[class_id],
                    "confidence": float(conf),
                    "class_id": class_id,
                    "class_name": self.class_names[class_id],
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "timestamp": datetime.now().isoformat()
                })
            elif conf > self.confidence_threshold:
                logger.warning(f"Ignoring detection with invalid class ID: {class_id}")
        self.update_performance_metrics(time.time() - start_time, inference_time)
        return detections

    def update_performance_metrics(self, total_time, inference_time):
        current_time = time.time()
        self.frame_times.append(total_time)
        self.inference_times.append(inference_time)
        if len(self.frame_times) > 30:
            self.frame_times.pop(0)
            self.inference_times.pop(0)
        if current_time - self.last_fps_update >= self.fps_update_interval:
            avg_fps = 1.0 / (sum(self.frame_times) / len(self.frame_times))
            avg_inference = sum(self.inference_times) / len(self.inference_times) * 1000
            logger.info(f"Performance - FPS: {avg_fps:.1f}, Inference: {avg_inference:.1f}ms")
            self.frame_times = []
            self.inference_times = []
            self.last_fps_update = current_time

    def close(self):
        if hasattr(self, 'session'):
            del self.session

def load_config(config_path="config/config.yaml"):
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

