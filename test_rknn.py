import cv2
import numpy as np
from rknnlite.api import RKNNLite
import time
import logging
import argparse

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
IMG_SIZE = 640  # Input size for YOLOv8 model
CLASSES = [
    'Green Light', 'Red Light', 'Speed Limit 10', 'Speed Limit 100', 'Speed Limit 110',
    'Speed Limit 120', 'Speed Limit 20', 'Speed Limit 30', 'Speed Limit 40', 'Speed Limit 50',
    'Speed Limit 60', 'Speed Limit 70', 'Speed Limit 80', 'Speed Limit 90', 'Stop'
]
RKNN_MODEL_PATH = 'models/newnewnew.rknn'
CONF_THRES = 0.01  # Lowered to capture scores up to 0.029
IOU_THRES = 0.45

def preprocess_image(image, input_size):
    """Preprocess image for YOLOv8 model (float32 input)."""
    logger.debug("Preprocessing image")
    if image is None or image.size == 0:
        logger.error("Invalid input image")
        raise ValueError("Invalid image")
    img = cv2.resize(image, (input_size, input_size))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0  # Normalize to [0, 1]
    img = np.transpose(img, (2, 0, 1))  # HWC to CHW
    img = np.expand_dims(img, axis=0)  # Add batch dimension
    logger.debug(f"Preprocessed image shape: {img.shape}, dtype: {img.dtype}, range: [{img.min():.3f}, {img.max():.3f}]")
    return img

def postprocess_outputs(outputs, img_shape, conf_thres=CONF_THRES, iou_thres=IOU_THRES):
    """Postprocess YOLOv8 float32 outputs."""
    logger.debug("Postprocessing outputs")
    if not outputs or len(outputs) == 0:
        logger.error("No outputs from RKNN inference")
        return [], [], []
    
    # Assuming outputs[0] is [1, 19, 8400] (4 boxes + 15 class scores)
    output = outputs[0]
    logger.debug(f"Raw output shape: {output.shape}, dtype: {output.dtype}, range: [{output.min():.3f}, {output.max():.3f}]")
    
    # Log raw tensor (first 10 values of up to 20 channels)
    for i in range(min(20, output.shape[1])):
        logger.debug(f"Raw output channel {i} (first 10): {output[0, i, :10].flatten()}")
    
    # No dequantization needed (float32 output)
    logger.debug("Using float32 output directly (no quantization)")
    
    # Transpose to [8400, 19, 1]
    output = output.transpose((2, 1, 0))  # [8400, 19, 1]
    logger.debug(f"Transposed output shape: {output.shape}")
    
    # Split boxes and scores (try channels 4–18 for scores)
    boxes = output[:, :4, 0]  # [8400, 4] (x1, y1, x2, y2 or center_x, center_y, w, h)
    scores = output[:, 4:19, 0]  # [8400, 15] (class scores)
    logger.debug(f"Boxes shape: {boxes.shape}, range: [{boxes.min():.3f}, {boxes.max():.3f}]")
    logger.debug(f"Boxes (first 5): {boxes[:5]}")
    logger.debug(f"Scores shape: {scores.shape}, range: [{scores.min():.3f}, {scores.max():.3f}]")
    logger.debug(f"Scores (first 5): {scores[:5]}")
    
    # Try alternative score channels (e.g., 5–19) if scores are zero
    if scores.max() < 0.01:
        logger.warning("Class scores near zero, trying alternative channels (5–19)")
        alt_scores = output[:, 5:20, 0] if output.shape[1] >= 20 else output[:, 5:, 0]
        logger.debug(f"Alternative scores shape: {alt_scores.shape}, range: [{alt_scores.min():.3f}, {alt_scores.max():.3f}]")
        logger.debug(f"Alternative scores (first 5): {alt_scores[:5]}")
    
    # Normalize boxes (assume center-based: cx, cy, w, h)
    boxes[:, 0] = boxes[:, 0] / IMG_SIZE  # Normalize cx
    boxes[:, 1] = boxes[:, 1] / IMG_SIZE  # Normalize cy
    boxes[:, 2] = boxes[:, 2] / IMG_SIZE  # Normalize w
    boxes[:, 3] = boxes[:, 3] / IMG_SIZE  # Normalize h
    logger.debug(f"Normalized boxes range: [{boxes.min():.3f}, {boxes.max():.3f}]")
    
    # Convert to corner-based (x1, y1, x2, y2)
    boxes[:, 0] = boxes[:, 0] - boxes[:, 2] / 2  # x1 = cx - w/2
    boxes[:, 1] = boxes[:, 1] - boxes[:, 3] / 2  # y1 = cy - h/2
    boxes[:, 2] = boxes[:, 0] + boxes[:, 2]      # x2 = cx + w/2
    boxes[:, 3] = boxes[:, 1] + boxes[:, 3]      # y2 = cy + h/2
    logger.debug(f"Corner-based boxes range: [{boxes.min():.3f}, {boxes.max():.3f}]")
    
    # Scale to original image
    h, w = img_shape
    scale_factor = min(IMG_SIZE / w, IMG_SIZE / h)
    pad_w = (IMG_SIZE - w * scale_factor) / 2
    pad_h = (IMG_SIZE - h * scale_factor) / 2
    
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] * IMG_SIZE - pad_w) / scale_factor
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] * IMG_SIZE - pad_h) / scale_factor
    logger.debug(f"Scaled boxes range: [{boxes.min():.3f}, {boxes.max():.3f}]")
    logger.debug(f"Scaled boxes (first 5): {boxes[:5]}")
    
    # Apply confidence threshold
    max_scores = np.max(scores, axis=1)
    max_classes = np.argmax(scores, axis=1)
    logger.debug(f"Max scores range: [{max_scores.min():.3f}, {max_scores.max():.3f}]")
    logger.debug(f"Max scores (first 10): {max_scores[:10]}")
    logger.debug(f"Max classes (first 10): {max_classes[:10]}")
    
    mask = max_scores > conf_thres
    boxes = boxes[mask]
    scores = max_scores[mask]
    classes = max_classes[mask]
    logger.debug(f"After conf threshold: {len(boxes)} detections")
    
    if len(boxes) == 0:
        logger.debug("No detections after confidence threshold")
        return [], [], []
    
    # Apply NMS
    indices = cv2.dnn.NMSBoxes(
        boxes.tolist(), scores.tolist(), conf_thres, iou_thres
    )
    if isinstance(indices, np.ndarray):
        indices = indices.flatten()
    logger.debug(f"After NMS: {len(indices)} detections")
    
    return boxes[indices], scores[indices], classes[indices]

