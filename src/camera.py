import cv2
import logging
import time

class Camera:
    def __init__(self, device_id, width, height, fps):
        self.logger = logging.getLogger(__name__)
        self.device_id = device_id
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None

    def initialize(self):
        try:
            # Try V4L2 backend first
            self.cap = cv2.VideoCapture(self.device_id, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                self.logger.warning(f"Failed to open camera {self.device_id} with V4L2, trying default backend")
                self.cap.release()
                self.cap = cv2.VideoCapture(self.device_id)

            if not self.cap.isOpened():
                self.logger.error(f"Failed to open camera {self.device_id}")
                return False

            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

            # Verify settings
            actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            actual_fourcc = int(self.cap.get(cv2.CAP_PROP_FOURCC)).to_bytes(4, 'little').decode('utf-8')

            if (abs(actual_width - self.width) > 1 or
                abs(actual_height - self.height) > 1 or
                actual_fourcc != 'MJPG'):
                self.logger.error(f"Camera settings mismatch: "
                                 f"width={actual_width}/{self.width}, "
                                 f"height={actual_height}/{self.height}, "
                                 f"fps={actual_fps}/{self.fps}, "
                                 f"fourcc={actual_fourcc}/MJPG")
                self.cap.release()
                self.cap = None
                return False

            self.logger.info(f"Camera initialized: {self.device_id}, "
                            f"{self.width}x{self.height}, {self.fps} FPS, MJPG")
            return True

        except Exception as e:
            self.logger.error(f"Error initializing camera {self.device_id}: {e}")
            if self.cap:
                self.cap.release()
                self.cap = None
            return False

    def get_frame(self):
        if not self.cap or not self.cap.isOpened():
            self.logger.warning(f"Camera {self.device_id} not initialized or closed")
            return None
        try:
            ret, frame = self.cap.read()
            if not ret:
                self.logger.warning(f"Failed to capture frame from {self.device_id}")
                return None
            return frame
        except Exception as e:
            self.logger.error(f"Error capturing frame from {self.device_id}: {e}")
            return None

    def close(self):
        if self.cap:
            self.cap.release()
            self.logger.info(f"Camera {self.device_id} closed")
        self.cap = None
