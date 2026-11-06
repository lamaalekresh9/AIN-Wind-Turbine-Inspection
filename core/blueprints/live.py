"""Live detection: browser camera, uploaded video streamed with boxes, and single images.

Quick-check tool. Nothing here is saved as an inspection; use New inspection for the
reviewed, reportable workflow.
"""
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from flask import (Blueprint, Response, abort, current_app, jsonify, render_template, request)
from flask_login import current_user, login_required

import json

from ..permissions import ADMIN, INSPECTOR, roles
from ..services import ai_client, detector, vlm
from ..services import chat as chat_service
from ..services.knowledge import class_catalog, info

bp = Blueprint("live", __name__, url_prefix="/live")

SESSIONS = {}  # token -> {"path", "conf", "realtime", "stop", "stats", "created"}
_lock = threading.Lock()
SESSION_TTL = 3600


def _cfg():
    c = current_app.config
    return c["MODEL_PATH"], c["MODEL_IMGSZ"], c["MODEL_DEVICE"]


def _decode(file_storage):
    data = np.frombuffer(file_storage.read(), np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _bgr(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def draw(img, dets):
    h, w = img.shape[:2]
    lw = max(2, int(min(w, h) / 300))
    fs = max(0.45, min(w, h) / 1100)
    for d in dets:
        x1, y1, x2, y2 = d["box"]
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        col = _bgr(info(d["class_name"])["color"])
        cv2.rectangle(img, p1, p2, col, lw)
        label = f"{d['class_name']} {d['confidence']:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, max(1, lw - 1))
        ty = p1[1] - th - 8 if p1[1] - th - 8 > 0 else p1[1] + 2
        cv2.rectangle(img, (p1[0], ty), (p1[0] + tw + 8, ty + th + 8), col, -1)
        cv2.putText(img, label, (p1[0] + 4, ty + th + 3), cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255),
                    max(1, lw - 1), cv2.LINE_AA)
    return img


def _cleanup():
    now = time.time()
    with _lock:
        for tok in [t for t, s in SESSIONS.items() if now - s["created"] > SESSION_TTL]:
            s = SESSIONS.pop(tok)
            s["stop"] = True
            Path(s["path"]).unlink(missing_ok=True)


@bp.route("/")
@login_required
@roles(INSPECTOR, ADMIN)
def index():
    names = detector.class_names(current_app.config["MODEL_PATH"])
    return render_template("live.html", classes=class_catalog(names),
                           default_conf=current_app.config["DEFAULT_CONF"], ai=ai_client.status())


@bp.route("/vlm", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def vlm_check():
    """YOLO + VLM cross-check on one image; returns fused results."""
    if not ai_client.available():
        return jsonify(error="No AI key is set in .env, so the VLM check isn't available."), 400
    f = request.files.get("image")
    img = _decode(f) if f else None
    if img is None:
        return jsonify(error="That file isn't a readable image."), 400
    conf = min(0.95, max(0.05, request.form.get("conf", type=float) or current_app.config["DEFAULT_CONF"]))
    mp, imgsz, dev = _cfg()
    dets = detector.predict(img, mp, conf, imgsz, dev)
    t = time.perf_counter()
    try:
        res = vlm.check_image(img, dets, detector.class_names(mp))
    except ai_client.AIError as e:
        msg = f"{e}. Wait a minute and try again." if e.quota else str(e)
        return jsonify(error=f"VLM check failed: {msg}"), 502
    ms = (time.perf_counter() - t) * 1000
    out = []
    for i, d in enumerate(dets):
        v = res["boxes"].get(i)
        d = dict(d)
        if v:
            d.update(vlm_verdict=v["verdict"], vlm_class=v["class"], vlm_confidence=v["confidence"],
                     vlm_reason=v["reason"], fused=vlm.fuse(d["confidence"], v["verdict"], v["confidence"]))
            if v["verdict"] == "relabeled" and current_app.config.get("VLM_RELABEL") and v["confidence"] >= d["confidence"]:
                d["class_name"] = v["class"]
        out.append(d)
    for m in res["missed"]:
        if m["confidence"] >= float(current_app.config.get("VLM_MISSED_MIN_CONF", 0.6)):
            out.append({"class_name": m["class"], "confidence": None, "box": m["box"], "vlm_verdict": "added",
                        "vlm_class": m["class"], "vlm_confidence": m["confidence"], "vlm_reason": m["reason"],
                        "fused": vlm.fuse(None, "added", m["confidence"])})
    h, w = img.shape[:2]
    return jsonify(detections=out, ms=round(ms), width=w, height=h, model=ai_client.settings()["model"],
                   min_fused=current_app.config.get("VLM_MIN_FUSED", 0.35))


@bp.route("/detect", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def detect():
    """Detect on one image (camera frame or uploaded photo). Returns normalized boxes."""
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image received."), 400
    img = _decode(f)
    if img is None:
        return jsonify(error="That file isn't a readable image."), 400
    conf = min(0.95, max(0.05, request.form.get("conf", type=float) or current_app.config["DEFAULT_CONF"]))
    mp, imgsz, dev = _cfg()
    t = time.perf_counter()
    dets = detector.predict(img, mp, conf, imgsz, dev)
    ms = (time.perf_counter() - t) * 1000
    h, w = img.shape[:2]
    return jsonify(detections=dets, ms=round(ms, 1), width=w, height=h)


@bp.route("/video", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def upload_video():
    _cleanup()
    f = request.files.get("video")
    exts = current_app.config["ALLOWED_VIDEO_EXT"]
    if not f or "." not in f.filename or f.filename.rsplit(".", 1)[1].lower() not in exts:
        return jsonify(error="Upload an MP4, MOV, AVI or MKV video."), 400
    d = Path(current_app.config["UPLOAD_DIR"]) / "live"
    d.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    path = d / f"{token}.{f.filename.rsplit('.', 1)[1].lower()}"
    f.save(path)
    cap = cv2.VideoCapture(str(path))
    ok = cap.isOpened()
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    if not ok:
        path.unlink(missing_ok=True)
        return jsonify(error="The video couldn't be opened. Try re-exporting it as MP4 (H.264)."), 400
    with _lock:
        SESSIONS[token] = {"owner": current_user.id, "path": str(path), "conf": current_app.config["DEFAULT_CONF"], "realtime": True,
                           "stop": False, "created": time.time(), "name": f.filename,
                           "stats": {"frame": 0, "total": total, "fps": fps, "ms": 0, "detections": [],
                                     "counts": {}, "done": False, "processed": 0}}
    return jsonify(token=token, total=total, fps=round(fps, 2), duration=round(total / fps, 1) if total else None)


def _session(token):
    s = SESSIONS.get(token)
    if not s or s.get("owner") != current_user.id:
        abort(404)
    return s


@bp.route("/video/<token>/settings", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def video_settings(token):
    s = _session(token)
    data = request.get_json(silent=True) or {}
    if "conf" in data:
        s["conf"] = min(0.95, max(0.05, float(data["conf"])))
    if "realtime" in data:
        s["realtime"] = bool(data["realtime"])
    if data.get("stop"):
        s["stop"] = True
    return jsonify(ok=True)


@bp.route("/video/<token>/stats")
@login_required
@roles(INSPECTOR, ADMIN)
def video_stats(token):
    return jsonify(_session(token)["stats"])


@bp.route("/video/<token>/stream")
@login_required
@roles(INSPECTOR, ADMIN)
def video_stream(token):
    s = _session(token)
    mp, imgsz, dev = _cfg()
    s["stop"] = False

    def gen():
        cap = cv2.VideoCapture(s["path"])
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        st = s["stats"]
        st.update(frame=0, counts={}, done=False, processed=0, detections=[])
        idx = 0
        started = time.perf_counter()
        try:
            while not s["stop"]:
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                if max(h, w) > 1280:  # keep the stream light
                    k = 1280 / max(h, w)
                    frame = cv2.resize(frame, (int(w * k), int(h * k)))
                t = time.perf_counter()
                dets = detector.predict(frame, mp, s["conf"], imgsz, dev)
                ms = (time.perf_counter() - t) * 1000
                for d in dets:
                    st["counts"][d["class_name"]] = st["counts"].get(d["class_name"], 0) + 1
                st.update(frame=idx, ms=round(ms, 1), detections=dets, time=round(idx / fps, 2),
                          processed=st["processed"] + 1)
                draw(frame, dets)
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"
                idx += 1
                if s["realtime"]:
                    # skip frames so playback keeps pace with the video's real clock
                    target = int((time.perf_counter() - started) * fps)
                    while idx < target:
                        if not cap.grab():
                            break
                        idx += 1
                    ahead = idx / fps - (time.perf_counter() - started)
                    if ahead > 0:
                        time.sleep(min(ahead, 0.2))
        finally:
            cap.release()
            st["done"] = True

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})


@bp.route("/chat", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def live_chat():
    """Ask about the image currently shown in the Image tab (stateless: history comes from the browser)."""
    f = request.files.get("image")
    img = _decode(f) if f else None
    if img is None:
        return jsonify(error="Load an image first."), 400
    q = (request.form.get("question") or "").strip()[:2000]
    if not q:
        return jsonify(error="Type a question first."), 400
    try:
        dets = json.loads(request.form.get("detections") or "[]")[:50]
        history = json.loads(request.form.get("history") or "[]")[-8:]
    except ValueError:
        dets, history = [], []
    dets = [d for d in dets if isinstance(d, dict) and isinstance(d.get("box"), list) and len(d["box"]) == 4]
    answer, mode = chat_service.answer_live(img, dets, history, q)
    return jsonify(answer=answer, mode=mode)
