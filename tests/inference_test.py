import sys
import os
import cv2
import logging
import yaml
import numpy as np
import threading
import time
import datetime
import csv

# Ensure the src directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.sign_detection import SignDetector, draw_boxes_on_image

# --- Configuration ---
MAX_CYCLES = 300
LOG_FILE_NAME = "inference_log.csv"

# --- Global Variables ---
exit_flag = False
all_log_data = []

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("inference_test_script")

# --- Early Exit Monitor ---
def monitor_input():
    global exit_flag
    while not exit_flag:
        try:
            if sys.stdin.isatty():
                user_input = input("Type 'x' and press Enter to exit early: \\n")
                if user_input.strip().lower() == 'x':
                    logger.info("Exit command received. Shutting down gracefully...")
                    exit_flag = True
                    break
            else:
                # If not a TTY, can't get input, sleep to prevent busy loop
                time.sleep(0.5)
        except EOFError: # Happens if stdin is closed
            logger.warning("EOFError on stdin, input monitoring thread stopping.")
            break
        except Exception as e:
            logger.error(f"Error in input monitoring thread: {e}")
            break
    logger.info("Input monitoring thread finished.")

# --- Main Test Logic ---
def run_inference_test():
    global exit_flag, all_log_data

    # Load config
    try:
        with open('config/config.yaml', 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("Error: config/config.yaml not found. Exiting.")
        return
    except Exception as e:
        logger.error(f"Error loading config/config.yaml: {e}. Exiting.")
        return

    camera_config = config.get('camera', {})
    detector_config_path = 'config/config.yaml' # Assuming SignDetector uses this

    logger.info(f"Initializing SignDetector with config: {detector_config_path}")
    try:
        detector = SignDetector(detector_config_path)
    except Exception as e:
        logger.error(f"Failed to initialize SignDetector: {e}. Exiting.")
        return

    # Camera initialization
    cap = None
    try:
        device_id = camera_config.get('device_id', 0)
        logger.info(f"Attempting to open camera {device_id}...")
        cap = cv2.VideoCapture(device_id)
        if not cap.isOpened(): # First check
             # Try with alternative backend if first attempt fails
            logger.warning(f"Failed to open camera {device_id} with default backend. Trying CAP_DSHOW.")
            cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)

        if not cap.isOpened(): # Second check
            logger.error(f"Failed to open camera {device_id} even with CAP_DSHOW. Exiting.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_config.get('width', 1280))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_config.get('height', 720))
        cap.set(cv2.CAP_PROP_FPS, camera_config.get('fps', 30))
        logger.info(f"Camera {device_id} opened successfully.")
    except Exception as e:
        logger.error(f"Exception during camera initialization: {e}. Exiting.")
        if cap:
            cap.release()
        return

    # Start input monitoring thread
    input_thread = threading.Thread(target=monitor_input, daemon=True)
    input_thread.start()

    logger.info(f"Starting inference test for {MAX_CYCLES} cycles...")

    for cycle_num in range(1, MAX_CYCLES + 1):
        if exit_flag:
            logger.info(f"Early exit initiated at cycle {cycle_num}.")
            break

        cycle_metrics = {'cycle': cycle_num, 'timestamp': datetime.datetime.now().isoformat()}
        t_cycle_start = time.perf_counter()

        # 1. Frame Read
        t_read_start = time.perf_counter()
        ret, frame = cap.read()
        t_read_end = time.perf_counter()
        cycle_metrics['frame_read_ms'] = (t_read_end - t_read_start) * 1000
        
        if not ret or frame is None:
            logger.error(f"Cycle {cycle_num}: Failed to capture frame. Skipping cycle.")
            cycle_metrics.update({
                'preprocess_for_drawing_ms': 0,
                'detect_pipeline_ms': 0,
                'drawing_on_img_ms': 0,
                'total_cycle_ms': (time.perf_counter() - t_cycle_start) * 1000
            })
            all_log_data.append(cycle_metrics)
            time.sleep(0.1) # Avoid busy loop on continuous frame read errors
            continue
        
        original_frame_copy = frame.copy() # For detection
        preprocess_frame_copy = frame.copy() # For preparing drawing canvas

        # 2. Preprocess for Drawing Canvas
        t_prep_draw_start = time.perf_counter()
        # Replicate logic from generate_video_stream to get img_for_model
        img_tensor, ratio, (dw, dh) = detector.preprocess(preprocess_frame_copy)
        img_for_model = img_tensor[0].transpose(1, 2, 0)  # CHW to HWC
        img_for_model = (img_for_model * 255).astype(np.uint8)
        img_for_model = cv2.cvtColor(img_for_model, cv2.COLOR_RGB2BGR) # Assuming model output is RGB
        t_prep_draw_end = time.perf_counter()
        cycle_metrics['preprocess_for_drawing_ms'] = (t_prep_draw_end - t_prep_draw_start) * 1000

        # 3. Detection Pipeline (includes internal preproc, inference, internal postproc)
        t_detect_start = time.perf_counter()
        detections = detector.detect(original_frame_copy)
        t_detect_end = time.perf_counter()
        cycle_metrics['detect_pipeline_ms'] = (t_detect_end - t_detect_start) * 1000
        
        # 4. Drawing on Image (external post-processing)
        t_draw_start = time.perf_counter()
        if detections:
            boxes = [d['box'] for d in detections] # (cx, cy, w, h) relative to original
            class_ids = [detector.class_names.index(d['label']) for d in detections if d['label'] in detector.class_names]
            confidences = [d['confidence'] for d in detections]

            if boxes and len(boxes) == len(class_ids) == len(confidences): # Ensure consistency
                boxes_np = np.array(boxes)
                # Convert (cx, cy, w, h) to (x1, y1, x2, y2) - still relative to original frame
                x1 = boxes_np[:, 0] - boxes_np[:, 2] / 2
                y1 = boxes_np[:, 1] - boxes_np[:, 3] / 2
                x2 = boxes_np[:, 0] + boxes_np[:, 2] / 2
                y2 = boxes_np[:, 1] + boxes_np[:, 3] / 2
                boxes_xyxy_original = np.stack([x1, y1, x2, y2], axis=1)

                # Scale boxes to img_for_model (letterboxed image)
                # dw, dh are total padding; ratio is the scaling factor
                # Padding is (dw, dh), so actual padding on each side is (dw/2, dh/2)
                pad_x, pad_y = dw / 2, dh / 2
                
                boxes_xyxy_scaled = boxes_xyxy_original.copy()
                boxes_xyxy_scaled[:, [0, 2]] = boxes_xyxy_scaled[:, [0, 2]] * ratio + pad_x # Scale x and add padding offset
                boxes_xyxy_scaled[:, [1, 3]] = boxes_xyxy_scaled[:, [1, 3]] * ratio + pad_y # Scale y and add padding offset
                
                # Clip boxes to the dimensions of img_for_model
                img_h, img_w = img_for_model.shape[:2]
                boxes_xyxy_scaled[:, [0, 2]] = np.clip(boxes_xyxy_scaled[:, [0, 2]], 0, img_w -1)
                boxes_xyxy_scaled[:, [1, 3]] = np.clip(boxes_xyxy_scaled[:, [1, 3]], 0, img_h -1)
                
                # Ensure x1 < x2 and y1 < y2 after clipping
                valid_boxes_mask = (boxes_xyxy_scaled[:, 0] < boxes_xyxy_scaled[:, 2]) & (boxes_xyxy_scaled[:, 1] < boxes_xyxy_scaled[:, 3])
                
                if np.any(valid_boxes_mask):
                    draw_boxes_on_image(
                        img_for_model, # Draw on the letterboxed image
                        boxes_xyxy_scaled[valid_boxes_mask],
                        np.array(class_ids)[valid_boxes_mask],
                        np.array(confidences)[valid_boxes_mask],
                        detector.class_names
                    )
        t_draw_end = time.perf_counter()
        cycle_metrics['drawing_on_img_ms'] = (t_draw_end - t_draw_start) * 1000
        
        t_cycle_end = time.perf_counter()
        cycle_metrics['total_cycle_ms'] = (t_cycle_end - t_cycle_start) * 1000
        
        all_log_data.append(cycle_metrics)
        logger.info(
            f"Cycle {cycle_num}/{MAX_CYCLES} completed. "
            f"Read: {cycle_metrics['frame_read_ms']:.2f}ms, "
            f"PrepDraw: {cycle_metrics['preprocess_for_drawing_ms']:.2f}ms, "
            f"Detect: {cycle_metrics['detect_pipeline_ms']:.2f}ms, "
            f"Draw: {cycle_metrics['drawing_on_img_ms']:.2f}ms, "
            f"Total: {cycle_metrics['total_cycle_ms']:.2f}ms"
        )

    # --- End of Test ---
    logger.info("Inference test finished.")
    exit_flag = True # Signal input_thread to exit if it hasn't already

    if cap and cap.isOpened():
        logger.info("Releasing camera.")
        cap.release()

    # Save data to CSV
    if all_log_data:
        logger.info(f"Saving log data to {LOG_FILE_NAME}...")
        fieldnames = [
            'timestamp', 'cycle', 'frame_read_ms', 'preprocess_for_drawing_ms', 
            'detect_pipeline_ms', 'drawing_on_img_ms', 'total_cycle_ms'
        ]
        try:
            with open(LOG_FILE_NAME, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_log_data)
            logger.info(f"Log data successfully saved to {LOG_FILE_NAME}.")
        except IOError as e:
            logger.error(f"Failed to write CSV file: {e}")

        # Calculate and print summary
        print_summary()
    else:
        logger.info("No data logged.")

def print_summary():
    if not all_log_data:
        print("\\nNo data to summarize.")
        return

    num_cycles = len(all_log_data)
    metrics_to_summarize = [
        'frame_read_ms', 'preprocess_for_drawing_ms', 
        'detect_pipeline_ms', 'drawing_on_img_ms', 'total_cycle_ms'
    ]
    
    summary_stats = {metric: {'total': 0, 'count': 0} for metric in metrics_to_summarize}

    for record in all_log_data:
        for metric in metrics_to_summarize:
            if metric in record and isinstance(record[metric], (int, float)):
                summary_stats[metric]['total'] += record[metric]
                summary_stats[metric]['count'] += 1
    
    print("\\n--- Performance Summary ---")
    print(f"Total cycles completed: {num_cycles}")
    print(f"{'Metric':<30} | {'Total (ms)':<15} | {'Average (ms)':<15}")
    print("-" * 65)

    for metric, stats in summary_stats.items():
        total_val = stats['total']
        avg_val = total_val / stats['count'] if stats['count'] > 0 else 0
        print(f"{metric:<30} | {total_val:<15.2f} | {avg_val:<15.2f}")
    
    print("-" * 65)
    if 'detect_pipeline_ms' in summary_stats:
        print("\\nNote: 'detect_pipeline_ms' includes internal preprocessing, model inference, and internal post-processing (e.g., NMS).")

if __name__ == "__main__":
    run_inference_test()
    logger.info("Script finished.") 