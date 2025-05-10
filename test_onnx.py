import onnxruntime as ort
import numpy as np
import yaml

def load_config(config_path="config/config.yaml"):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)

# Load config
config = load_config()
yolo_cfg = config.get("yolo", {})

session = ort.InferenceSession(yolo_cfg['onnx_model_path'], providers=['CPUExecutionProvider'])
img = np.random.rand(1, 3, yolo_cfg['imgsz'], yolo_cfg['imgsz']).astype(np.float32)
outputs = session.run(None, {'images': img})[0]
print(f"Output shape: {outputs.shape}")
print(f"Raw scores min/max/mean: {outputs[:, 4:].min():.4f}/{outputs[:, 4:].max():.4f}/{outputs[:, 4:].mean():.4f}")
