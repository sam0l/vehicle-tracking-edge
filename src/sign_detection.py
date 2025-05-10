import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
import onnxruntime

logger = logging.getLogger(__name__)

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config

class SignDetector:
    def __init__(self, config_path):
        self.logger = logging.getLogger(__name__)
        config = load_config(config_path)
        yolo_cfg = config.get("yolo", {})
        self.imgsz = yolo_cfg.get('imgsz', 640)
        self.confidence_threshold = yolo_cfg['confidence_threshold']
        self.iou_threshold = yolo_cfg.get('iou_threshold', 0.5)
        self.send_images = yolo_cfg.get('send_images', True)
        self.class_names = [
            "Green Light", "Red Light", "Speed Limit 10", "Speed Limit 100", "Speed Limit 110",
            "Speed Limit 120", "Speed Limit 20", "Speed Limit 30", "Speed Limit 40", "Speed Limit 50",
            "Speed Limit 60", "Speed Limit 70", "Speed Limit 80", "Speed Limit 90", "Stop"
        ]
        session_options = onnxruntime.SessionOptions()
        session_options.intra_op_num_threads = 4
        session_options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(
            yolo_cfg['model_path'],
            sess_options=session_options,
            providers=['CPUExecutionProvider']
        )
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.logger.info(f"Initialized ONNX model with imgsz={self.imgsz}, confidence_threshold={self.confidence_threshold}")
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

    def postprocess(self, output, iou_threshold=0.5):
        # output: [1, 19, 8400] -> [1, 8400, 19]
        if output.ndim == 3:
            output = output.transpose(0, 2, 1)
        output = output[0]  # [8400, 19]
        boxes = output[:, :4]  # [x_center, y_center, w, h]
        obj_conf = output[:, 4]
        class_scores = output[:, 5:]
        class_ids = np.argmax(class_scores, axis=1)
        class_conf = class_scores[np.arange(class_scores.shape[0]), class_ids]
        confidences = obj_conf * class_conf
        # Filter by confidence
        mask = confidences >= self.confidence_threshold
        boxes = boxes[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]
        if len(boxes) == 0:
            return [], [], []
        # Convert xywh to xyxy
        xyxy_boxes = np.zeros_like(boxes)
        xyxy_boxes[:, 0] = (boxes[:, 0] - boxes[:, 2] / 2) * self.imgsz
        xyxy_boxes[:, 1] = (boxes[:, 1] - boxes[:, 3] / 2) * self.imgsz
        xyxy_boxes[:, 2] = (boxes[:, 0] + boxes[:, 2] / 2) * self.imgsz
        xyxy_boxes[:, 3] = (boxes[:, 1] + boxes[:, 3] / 2) * self.imgsz
        # NMS
        indices = cv2.dnn.NMSBoxes(
            xyxy_boxes.tolist(), confidences.tolist(), self.confidence_threshold, iou_threshold
        )
        if isinstance(indices, tuple):
            indices = indices[0]
        if isinstance(indices, np.ndarray):
            indices = indices.flatten()
        if len(indices) == 0:
            return [], [], []
        return xyxy_boxes[indices], confidences[indices], class_ids[indices]

    def detect(self, frame):
        start_time = time.time()
        img = self.preprocess(frame)
        inference_start = time.time()
        outputs = self.session.run(None, {self.input_name: img})[0]
        inference_time = time.time() - inference_start
        boxes, confidences, class_ids = self.postprocess(outputs, self.iou_threshold)
        detections = []
        for box, confidence, class_id in zip(boxes, confidences, class_ids):
            if class_id < 0 or class_id >= len(self.class_names):
                self.logger.warning(f"Invalid class ID: {class_id} (confidence: {confidence:.3f})")
                continue
            label = self.class_names[class_id]
            self.logger.info(f"Detected {label} with confidence {confidence:.3f}")
            detections.append({
                "sign_type": label,
                "confidence": float(confidence),
                "class_id": int(class_id),
                "class_name": label,
                "bbox": [int(b) for b in box],
                "timestamp": datetime.now().isoformat()
            })
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

