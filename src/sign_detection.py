import cv2
import base64
import logging
import numpy as np
import yaml
import time
from datetime import datetime
import onnxruntime as ort
from typing import Tuple, Union

try:
    import tengine as tg
    TENGINE_AVAILABLE = True
except ImportError:
    TENGINE_AVAILABLE = False
    tg = None

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
    for box, class_id, conf in zip(boxes, class_ids, confidences):
        x1 = int(box[0])
        y1 = int(box[1])
        x2 = int(box[2])
        y2 = int(box[3])
        label = f"{class_names[class_id]}: {conf:.2f}"
        color = (0, 255, 0)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    return img

class SignDetector:
    def __init__(self, config_path='config/config.yaml'):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG) # Explicitly set level for this logger
        self.logger.critical("--- SignDetector __init__ CALLED (logger level set to DEBUG explicitly) ---")
        self.config = load_config(config_path)
        yolo_config = self.config['yolo']
        self.imgsz = yolo_config['imgsz']
        self.confidence_threshold = yolo_config['confidence_threshold']
        self.iou_threshold = yolo_config['iou_threshold']
        self.send_images = yolo_config.get('send_images', True)
        self.class_names = yolo_config.get('class_names', [])
        self.intra_op_num_threads = yolo_config.get('intra_op_num_threads', 4)
        self.draw_boxes = yolo_config.get('draw_boxes', False)

        # Tengine Initialization
        self.tengine_ctx = None
        self.tengine_graph = None
        self.tengine_input_tensor = None
        self.tengine_output_tensor = None # Assuming single output for now
        self.use_tengine = False
        self.model_path = yolo_config['model_path'] # Store for convenience

        self.logger.debug(f"SignDetector: TENGINE_AVAILABLE = {TENGINE_AVAILABLE}")
        self.logger.debug(f"SignDetector: yolo_config.get('tengine_enable', False) = {yolo_config.get('tengine_enable', False)}")
        if TENGINE_AVAILABLE and yolo_config.get('tengine_enable', False):
            try:
                self.logger.info("Attempting to initialize Tengine (using .context.Context and .graph.Graph)...")
                self.logger.debug(f"Tengine: Using model_path: {self.model_path}")
                self.tengine_ctx = tg.context.Context("") # Provide empty string for 'name' argument
                self.logger.info("Tengine: Context created.")
                
                tengine_model_format = yolo_config.get('tengine_model_format', 'onnx') # Default to onnx if not specified
                self.logger.debug(f"Tengine: Using model_format: {tengine_model_format}")
                self.logger.info(f"Tengine: Attempting to create graph with model: {self.model_path}, format: {tengine_model_format}")
                self.tengine_graph = tg.graph.Graph(self.tengine_ctx, tengine_model_format, self.model_path)
                self.logger.info("Tengine: Graph created successfully.")

                self.tengine_input_tensor = self.tengine_graph.getInputTensor(0,0)
                self.logger.debug(f"--- TENGINE INPUT TENSOR DEBUG --- dir(self.tengine_input_tensor): {dir(self.tengine_input_tensor)}")
                try:
                    # Attempt to get shape if a 'shape' attribute or 'get_shape' method exists
                    if hasattr(self.tengine_input_tensor, 'shape') and self.tengine_input_tensor.shape is not None:
                        self.logger.debug(f"Tengine input_tensor.shape: {self.tengine_input_tensor.shape}")
                    elif hasattr(self.tengine_input_tensor, 'get_shape') and callable(self.tengine_input_tensor.get_shape):
                        self.logger.debug(f"Tengine input_tensor.get_shape(): {self.tengine_input_tensor.get_shape()}")
                    else:
                        self.logger.debug("Tengine input_tensor does not have a direct .shape attribute or .get_shape() method visible here.")
                    # You might also want to log other attributes like name, dtype if available from dir()
                    if hasattr(self.tengine_input_tensor, 'name'):
                         self.logger.debug(f"Tengine input_tensor.name: {self.tengine_input_tensor.name}")
                    if hasattr(self.tengine_input_tensor, 'data_type'): # or dtype, etc.
                         self.logger.debug(f"Tengine input_tensor.data_type: {self.tengine_input_tensor.data_type}")

                except Exception as e_tensor_debug:
                    self.logger.error(f"Error during Tengine input_tensor debug: {e_tensor_debug}")
                self.logger.debug("--- END TENGINE INPUT TENSOR DEBUG ---")
                # Tengine might require explicit shape setting for the input tensor if it's dynamic
                # For YOLO, input shape is usually fixed, e.g., [1, 3, imgsz, imgsz]
                # input_dims_from_model = self.tengine_input_tensor.dims # e.g. [1, 3, 640, 640]
                # self.tengine_input_tensor.shape = input_dims_from_model # Set it if needed

                self.tengine_output_tensor = self.tengine_graph.getOutputTensor(0,0)
                
                # Some Tengine versions/models might benefit from or require a prerun after loading
                # self.tengine_graph.prerun()
                
                self.use_tengine = True
                self.logger.info(f"Tengine initialized successfully with model: {self.model_path} (Format: {tengine_model_format})")
            # self.logger.info(f"Tengine Input Tensor Dims: {self.tengine_input_tensor.dims}, Output Tensor Dims: {self.tengine_output_tensor.dims}") # Commented out due to AttributeError with .dims
            except Exception as e_tengine_init:
                self.logger.error(f"Tengine graph initialization FAILED. Error: {e_tengine_init}", exc_info=True)
                self.logger.warning("Tengine was enabled but graph is not available due to the error above. Falling back to ONNX Runtime if available.")
                self.use_tengine = False
                # Clean up partial Tengine resources if any step failed
                if self.tengine_graph: del self.tengine_graph
                if self.tengine_ctx: del self.tengine_ctx
                self.tengine_graph, self.tengine_ctx = None, None
        elif not TENGINE_AVAILABLE and yolo_config.get('tengine_enable', False):
            self.logger.warning("Tengine is enabled in config, but the 'tengine' Python library was not found.")
        else:
            self.logger.info("Tengine is not enabled in config or not available. Will attempt ONNX Runtime.")

        # Initialize ONNX model (as fallback or primary if Tengine Lite fails/unavailable)
        self.ort_session = None # Initialize to None
        try:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = self.intra_op_num_threads

            available_providers = ort.get_available_providers()
            self.logger.info(f"Available ONNX Runtime Execution Providers: {available_providers}")

            # Preferred execution providers for ARM Mali: ACL, then OpenCL, then CPU
            # Ensure your ONNX Runtime build for ARM64 includes these providers.
            preferred_providers = []
            if 'ACLExecutionProvider' in available_providers:
                preferred_providers.append('ACLExecutionProvider')
            if 'OpenCLExecutionProvider' in available_providers:
                preferred_providers.append('OpenCLExecutionProvider')
            preferred_providers.append('CPUExecutionProvider') # Always include CPU as a fallback

            self.logger.info(f"Attempting to initialize ONNX session with providers: {preferred_providers}")
            self.ort_session = ort.InferenceSession(yolo_config['model_path'], sess_options=sess_options, providers=preferred_providers)
            
            current_provider = self.ort_session.get_providers()
            self.logger.info(f"ONNX Runtime session initialized with provider(s): {current_provider}")
            if not any(ep in ['ACLExecutionProvider', 'OpenCLExecutionProvider'] for ep in current_provider):
                self.logger.warning("ONNX Runtime is NOT using a GPU Execution Provider (ACL or OpenCL). Inference will run on CPU.")
            output_shapes = [output.shape for output in self.ort_session.get_outputs()]
            self.logger.info(f"Initialized ONNX model: {yolo_config['model_path']}, output shapes: {output_shapes}")
        except Exception as e:
            self.logger.error(f"Failed to load ONNX model during ONNX Runtime setup: {e}")
            # Do not raise here if Tengine Lite is already successfully initialized and is the primary
            if not self.use_tengine:
                self.logger.error("Both Tengine and ONNX Runtime failed to initialize.")
                raise # Raise only if Tengine Lite is not available as primary

        if self.use_tengine:
            self.logger.info(f"SignDetector initialized. Primary Engine: Tengine. Fallback: ONNX Runtime (if initialized).")
        elif self.ort_session:
            self.logger.info(f"SignDetector initialized. Primary Engine: ONNX Runtime (Tengine unavailable/disabled or failed).")
        else:
            self.logger.error("SignDetector critical failure: NO inference engine (Tengine or ONNX Runtime) could be initialized.")
        self.logger.info(f"SignDetector params: imgsz={self.imgsz}, confidence_threshold={self.confidence_threshold}, iou_threshold={self.iou_threshold}, draw_boxes={self.draw_boxes}")

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
            self.logger.debug(f"Transposing output from shape {outputs.shape} to (1, 8400, 19)")
            outputs = outputs.transpose(0, 2, 1)  # [1, 8400, 19]
        outputs = outputs[0] if len(outputs.shape) == 3 else outputs  # [8400, 19] or [N, 19]
        num_classes = len(self.class_names)
        expected_cols = 4 + num_classes
        if outputs.shape[1] != expected_cols:
            self.logger.error(f"Model output columns: {outputs.shape[1]}, expected: {expected_cols} (4 box + {num_classes} classes)")
            self.logger.error(f"First row of output: {outputs[0] if outputs.shape[0] > 0 else 'N/A'}")
            raise ValueError(f"Unexpected number of columns in output: {outputs.shape[1]}")
        self.logger.debug(f"Model output shape after processing: {outputs.shape}")
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
        self.logger.debug(f"Running NMS on {len(boxes_xyxy)} boxes")
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
            self.logger.debug("Starting detection...")
            start_time = time.time()
            preprocess_start = time.time()
            img, r, (dw, dh) = self.preprocess(frame)
            preprocess_time = time.time() - preprocess_start
            inference_start = time.time()
            outputs = None

            if self.use_tengine and self.tengine_graph:
                try:
                    self.logger.debug("Running inference with Tengine...")
                    # Ensure input_data is C-contiguous and float32 for Tengine
                    contiguous_img = np.ascontiguousarray(img, dtype=np.float32)
                    self.tengine_input_tensor.buf = contiguous_img
                    self.tengine_graph.run()
                    outputs = self.tengine_output_tensor.buf # Get the output buffer
                    # The .shape attribute might not exist on the buffer directly.
                    # We'll address how to get Tengine output shape/dims later if needed.
                    # For now, let's confirm inference runs.
                    # self.logger.debug(f"Tengine inference successful. Output shape: {outputs.shape}") 
                except Exception as e_tengine_runtime:
                    self.logger.error(f"Tengine runtime inference failed: {e_tengine_runtime}. Falling back to ONNX Runtime.", exc_info=True)
                    self.use_tengine = False # Disable Tengine for subsequent calls
                    outputs = None # Ensure ONNX path is taken
            
            # Fallback to ONNX Runtime if Tengine is not used or failed
            elif self.ort_session:
                self.logger.debug("Using ONNX Runtime for inference.")
                try:
                    outputs = self.ort_session.run(None, {'images': img})[0]
                except Exception as e_onnx_runtime:
                    self.logger.error(f"ONNX Runtime inference failed: {e_onnx_runtime}", exc_info=True)
                    outputs = None # Explicitly set to None on ONNX failure too
            else:
                self.logger.error("Fallback ONNX Runtime session not available and Tengine failed or was not used.")
                # No engine, cannot proceed, outputs remains None

            if outputs is None:
                self.logger.error("No inference engine available (Tengine or ONNX Runtime).")
                return [] # Return empty list if no output could be generated
                
            self.logger.debug(f"Model output shape after inference: {outputs.shape}")
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
            # Always draw boxes on the letterboxed image for output
            if len(boxes) > 0:
                # Convert normalized boxes to 640x640 pixel coordinates
                boxes_px = np.array(boxes) * 640
                # Prepare the letterboxed image for drawing
                img_for_model = img[0].transpose(1, 2, 0)
                img_for_model = (img_for_model * 255).astype(np.uint8)
                img_for_model = cv2.cvtColor(img_for_model, cv2.COLOR_RGB2BGR)
                output_img = draw_boxes_on_image(img_for_model, boxes_px, class_ids, confidences, self.class_names)
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
                # Always include the image with boxes if there are detections
                if output_img is not None:
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

