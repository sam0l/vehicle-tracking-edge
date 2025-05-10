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
    def __init__(self, config_path='config/config.yaml'):
        self.logger = logging.getLogger(__name__)

        # Load config
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        yolo_config = config['yolo']
        self.imgsz = yolo_config['imgsz']
        self.confidence_threshold = yolo_config['confidence_threshold']
        self.iou_threshold = yolo_config['iou_threshold']
        self.send_images = yolo_config['send_images']

        self.class_names = [
            'Green Light', 'Red Light', 'Speed Limit 10', 'Speed Limit 100', 'Speed Limit 110',
            'Speed Limit 120', 'Speed Limit 20', 'Speed Limit 30', 'Speed Limit 40', 'Speed Limit 50',
            'Speed Limit 60', 'Speed Limit 70', 'Speed Limit 80', 'Speed Limit 90', 'Stop'
        ]

        # Initialize ONNX model with multi-threading
        try:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = 4  # Use 4 CPU cores (adjust as needed)
            self.ort_session = ort.InferenceSession(yolo_config['model_path'], sess_options=sess_options)
            output_shapes = [output.shape for output in self.ort_session.get_outputs()]
            self.logger.info(f"Initialized ONNX model: {yolo_config['model_path']}, output shapes: {output_shapes}")
        except Exception as e:
            self.logger.error(f"Failed to load ONNX model: {e}")
            raise

        self.logger.info(f"SignDetector initialized with ONNX model, imgsz={self.imgsz}, confidence_threshold={self.confidence_threshold}, iou_threshold={self.iou_threshold}")

    def preprocess(self, frame):
        img = cv2.resize(frame, (self.imgsz, self.imgsz))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)
        img = np.expand_dims(img, axis=0)
        return img

    def postprocess(self, outputs):
        if len(outputs.shape) != 3 or outputs.shape[0] != 1:
            self.logger.error(f"Unexpected output shape: {outputs.shape}, expected [1, ?, ?]")
            return [], [], []

        outputs = outputs[0]
        num_classes = len(self.class_names)
        expected_channels = num_classes + 4

        if outputs.shape[0] == expected_channels:
            outputs = outputs.transpose(1, 0)
        else:
            self.logger.error(f"Unexpected channel count: {outputs.shape[0]}, expected {expected_channels}")
            return [], [], []

        boxes = outputs[:, :4]
        scores = outputs[:, 4:]

        self.logger.debug(f"Raw scores min/max/mean: {scores.min():.4f}/{scores.max():.4f}/{scores.mean():.4f}")
        scores = 1 / (1 + np.exp(-scores))
        self.logger.debug(f"Sigmoid scores min/max/mean: {scores.min():.4f}/{scores.max():.4f}/{scores.mean():.4f}")

        confidences = np.max(scores, axis=1)
        class_ids = np.argmax(scores, axis=1)

        self.logger.debug(f"Detections before confidence filter: {len(confidences)}")
        mask = confidences >= self.confidence_threshold
        if not np.any(mask):
            self.logger.debug("No detections above confidence threshold")
            return [], [], []

        boxes = boxes[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]

        self.logger.debug(f"Detections after confidence filter: {len(boxes)}")

        boxes[:, [0, 2]] *= self.imgsz
        boxes[:, [1, 3]] *= self.imgsz

        boxes_xyxy = np.zeros_like(boxes)
        boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2

        indices = cv2.dnn.NMSBoxes(
            boxes_xyxy.tolist(),
            confidences.tolist(),
            self.confidence_threshold,
            self.iou_threshold
        )

        indices = indices.flatten() if isinstance(indices, np.ndarray) and indices.ndim > 1 else indices
        if isinstance(indices, tuple):
            indices = indices[0]

        self.logger.debug(f"Detections after NMS: {len(indices)}")

        if len(indices) == 0:
            self.logger.debug("No detections after NMS")
            return [], [], []

        boxes = boxes[indices]
        boxes[:, [0, 2]] /= self.imgsz
        boxes[:, [1, 3]] /= self.imgsz
        confidences = confidences[indices]
        class_ids = class_ids[indices]

        return boxes, confidences, class_ids

    def detect(self, frame):
        try:
            start_time = time.time()
            preprocess_start = time.time()
            img = self.preprocess(frame)
            preprocess_time = time.time() - preprocess_start
            inference_start = time.time()
            outputs = self.ort_session.run(None, {'images': img})[0]
            inference_time = time.time() - inference_start
            postprocess_start = time.time()
            boxes, confidences, class_ids = self.postprocess(outputs)
            postprocess_time = time.time() - postprocess_start
            total_time = time.time() - start_time
            fps = 1.0 / total_time if total_time > 0 else 0.0
            self.logger.info(
                f"Detection completed: FPS={fps:.2f}, "
                f"Total={total_time*1000:.2f}ms "
                f"(Preprocess={preprocess_time*1000:.2f}ms, "
                f"Inference={inference_time*1000:.2f}ms, "
                f"Postprocess={postprocess_time*1000:.2f}ms)"
            )
            detections = []
            for box, confidence, class_id in zip(boxes, confidences, class_ids):
                if class_id < 0 or class_id >= len(self.class_names):
                    self.logger.warning(f"Invalid class ID: {class_id} (confidence: {confidence:.3f})")
                    continue
                label = self.class_names[class_id]
                print(f"Detected: {label} (confidence: {confidence:.3f})")
                self.logger.info(f"Detected {label} with confidence {confidence:.3f}, box: {box.tolist()}")
                detection = {
                    "label": label,
                    "confidence": float(confidence),
                    "box": box.tolist()
                }
                if self.send_images:
                    detection["image"] = None
                detections.append(detection)
            return detections
        except Exception as e:
            self.logger.error(f"Error during detection: {e}")
            return []

    def close(self):
        self.logger.info("SignDetector closed")

if __name__ == "__main__":
    # Setup logging to integrate with your codebase's logging config
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # Load config from YAML
    config = load_config()

    try:
        # Instantiate SignDetector using config values exactly as you specified
        yolo_cfg = config.get("yolo", {})
        detector = SignDetector(config_path='config/config.yaml')
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

