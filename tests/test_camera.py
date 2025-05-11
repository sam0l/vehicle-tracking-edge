import yaml
from src.camera import Camera
from src.sign_detection import SignDetector
import cv2
import logging

logging.basicConfig(level=logging.INFO)

def test_camera():
    config_path = "config/config.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    camera_config = config["camera"]
    
    camera = Camera(
        camera_config["device_id"],
        camera_config["width"],
        camera_config["height"],
        camera_config["fps"]
    )
    detector = SignDetector(config_path)
    
    if camera.initialize() and detector.initialize():
        while True:
            frame = camera.get_frame()
            if frame is not None:
                detections = detector.detect(frame)
                for det in detections:
                    x1, y1, x2, y2 = det["bbox"]
                    label = det["label"]
                    conf = det["confidence"]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1-10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                cv2.imshow("Camera", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        camera.close()
        detector.close()
        cv2.destroyAllWindows()
    else:
        print("Camera or detector initialization failed")

if __name__ == "__main__":
    test_camera()