def log_detections(boxes, scores, classes, fps):
    """Log detection results to console."""
    logger.info(f"FPS: {fps:.2f}")
    if len(boxes) == 0:
        logger.info("No detections")
        return
    logger.info(f"Detected {len(boxes)} objects:")
    for i, (box, score, cls) in enumerate(zip(boxes, scores, classes)):
        x1, y1, x2, y2 = map(int, box)
        logger.info(
            f"  {i+1}. Class: {CLASSES[cls]}, Score: {score:.2f}, "
            f"Box: [{x1}, {y1}, {x2}, {y2}]"
        )

def main(test_image=None):
    # Initialize RKNNLite
    logger.debug("Initializing RKNNLite")
    rknn = RKNNLite()
    ret = rknn.load_rknn(RKNN_MODEL_PATH)
    if ret != 0:
        logger.error("Failed to load RKNN model")
        return
    ret = rknn.init_runtime()
    if ret != 0:
        logger.error("Failed to initialize RKNN runtime")
        rknn.release()
        return
    logger.debug("RKNNLite initialized successfully")
    
    # Initialize input source
    if test_image is not None:
        logger.debug(f"Loading test image: {test_image}")
        frame = cv2.imread(test_image)
        if frame is None:
            logger.error(f"Failed to load test image: {test_image}")
            rknn.release()
            return
        # Process single image
        input_data = preprocess_image(frame, IMG_SIZE)
        logger.debug("Running RKNN inference")
        start_time = time.time()
        outputs = rknn.inference(inputs=[input_data])
        inference_time = time.time() - start_time
        logger.debug(f"Inference time: {inference_time:.3f}s")
        boxes, scores, classes = postprocess_outputs(outputs, frame.shape[:2])
        fps = 1.0 / inference_time if inference_time > 0 else 0
        log_detections(boxes, scores, classes, fps)
    else:
        logger.debug("Initializing camera")
        cap = cv2.VideoCapture(1)
        if not cap.isOpened():
            logger.error("Failed to open camera")
            rknn.release()
            return
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    logger.error("Failed to read frame")
                    break
                
                # Preprocess
                input_data = preprocess_image(frame, IMG_SIZE)
                
                # Inference
                logger.debug("Running RKNN inference")
                start_time = time.time()
                outputs = rknn.inference(inputs=[input_data])
                inference_time = time.time() - start_time
                logger.debug(f"Inference time: {inference_time:.3f}s")
                
                # Postprocess
                boxes, scores, classes = postprocess_outputs(
                    outputs, frame.shape[:2]
                )
                
                # Log results
                fps = 1.0 / inference_time if inference_time > 0 else 0
                log_detections(boxes, scores, classes, fps)
                
                # Small sleep to prevent excessive CPU usage
                time.sleep(0.01)
        
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        
        finally:
            cap.release()
    
    rknn.release()
    logger.info("Resources released")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RKNN YOLOv8 model")
    parser.add_argument("--test-image", type=str, help="Path to test image for single inference")
    args = parser.parse_args()
    main(test_image=args.test_image)
