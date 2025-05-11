import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
import onnxruntime as ort
from typing import Tuple, Union

logger = logging.getLogger(__name__)

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config

def letterbox(img, new_shape: Union[int, Tuple[int, int]], color=(114, 114, 114)):
    # Resize image and keep aspect ratio with padding
    shape = img.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
    new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
    img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    dw /= 2
    dh /= 2
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)

def draw_boxes_on_image(img, boxes, class_ids, confidences, class_names):
    img = img.copy()
    h, w = img.shape[:2]
    for box, class_id, conf in zip(boxes, class_ids, confidences):
        x1 = int(box[0] * w)
        y1 = int(box[1] * h)
        x2 = int(box[2] * w)
        y2 = int(box[3] * h)
        label = f"{class_names[class_id]}: {conf:.2f}"
        color = (0, 255, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    return img

class SignDetector:
    def __init__(self, config_path='config/config.yaml'):
        self.logger = logging.getLogger(__name__)
        self.config = load_config(config_path)
        yolo_config = self.config['yolo']
        self.imgsz = yolo_config['imgsz']
        self.confidence_threshold = yolo_config['confidence_threshold']
        self.iou_threshold = yolo_config['iou_threshold']
        self.send_images = yolo_config.get('send_images', True)
        self.class_names = yolo_config.get('class_names', [])
        self.intra_op_num_threads = yolo_config.get('intra_op_num_threads', 4)
        self.draw_boxes = yolo_config.get('draw_boxes', False)

        # Initialize ONNX model with configurable multi-threading
        try:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = self.intra_op_num_threads
            self.ort_session = ort.InferenceSession(yolo_config['model_path'], sess_options=sess_options)
            output_shapes = [output.shape for output in self.ort_session.get_outputs()]
            self.logger.info(f"Initialized ONNX model: {yolo_config['model_path']}, output shapes: {output_shapes}")
        except Exception as e:
            self.logger.error(f"Failed to load ONNX model: {e}")
            raise

        self.logger.info(f"SignDetector initialized with ONNX model, imgsz={self.imgsz}, confidence_threshold={self.confidence_threshold}, iou_threshold={self.iou_threshold}, intra_op_num_threads={self.intra_op_num_threads}, draw_boxes={self.draw_boxes}")

    def preprocess(self, frame):
        # Validate input frame
        if not isinstance(frame, np.ndarray):
            self.logger.error("Input frame is not a numpy array")
            raise ValueError("Input frame must be a numpy array")
        if frame.ndim != 3 or frame.shape[2] != 3:
            self.logger.error(f"Input frame has invalid shape: {frame.shape}")
            raise ValueError(f"Input frame must have shape (H, W, 3), got {frame.shape}")
        # Letterbox resize
        imgsz = self.imgsz
        if isinstance(imgsz, int):
            imgsz = (imgsz, imgsz)
        img, r, (dw, dh) = letterbox(frame, imgsz)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)
        img = np.expand_dims(img, axis=0)
        return img, r, (dw, dh)

    def postprocess(self, outputs):
        # Validate output shape
        if not isinstance(outputs, np.ndarray):
            self.logger.error("Model output is not a numpy array")
            raise ValueError("Model output must be a numpy array")
        if len(outputs.shape) not in [2, 3]:
            self.logger.error(f"Unexpected output shape: {outputs.shape}")
            raise ValueError(f"Unexpected output shape: {outputs.shape}")
        # Always transpose if output is [1, 19, 8400]
        if len(outputs.shape) == 3 and outputs.shape[0] == 1 and outputs.shape[1] == 19:
            outputs = outputs.transpose(0, 2, 1)  # [1, 8400, 19]
        outputs = outputs[0] if len(outputs.shape) == 3 else outputs  # [8400, 19] or [N, 19]
        num_classes = len(self.class_names)
        if outputs.shape[1] < 5 or outputs.shape[1] != 4 + 1 + num_classes:
            self.logger.error(f"Unexpected number of columns in output: {outputs.shape[1]}")
            raise ValueError(f"Unexpected number of columns in output: {outputs.shape[1]}")
        boxes = outputs[:, :4] # Bounding boxes
        scores = outputs[:, 4:] # Class scores
        self.logger.debug(f"Raw scores min/max/mean: {scores.min():.4f}/{scores.max():.4f}/{scores.mean():.4f}")
        scores = 1 / (1 + np.exp(-scores)) #Sigmoid activation
        self.logger.debug(f"Sigmoid scores min/max/mean: {scores.min():.4f}/{scores.max():.4f}/{scores.mean():.4f}")
        confidences = np.max(scores, axis=1) #Max class score
        class_ids = np.argmax(scores, axis=1) #Class with max score
        self.logger.debug(f"Detections before confidence filter: {len(confidences)}")
        mask = confidences >= self.confidence_threshold
        if not np.any(mask):
            self.logger.debug("No detections above confidence threshold")
            return [], [], []
        boxes = boxes[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]
        self.logger.debug(f"Detections after confidence filter: {len(boxes)}")
        # Convert boxes to xyxy
        if isinstance(self.imgsz, int):
            imgsz = (self.imgsz, self.imgsz)
        else:
            imgsz = self.imgsz
        boxes[:, [0, 2]] *= imgsz[0]
        boxes[:, [1, 3]] *= imgsz[1]
        boxes_xyxy = np.zeros_like(boxes)
        boxes_xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        boxes_xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        boxes_xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        boxes_xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        # NMS
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
        boxes[:, [0, 2]] /= imgsz[0]
        boxes[:, [1, 3]] /= imgsz[1]
        confidences = confidences[indices]
        class_ids = class_ids[indices]
        return boxes, confidences, class_ids

    def detect(self, frame):
        try:
            # Validate input
            if not isinstance(frame, np.ndarray):
                self.logger.error("Input frame is not a numpy array")
                return []
            if frame.ndim != 3 or frame.shape[2] != 3:
                self.logger.error(f"Input frame has invalid shape: {frame.shape}")
                return []
            print("[DEBUG] Starting detection...")
            start_time = time.time()
            preprocess_start = time.time()
            img, r, (dw, dh) = self.preprocess(frame)
            preprocess_time = time.time() - preprocess_start
            inference_start = time.time()
            outputs = self.ort_session.run(None, {'images': img})[0]
            print(f"[DEBUG] Model output shape: {outputs.shape}")
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
            output_img = None
            if self.draw_boxes and len(boxes) > 0:
                output_img = draw_boxes_on_image(frame, boxes, class_ids, confidences, self.class_names)
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
                    if self.draw_boxes and output_img is not None:
                        _, buffer = cv2.imencode('.jpg', output_img)
                        detection["image"] = base64.b64encode(buffer).decode('utf-8')
                    else:
                        detection["image"] = None
                detections.append(detection)
            print(f"[DEBUG] Number of detections: {len(detections)}")
            return detections
        except Exception as e:
            print(f"[DEBUG] Error during detection: {e}")
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

