import yaml
from rknnlite.api import RKNNLite
import cv2
import numpy as np

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load config
config = load_config()
yolo_cfg = config.get("yolo", {})
camera_cfg = config.get("camera", {})

# Class names from data.yaml
CLASS_NAMES = ['Green Light', 'Red Light', 'Speed Limit 10', 'Speed Limit 100', 'Speed Limit 110', 
               'Speed Limit 120', 'Speed Limit 20', 'Speed Limit 30', 'Speed Limit 40', 'Speed Limit 50', 
               'Speed Limit 60', 'Speed Limit 70', 'Speed Limit 80', 'Speed Limit 90', 'Stop']

# Initialize RKNNLite
rknn = RKNNLite()
ret = rknn.load_rknn('models/yolov8n_traffic_signs.rknn')
if ret != 0:
    print('Failed to load RKNN model!')
    exit(ret)

ret = rknn.init_runtime()
if ret != 0:
    print('Failed to initialize RKNN runtime!')
    exit(ret)

# Initialize camera
cap = cv2.VideoCapture(camera_cfg['device_id'])
if not cap.isOpened():
    print('Failed to open camera!')
    exit(-1)

# Set camera resolution
cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg['width'])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg['height'])

def postprocess(outputs, conf_thres=None, iou_thres=None):
    """Post-process YOLOv8 outputs (assuming standard YOLOv8 output format)."""
    conf_thres = conf_thres or yolo_cfg['confidence_threshold']
    iou_thres = iou_thres or yolo_cfg['iou_threshold']
    
    boxes, scores, classes = outputs[0].transpose(1, 0)  # [1, 8400, 4+nc] -> [4+nc, 8400]
    boxes = boxes[:4].T  # [8400, 4]
    scores = scores.T  # [8400, nc]
    classes = np.argmax(scores, axis=1)  # [8400]
    scores = np.max(scores, axis=1)  # [8400]

    # Apply NMS
    indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), conf_thres, iou_thres)
    detections = []
    for i in indices:
        score = scores[i]
        if score > conf_thres:
            box = boxes[i]
            class_id = classes[i]
            detections.append({
                'class': CLASS_NAMES[class_id],
                'confidence': score,
                'box': box  # [x, y, w, h]
            })
    return detections

# Inference loop
try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print('Failed to read frame!')
            continue

        # Preprocess frame
        img = cv2.resize(frame, (yolo_cfg['imgsz'], yolo_cfg['imgsz']))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0  # Normalize to [0, 1]
        img = img.transpose(2, 0, 1)  # HWC to CHW (NCHW for RKNN)

        # Perform inference
        outputs = rknn.inference(inputs=[img])

        # Post-process outputs
        detections = postprocess(outputs)

        # Print detections
        for det in detections:
            box = det['box']
            print(f"Class: {det['class']}, Confidence: {det['confidence']:.3f}, "
                  f"Box: [x={box[0]:.1f}, y={box[1]:.1f}, w={box[2]:.1f}, h={box[3]:.1f}]")

except KeyboardInterrupt:
    print('Inference stopped by user.')

# Cleanup
cap.release()
rknn.release()
