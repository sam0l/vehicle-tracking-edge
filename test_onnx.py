import onnxruntime as ort
import numpy as np

session = ort.InferenceSession('/root/vehicle-tracking-edge/models/yolov8n.onnx', providers=['CPUExecutionProvider'])
img = np.random.rand(1, 3, 640, 640).astype(np.float32)
outputs = session.run(None, {'images': img})[0]
print(f"Output shape: {outputs.shape}")
print(f"Raw scores min/max/mean: {outputs[:, 4:].min():.4f}/{outputs[:, 4:].max():.4f}/{outputs[:, 4:].mean():.4f}")
