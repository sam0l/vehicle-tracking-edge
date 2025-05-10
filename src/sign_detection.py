import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
import onnxruntime as ort

logger = logging.getLogger(__name__)

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config

class SignDetector:
    def __init__(self, onnx_model_path, imgsz, confidence_threshold, send_images):
        self.logger = logging.getLogger(__name__)
        self.imgsz = imgsz
        self.confidence_threshold = confidence_threshold
        self.send_images = send_images
        self.class_names = [
            'Green Light', 'Red Light', 'Speed Limit 10', 'Speed Limit 100', 'Speed Limit 110',
            'Speed Limit 120', 'Speed Limit 20', 'Speed Limit 30', 'Speed Limit 40', 'Speed Limit 50',
            'Speed Limit 60', 'Speed Limit 70', 'Speed Limit 80', 'Speed Limit 90', 'Stop'
        ]
        self.ort_session = None
        try:
            self.ort_session = ort.InferenceSession(onnx_model_path)
            self.logger.info(f"Initialized ONNX model: {onnx_model_path}")
        except Exception as e:
            self.logger.error(f"Failed to load ONNX model: {e}")
            raise
        self.logger.info(f"SignDetector initialized with onnx model, imgsz={imgsz}, confidence_threshold={confidence_threshold}")
        # Performance tracking
        self.frame_times = []
        self.inference_times = []
        self.last_fps_update = time.time()
        self.fps_update_interval = 1.0

    def preprocess(self, frame):
        img = cv2.resize(frame, (self.imgsz, self.imgsz))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.transpose((2, 0, 1)).astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)
        return img

    def postprocess(self, outputs, iou_threshold=0.5):
        boxes = outputs[:, :4]  # [x_center, y_center, width, height]
        scores = outputs[:, 4:]  # [num_boxes, num_classes]
        confidences = np.max(scores, axis=1)
        class_ids = np.argmax(scores, axis=1)
        # Filter by confidence
        mask = confidences >= self.confidence_threshold
        boxes = boxes[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]
        if len(boxes) == 0:
            return [], [], []
        # Non-maximum suppression
        indices = cv2.dnn.NMSBoxes(
            boxes.tolist(),
            confidences.tolist(),
            self.confidence_threshold,
            iou_threshold
        )
        self.logger.debug(f"NMS indices: {indices}")
        # Handle varying OpenCV outputs
        indices = indices.flatten() if isinstance(indices, np.ndarray) and indices.ndim > 1 else indices
        if isinstance(indices, tuple):
            indices = indices[0]  # Some OpenCV versions return a tuple
        if len(indices) == 0:
            return [], [], []
        return boxes[indices], confidences[indices], class_ids[indices]

    def detect(self, frame):
        try:
            start_time = time.time()
            img = self.preprocess(frame)
            inference_start = time.time()
            detections = []
            outputs = self.ort_session.run(None, {'images': img})[0]
            outputs = outputs.transpose(0, 2, 1)  # [1, 19, n] -> [1, n, 19]
            self.logger.debug(f"Model output shape: {outputs.shape}, unique class IDs: {np.unique(outputs[0, :, 4:].argmax(axis=1)).tolist()}")
            boxes, confidences, class_ids = self.postprocess(outputs[0])
            for box, confidence, class_id in zip(boxes, confidences, class_ids):
                if class_id < 0 or class_id >= len(self.class_names):
                    self.logger.warning(f"Invalid class ID: {class_id} (confidence: {confidence:.3f})")
                    continue
                label = self.class_names[class_id]
                self.logger.info(f"Detected {label} with confidence {confidence:.3f}")
                print(f"Detected: {label} (confidence: {confidence:.3f})")
                detections.append({
                    "label": label,
                    "confidence": float(confidence),
                    "box": box.tolist()  # [x_center, y_center, width, height]
                })
            inference_time = time.time() - inference_start
            self.update_performance_metrics(time.time() - start_time, inference_time)
            return detections
        except Exception as e:
            self.logger.error(f"Error during detection: {e}")
            return []

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
        if hasattr(self, 'ort_session'):
            del self.ort_session

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
            onnx_model_path="models/yolov8n.onnx",
            imgsz=640,
            confidence_threshold=0.7,
            send_images=True
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

