"""Background analysis: frames -> (optional blade mask) -> YOLO -> findings."""
import json
import shutil
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..extensions import db
from ..models import Finding, Frame, Inspection, Media
from . import detector
from .consolidate import consolidate
from .knowledge import default_severity


def imread(path):
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite(path, img, quality=90):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if ok:
        buf.tofile(str(path))
    return ok


def start(app, inspection_id):
    t = threading.Thread(target=_run, args=(app, inspection_id), daemon=True)
    t.start()
    return t


def _set(insp, progress=None, msg=None):
    if progress is not None:
        insp.progress = int(progress)
    if msg is not None:
        insp.progress_msg = msg
    db.session.commit()


def _new_finding(insp, frame, det, extra=None):
    x1, y1, x2, y2 = det["box"]
    f = Finding(
        inspection_id=insp.id,
        frame_id=frame.id,
        class_name=det["class_name"],
        ai_class_name=det["class_name"],
        confidence=det["confidence"],
        x1=x1, y1=y1, x2=x2, y2=y2,
        ai_box=json.dumps([round(v, 5) for v in det["box"]]),
        source="ai",
        severity=default_severity(det["class_name"], (x2 - x1) * (y2 - y1)),
        status="pending",
    )
    for k, v in (extra or {}).items():
        setattr(f, k, v)
    db.session.add(f)
    return f


def _run(app, inspection_id):
    with app.app_context():
        cfg = app.config
        insp = db.session.get(Inspection, inspection_id)
        if insp is None:
            return
        upload_root = Path(cfg["UPLOAD_DIR"])
        started = time.time()
        try:
            insp.status = "processing"
            insp.error = None
            insp.model_name = Path(cfg["MODEL_PATH"]).name
            _set(insp, 2, "Loading detection model")
            detector.get_model(cfg["MODEL_PATH"], cfg["MODEL_DEVICE"])

            seg_path = cfg.get("BLADE_SEG_MODEL_PATH")
            any_mask = False
            media = list(insp.media)
            n = max(1, len(media))
            conf = insp.conf_threshold or cfg["DEFAULT_CONF"]

            def run_det(img):
                nonlocal any_mask
                applied = False
                if insp.mask_enabled:
                    img, applied = detector.mask_blade(img, seg_path, cfg["MODEL_DEVICE"])
                    any_mask = any_mask or applied
                dets = detector.predict(img, cfg["MODEL_PATH"], conf, cfg["MODEL_IMGSZ"], cfg["MODEL_DEVICE"])
                return dets, applied

            from . import ai_client
            use_vlm = bool(insp.vlm_enabled and app.config.get("VLM_ENABLED") and ai_client.available())
            yolo_total = 55 if use_vlm else 90
            for mi, m in enumerate(media):
                base_p = 5 + yolo_total * mi / n
                span = yolo_total / n
                src = upload_root / m.stored_path
                if m.kind == "image":
                    _set(insp, base_p, f"Analyzing {m.original_name}")
                    img = imread(src)
                    if img is None:
                        raise ValueError(f"Could not read image {m.original_name}")
                    h, w = img.shape[:2]
                    m.width, m.height = w, h
                    dets, applied = run_det(img)
                    fr = Frame(inspection_id=insp.id, media_id=m.id, image_path=m.stored_path,
                               width=w, height=h, masked=applied, detections_count=len(dets))
                    db.session.add(fr)
                    db.session.flush()
                    for d in dets:
                        _new_finding(insp, fr, d, {"frame_ids": json.dumps([fr.id])})
                    db.session.commit()
                else:
                    _process_video(insp, m, src, upload_root, cfg, run_det, base_p, span)

            insp.mask_applied = any_mask
            if use_vlm:
                run_vlm_stage(insp, lambda i, k: _set(insp, 60 + 38 * i / max(1, k),
                                                       f"Cross-checking detections with the VLM ({i} of {k})"))
            elif insp.vlm_enabled:
                insp.vlm_status, insp.vlm_note = "failed", "No AI provider key configured, so the VLM check was skipped."
            insp.status = "draft"  # the inspector checks the AI results, then submits
            insp.analyzed_at = datetime.utcnow()
            insp.processing_seconds = round(time.time() - started, 2)
            msg = "Analysis complete"
            if insp.mask_enabled and not any_mask:
                msg += " (blade masking requested, no segmentation model configured: images analyzed unmasked)"
            _set(insp, 100, msg)
            from ..utils import audit
            audit("inspection.analyzed", "inspection", insp.id, inspection_id=insp.id,
                  user_id=insp.created_by_id, findings=len(insp.findings),
                  seconds=insp.processing_seconds, commit=True)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            insp = db.session.get(Inspection, inspection_id)
            insp.status = "failed"
            insp.error = f"{type(e).__name__}: {e}"
            insp.progress_msg = "Analysis failed"
            db.session.commit()
            traceback.print_exc()
            from ..utils import audit
            audit("inspection.failed", "inspection", insp.id, inspection_id=insp.id,
                  user_id=insp.created_by_id, error=str(e), commit=True)


