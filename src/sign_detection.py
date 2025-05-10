import cv2
import base64
import logging
import numpy as np
import yaml
from ultralytics import YOLO

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

    def detect(self, frame):
        try:
            # Resize frame to fixed size expected by the model
            resized_frame = cv2.resize(frame, (self.imgsz, self.imgsz))

            # Run inference on resized frame
            results = self.model(resized_frame, verbose=False)

            detection_data = []
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    confidence = box.conf.item()
                    if confidence < self.confidence_threshold:
                        self.logger.debug(
                            f"Skipping detection with confidence {confidence:.3f} below threshold {self.confidence_threshold}"
                        )
                        continue

                    class_id = int(box.cls.item())
                    class_name = self.model.names[class_id]

                    self.logger.info(f"Detected {class_name} with confidence {confidence:.3f}")

                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    detection = {
                        "sign_type": f"{class_name}, {confidence*100:.0f}% certain ({confidence:.2f} confidence)",
                        "timestamp": np.datetime64('now').astype(str)
                    }

                    if self.send_images:
                        cropped = resized_frame[y1:y2, x1:x2]
                        _, buffer = cv2.imencode('.jpg', cropped)
                        detection["image"] = base64.b64encode(buffer).decode('utf-8')

                    detection_data.append(detection)

            return detection_data

        except Exception as e:
            self.logger.error(f"Error in detection: {e}")
            return []

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

