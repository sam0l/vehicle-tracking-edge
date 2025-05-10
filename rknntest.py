import cv2
import numpy as np
import yaml
from rknnlite.api import RKNNLite

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load config
config = load_config()
yolo_cfg = config.get("yolo", {})
camera_cfg = config.get("camera", {})

# Model and camera config
RKNN_MODEL_PATH = 'models/yolov8n_traffic_signs.rknn'
CAMERA_ID = camera_cfg['device_id']
INPUT_SIZE = (yolo_cfg['imgsz'], yolo_cfg['imgsz'])  # width, height

# Your model's class names
CLASS_NAMES = {
    0: 'Green Light', 1: 'Red Light', 2: 'Speed Limit 10', 3: 'Speed Limit 100',
    4: 'Speed Limit 110', 5: 'Speed Limit 120', 6: 'Speed Limit 20', 7: 'Speed Limit 30',
    8: 'Speed Limit 40', 9: 'Speed Limit 50', 10: 'Speed Limit 60', 11: 'Speed Limit 70',
    12: 'Speed Limit 80', 13: 'Speed Limit 90', 14: 'Stop'
}

# Replace with your actual output quantization parameters
OUTPUT_SCALE = 0.1
OUTPUT_ZERO_POINT = 0

def preprocess_frame(frame, input_size=INPUT_SIZE):
    img = cv2.resize(frame, input_size)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))  # HWC to CHW
    img = np.expand_dims(img, axis=0)   # Add batch dim
    return img

def sigmoid(x):
    return 1 / (1 + np.exp(-x))

def xywh2xyxy(x):
    y = np.zeros_like(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2  # x1
    y[:, 1] = x[:, 1] - x[:, 3] / 2  # y1
    y[:, 2] = x[:, 0] + x[:, 2] / 2  # x2
    y[:, 3] = x[:, 1] + x[:, 3] / 2  # y2
    return y

def nms(boxes, scores, iou_threshold=0.5):
    if boxes.shape[0] == 0:
        return []

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return keep

def postprocess_yolov8(output, conf_threshold=None, iou_threshold=None, input_size=INPUT_SIZE):
    conf_threshold = conf_threshold or yolo_cfg['confidence_threshold']
    iou_threshold = iou_threshold or yolo_cfg['iou_threshold']
    
    output = output[0]  # shape (19, N)
    num_classes = 15
    num_preds = output.shape[1]

    bbox = output[0:4, :].T  # (N,4)
    class_scores = output[4:4+num_classes, :].T  # (N,15)

    # Debug raw class scores before sigmoid
    print("Class scores sample before sigmoid:", class_scores[:5])

    class_scores = sigmoid(class_scores)

    # Debug class scores after sigmoid
    print("Class scores sample after sigmoid:", class_scores[:5])

    class_ids = np.argmax(class_scores, axis=1)
    confidences = class_scores[np.arange(num_preds), class_ids]

    mask = confidences > conf_threshold
    bbox = bbox[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]

    if bbox.shape[0] == 0:
        print("No detections above confidence threshold.")
        return

    # Scale bbox coords from normalized to pixel values
    bbox[:, 0] *= input_size[0]  # center_x * width
    bbox[:, 1] *= input_size[1]  # center_y * height
    bbox[:, 2] *= input_size[0]  # width * width
    bbox[:, 3] *= input_size[1]  # height * height

    boxes_xyxy = xywh2xyxy(bbox)

    # Clip boxes
    boxes_xyxy[:, [0, 2]] = np.clip(boxes_xyxy[:, [0, 2]], 0, input_size[0])
    boxes_xyxy[:, [1, 3]] = np.clip(boxes_xyxy[:, [1, 3]], 0, input_size[1])

    # Filter invalid boxes (width > 0 and height > 0)
    widths = boxes_xyxy[:, 2] - boxes_xyxy[:, 0]
    heights = boxes_xyxy[:, 3] - boxes_xyxy[:, 1]
    valid_mask = (widths > 0) & (heights > 0)

    boxes_xyxy = boxes_xyxy[valid_mask]
    confidences = confidences[valid_mask]
    class_ids = class_ids[valid_mask]

    if boxes_xyxy.shape[0] == 0:
        print("No valid bounding boxes after filtering invalid boxes.")
        return

    print(f"Number of boxes before NMS: {boxes_xyxy.shape[0]}")
    for i in range(min(5, boxes_xyxy.shape[0])):
        print(f"  Box {i}: {boxes_xyxy[i]}, conf: {confidences[i]:.3f}, class: {CLASS_NAMES.get(class_ids[i], 'Unknown')}")

    keep = nms(boxes_xyxy, confidences, iou_threshold)

    if len(keep) == 0:
        print("No boxes kept after NMS.")
        return

    for i in keep:
        box = boxes_xyxy[i]
        conf = confidences[i]
        cls_id = class_ids[i]
        print(f"Detected {CLASS_NAMES.get(cls_id, 'Unknown')} "
              f"conf: {conf:.2f} bbox: [{box[0]:.1f}, {box[1]:.1f}, {box[2]:.1f}, {box[3]:.1f}]")

def postprocess_output(output):
    print("Raw output shape:", output.shape)
    print("Raw output sample (first 20):", output.flatten()[:20])

    # Dequantize output
    output_dequant = (output.astype(np.float32) - OUTPUT_ZERO_POINT) * OUTPUT_SCALE
    print("Dequantized output sample (first 20):", output_dequant.flatten()[:20])

    postprocess_yolov8(output_dequant)

def main():
    rknn = RKNNLite()

    print('Loading RKNN model...')
    ret = rknn.load_rknn(RKNN_MODEL_PATH)
    if ret != 0:
        print('Failed to load RKNN model')
        return

    print('Initializing runtime environment...')
    ret = rknn.init_runtime()
    if ret != 0:
        print('Failed to initialize runtime environment')
        return

    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print('Failed to open camera')
        return

    # Set camera resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg['width'])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg['height'])

    print('Starting inference loop. Press Ctrl+C to stop.')

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print('Failed to read frame from camera')
                break

            input_data = preprocess_frame(frame)
            print('Input data shape:', input_data.shape, 'dtype:', input_data.dtype)

            outputs = rknn.inference(inputs=[input_data])
            print('Inference done. Number of outputs:', len(outputs))

            postprocess_output(outputs[0])

    except KeyboardInterrupt:
        print('Inference stopped by user')

    finally:
        cap.release()
        rknn.release()
        print('Resources released. Exiting.')

if __name__ == '__main__':
    main()