def _process_video(insp, m, src, upload_root, cfg, run_det, base_p, span):
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ValueError(f"Could not open video {m.original_name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    m.fps = fps
    m.duration_s = round(total / fps, 2) if total else None
    interval = max(0.1, float(insp.frame_interval_s or cfg["DEFAULT_FRAME_INTERVAL"]))
    step = max(1, int(round(fps * interval)))
    max_frames = cfg["MAX_FRAMES_PER_VIDEO"]
    expected = min(max_frames, max(1, (total // step) + 1 if total else max_frames))

    frame_dir = Path(f"inspection_{insp.id}") / "frames" / f"media_{m.id}"
    collected = []  # (sample_idx, Frame, ts, dets)
    idx, sidx = 0, 0
    while sidx < max_frames:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, img = cap.retrieve()
            if not ok:
                break
            ts = idx / fps
            h, w = img.shape[:2]
            m.width, m.height = w, h
            rel = frame_dir / f"f_{idx:06d}.jpg"
            imwrite(upload_root / rel, img)
            dets, applied = run_det(img)
            fr = Frame(inspection_id=insp.id, media_id=m.id, image_path=rel.as_posix(),
                       frame_index=idx, timestamp_s=round(ts, 3), width=w, height=h,
                       masked=applied, detections_count=len(dets))
            db.session.add(fr)
            db.session.flush()
            collected.append((sidx, fr, ts, dets))
            sidx += 1
            if sidx % 5 == 0:
                _set(insp, base_p + span * 0.9 * min(1.0, sidx / expected),
                     f"{m.original_name}: frame {sidx} of ~{expected}")
        idx += 1
    cap.release()

    tracks = consolidate(
        [(s, fr, ts, d) for s, fr, ts, d in collected],
        cfg["DEDUP_IOU"], cfg["DEDUP_CENTER_DIST"], cfg["DEDUP_MAX_GAP"],
    )
    for t in tracks:
        _new_finding(insp, t["best_frame"], t["best"], {
            "occurrences": t["count"],
            "first_ts": round(t["first_ts"], 3),
            "last_ts": round(t["last_ts"], 3),
            "frame_ids": json.dumps([f.id for f in t["frames"]]),
        })
    db.session.commit()
    raw = sum(len(d) for *_, d in collected)
    _set(insp, base_p + span, f"{m.original_name}: {raw} detections merged into {len(tracks)} findings")


def run_vlm_stage(insp, progress=None):
    from . import vlm
    insp.vlm_status, insp.vlm_note = "running", None
    db.session.commit()
    try:
        vlm.run_for_inspection(insp, progress)
    except Exception as e:  # noqa: BLE001 — the VLM is optional; YOLO results stand on their own
        db.session.rollback()
        insp.vlm_status, insp.vlm_note = "failed", f"VLM check failed: {e}"
        db.session.commit()
        traceback.print_exc()


def start_vlm(app, inspection_id):
    def _job():
        with app.app_context():
            insp = db.session.get(Inspection, inspection_id)
            run_vlm_stage(insp, lambda i, k: _set(insp, None, f"Checked {i - 1} of {k} frames with the VLM"))
            from ..utils import audit
            audit("inspection.vlm", "inspection", insp.id, inspection_id=insp.id, user_id=insp.created_by_id,
                  status=insp.vlm_status, frames=insp.vlm_frames_checked, commit=True)
    t = threading.Thread(target=_job, daemon=True)
    t.start()
    return t


def reset_analysis(insp, upload_root):
    """Remove frames/findings so analysis can run again."""
    for m in list(insp.messages):
        db.session.delete(m)
    for f in list(insp.findings):
        db.session.delete(f)
    for fr in list(insp.frames):
        db.session.delete(fr)
    if insp.report:
        db.session.delete(insp.report)
    db.session.flush()
    frames_dir = Path(upload_root) / f"inspection_{insp.id}" / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    insp.status = "queued"
    insp.progress = 0
    insp.progress_msg = "Queued"
    insp.error = None
    insp.review_completed_at = None
    insp.review_completed_by_id = None
    insp.vlm_status = insp.vlm_note = None
    insp.vlm_frames_checked = insp.vlm_added = 0
    db.session.commit()


def recover_stuck(app):
    with app.app_context():
        for s in Inspection.query.filter_by(vlm_status="running").all():
            s.vlm_status, s.vlm_note = "failed", "Interrupted by a server restart. Run the VLM check again."
        stuck = Inspection.query.filter(Inspection.status.in_(["queued", "processing"])).all()
        for s in stuck:
            s.status = "failed"
            s.error = "The server restarted while this inspection was being analyzed. Run the analysis again."
            s.progress_msg = "Interrupted"
        db.session.commit()
