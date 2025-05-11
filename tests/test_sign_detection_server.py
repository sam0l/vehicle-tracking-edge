import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import cv2
import logging
import yaml
import base64
import numpy as np
from flask import Flask, jsonify, request, Response
from src.sign_detection import SignDetector, draw_boxes_on_image
import threading
import time

# Load config
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

camera_config = config['camera']
test_server_config = config.get('test_server', {'host': '0.0.0.0', 'port': 8081})

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sign_detection_test_server")

detector = SignDetector('config/config.yaml')

# Camera initialization
cap = None
def init_camera():
    global cap
    device_id = camera_config.get('device_id', 0)
    cap = cv2.VideoCapture(device_id)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_config.get('width', 1280))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_config.get('height', 720))
    cap.set(cv2.CAP_PROP_FPS, camera_config.get('fps', 30))
    if not cap.isOpened():
        logger.error(f"Failed to open camera {device_id}")
        return False
    logger.info(f"Camera {device_id} opened successfully")
    return True

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/detect', methods=['GET'])
def detect():
    global cap
    if cap is None or not cap.isOpened():
        if not init_camera():
            return jsonify({'error': 'Camera not available'}), 500
    ret, frame = cap.read()
    if not ret or frame is None:
        logger.error("Failed to capture frame from camera")
        return jsonify({'error': 'Failed to capture frame'}), 500
    logger.info(f"Frame captured from camera: {frame.shape}")
    detections = detector.detect(frame)
    # Optionally include the frame with boxes as base64
    image_b64 = None
    if detector.draw_boxes and detector.send_images and len(detections) > 0:
        # The first detection will have the image if enabled
        for det in detections:
            if det.get('image'):
                image_b64 = det['image']
                break
    result = {
        'detections': detections,
        'image': image_b64
    }
    return jsonify(result)

def generate_video_stream():
    global cap
    while True:
        if cap is None or not cap.isOpened():
            if not init_camera():
                time.sleep(1)
                continue
        ret, frame = cap.read()
        if not ret or frame is None:
            logger.error("Failed to capture frame from camera for video stream")
            time.sleep(0.1)
            continue

        # Preprocess for detection (letterbox)
        img, r, (dw, dh) = detector.preprocess(frame)
        # Convert back to HWC uint8 for drawing (letterboxed 640x640)
        img_for_model = img[0].transpose(1, 2, 0)
        img_for_model = (img_for_model * 255).astype(np.uint8)
        img_for_model = cv2.cvtColor(img_for_model, cv2.COLOR_RGB2BGR)

        # Run detection (on the original frame, which will be letterboxed inside detect)
        detections = detector.detect(frame)
        boxes = [d['box'] for d in detections]
        class_ids = [detector.class_names.index(d['label']) for d in detections]
        confidences = [d['confidence'] for d in detections]
        if boxes:
            boxes = np.array(boxes)
            # Convert (cx, cy, w, h) in pixel space to (x1, y1, x2, y2)
            x1 = boxes[:, 0] - boxes[:, 2] / 2
            y1 = boxes[:, 1] - boxes[:, 3] / 2
            x2 = boxes[:, 0] + boxes[:, 2] / 2
            y2 = boxes[:, 1] + boxes[:, 3] / 2
            boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)
            print(f"[DEBUG] Drawing boxes (x1, y1, x2, y2): {boxes_xyxy}")
            img_for_model = draw_boxes_on_image(
                img_for_model,
                boxes_xyxy,
                np.array(class_ids),
                np.array(confidences),
                detector.class_names
            )

        ret, jpeg = cv2.imencode('.jpg', img_for_model)
        if not ret:
            logger.error("Failed to encode frame as JPEG for video stream")
            continue
        frame_bytes = jpeg.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """Stream live video with detection boxes as MJPEG."""
    return Response(generate_video_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_server():
    app.run(host=test_server_config.get('host', '0.0.0.0'), port=test_server_config.get('port', 8081), debug=False, use_reloader=False)

if __name__ == "__main__":
    logger.info(f"Starting sign detection test server on {test_server_config['host']}:{test_server_config['port']}")
    if not init_camera():
        logger.error("Camera initialization failed. Exiting.")
        exit(1)
    run_server() 