import cv2
import logging
import yaml
import base64
import numpy as np
from flask import Flask, jsonify, request
from src.sign_detection import SignDetector
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

def run_server():
    app.run(host=test_server_config.get('host', '0.0.0.0'), port=test_server_config.get('port', 8081), debug=False, use_reloader=False)

if __name__ == "__main__":
    logger.info(f"Starting sign detection test server on {test_server_config['host']}:{test_server_config['port']}")
    if not init_camera():
        logger.error("Camera initialization failed. Exiting.")
        exit(1)
    run_server() 