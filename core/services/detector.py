"""YOLO detection service — the model is loaded once and shared across requests."""
import threading
from pathlib import Path

_lock = threading.Lock()
_model = None
_model_path = None
_seg_model = None
_seg_path = None
SETTINGS = {"iou": 0.7, "max_det": 300}  # set from app.py via create_app


def get_model(path, device=""):
    global _model, _model_path
    with _lock:
        if _model is None or _model_path != str(path):
            from ultralytics import YOLO

            if not Path(path).exists():
                raise FileNotFoundError(f"Model file not found: {path}")
            _model = YOLO(str(path))
            _model_path = str(path)
        return _model


def class_names(path):
    try:
        m = get_model(path)
        names = m.names
        return [names[i] for i in sorted(names)]
    except Exception:
        return ["crack", "hide_craze", "surface_eye"]


def predict(image_bgr, model_path, conf=0.25, imgsz=640, device=""):
    """Return list of detections: dict(class_name, confidence, box=[x1,y1,x2,y2] normalized)."""
    model = get_model(model_path, device)
    kw = {"conf": conf, "imgsz": imgsz, "verbose": False, "iou": SETTINGS["iou"], "max_det": SETTINGS["max_det"]}
    if device:
        kw["device"] = device
    with _lock:  # ultralytics models aren't thread-safe
        res = model.predict(image_bgr, **kw)[0]
    out = []
    if res.boxes is None or len(res.boxes) == 0:
        return out
    xyxyn = res.boxes.xyxyn.cpu().numpy()
    confs = res.boxes.conf.cpu().numpy()
    clss = res.boxes.cls.cpu().numpy().astype(int)
    for b, c, k in zip(xyxyn, confs, clss):
        x1, y1, x2, y2 = [float(max(0.0, min(1.0, v))) for v in b]
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        out.append({"class_name": res.names[int(k)], "confidence": float(c), "box": [x1, y1, x2, y2]})
    return out


def seg_available(seg_path):
    return bool(seg_path) and Path(seg_path).exists()


def mask_blade(image_bgr, seg_path, device=""):
    """Black out everything except the blade using a YOLO-seg model.

    Returns (image, applied). With no segmentation model configured this is a passthrough,
    so the toggle can be wired end-to-end now and the model dropped in later.
    """
    global _seg_model, _seg_path
    if not seg_available(seg_path):
        return image_bgr, False
    import cv2
    import numpy as np

    with _lock:
        if _seg_model is None or _seg_path != str(seg_path):
            from ultralytics import YOLO

            _seg_model = YOLO(str(seg_path))
            _seg_path = str(seg_path)
        kw = {"conf": 0.25, "verbose": False, "retina_masks": True}
        if device:
            kw["device"] = device
        res = _seg_model.predict(image_bgr, **kw)[0]
    if res.masks is None or len(res.masks) == 0:
        return image_bgr, False
    h, w = image_bgr.shape[:2]
    m = res.masks.data.cpu().numpy().max(axis=0)
    m = cv2.resize((m > 0.5).astype("uint8"), (w, h), interpolation=cv2.INTER_NEAREST)
    m = cv2.dilate(m, np.ones((15, 15), np.uint8))
    out = image_bgr.copy()
    out[m == 0] = 0
    return out, True
