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

        # Get letterbox params for this frame
        imgsz = detector.imgsz
        if isinstance(imgsz, int):
            imgsz = (imgsz, imgsz)
        h, w = frame.shape[:2]
        r = min(imgsz[0] / h, imgsz[1] / w)
        new_unpad = (int(round(w * r)), int(round(h * r)))
        dw, dh = imgsz[1] - new_unpad[0], imgsz[0] - new_unpad[1]
        dw /= 2
        dh /= 2

        # Run detection
        detections = detector.detect(frame)
        logger.info(f'Detections this frame: {len(detections)}')
        if len(detections) > 0:
            boxes = []
            for d in detections:
                # Unletterbox (corrected for 640x360 letterboxed to 640x640)
                x1 = max(0, min(w, (d['box'][0] - dw) / r))
                y1 = max(0, min(h, (d['box'][1] - dh) / r))
                x2 = max(0, min(w, (d['box'][2] - dw) / r))
                y2 = max(0, min(h, (d['box'][3] - dh) / r))
                logger.info(f"Original detection box: {d['box']}")
                logger.info(f"Transformed box: {[x1, y1, x2, y2]}")
                boxes.append([x1, y1, x2, y2])
            class_ids = [detector.class_names.index(d['label']) for d in detections]
            confidences = [d['confidence'] for d in detections]
            # Log only label, confidence, and box (not image)
            first_det = detections[0]
            logger.info(f"First detection: label={first_det['label']}, conf={first_det['confidence']:.2f}, box={first_det['box']}")
            logger.info(f'Drawing on image of shape: {frame.shape}')
            logger.info(f'Boxes: {boxes}')
            frame = draw_boxes_on_image(
                frame,
                np.array(boxes),
                np.array(class_ids),
                np.array(confidences),
                detector.class_names
            )
        else:
            logger.info('No detections to draw.')

        # Encode as JPEG
        ret, jpeg = cv2.imencode('.jpg', frame)
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