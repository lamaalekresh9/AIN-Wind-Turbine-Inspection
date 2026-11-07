"""VLM cross-check of YOLO detections and score-level fusion.

For each frame that has detections, the VLM receives the clean image, the same image
with numbered YOLO boxes drawn on it, and the box list. It returns, per box, whether
it agrees there is a defect of that class, and it may report clear defects that YOLO
missed. The two opinions are fused into one score:

    confirmed / relabeled : fused = W_yolo * yolo_conf + W_vlm * vlm_conf
    rejected              : fused = W_yolo * yolo_conf + W_vlm * (1 - vlm_conf)
    added by VLM          : fused = W_vlm  * vlm_conf
"""
import json

import cv2
from flask import current_app

from . import ai_client, vlm_prompts
from .consolidate import iou
from .knowledge import default_severity

def _cfg(k, default=None):
    return current_app.config.get(k, default)


def _annotated(img, boxes):
    out = img.copy()
    h, w = out.shape[:2]
    lw = max(2, int(min(w, h) / 300))
    for i, b in enumerate(boxes, 1):
        x1, y1, x2, y2 = b
        p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
        cv2.rectangle(out, p1, p2, (0, 215, 255), lw)
        cv2.putText(out, f"#{i}", (p1[0] + 3, max(18, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.6, min(w, h) / 900), (0, 215, 255), lw, cv2.LINE_AA)
    return out


def _to1000(b):
    x1, y1, x2, y2 = b
    return [round(y1 * 1000), round(x1 * 1000), round(y2 * 1000), round(x2 * 1000)]


def _from1000(b):
    try:
        y1, x1, y2, x2 = [max(0.0, min(1.0, float(v) / 1000)) for v in b]
    except (TypeError, ValueError):
        return None
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    if x2 - x1 < 0.005 or y2 - y1 < 0.005:
        return None
    return [x1, y1, x2, y2]


def _crop(img, box, pad=1.5, min_side=160, out_side=512):
    """Zoomed view of one box with context, for small defects the full image shrinks away."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    bw, bh = max(x2 - x1, 1), max(y2 - y1, 1)
    side = max(bw, bh) * (1 + pad) if max(bw, bh) * (1 + pad) > min_side else min_side
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    X1, Y1 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    X2, Y2 = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
    c = img[Y1:Y2, X1:X2].copy()
    if c.size == 0:
        return None
    k = out_side / max(c.shape[:2])
    c = cv2.resize(c, (max(1, int(c.shape[1] * k)), max(1, int(c.shape[0] * k))),
                   interpolation=cv2.INTER_CUBIC if k > 1 else cv2.INTER_AREA)
    cv2.rectangle(c, (int((x1 - X1) * k), int((y1 - Y1) * k)), (int((x2 - X1) * k), int((y2 - Y1) * k)),
                  (0, 215, 255), 2)
    return c


def check_image(img_bgr, dets, class_names):
    """dets: list of {"class_name", "confidence", "box"} (normalized xyxy).
    Returns {"boxes": {idx: {...}}, "missed": [...]} with indices 0-based in dets order."""
    classes = list(class_names)
    listing = [{"id": i + 1, "class": d["class_name"], "detector_confidence": round(d["confidence"], 2)
                if d.get("confidence") is not None else None, "box": _to1000(d["box"])} for i, d in enumerate(dets)]
    images = [ai_client.jpeg_bytes(img_bgr)]
    order = ["Image 1: the original drone image (judge positions on this one)."]
    if dets:
        images.append(ai_client.jpeg_bytes(_annotated(img_bgr, [d["box"] for d in dets])))
        order.append("Image 2: the same image with the proposed boxes drawn in yellow and numbered #1, #2, ...")
        if _cfg("VLM_SEND_CROPS", True):
            for i, d in enumerate(dets[: int(_cfg("VLM_MAX_CROPS", 8))]):
                c = _crop(img_bgr, d["box"])
                if c is not None:
                    images.append(ai_client.jpeg_bytes(c, max_side=512, quality=90))
                    order.append(f"Image {len(images)}: zoomed crop of box #{i + 1} (box outlined in yellow).")
    prompt = ("\n".join(order) + "\n\nProposed boxes ([ymin, xmin, ymax, xmax], 0-1000 on Image 1):\n"
              + json.dumps(listing)
              + ("\nNo boxes were proposed for this image; only report clear missed defects." if not dets else ""))
    system = vlm_prompts.system_prompt(classes, _cfg("VLM_EXTRA_INSTRUCTIONS", ""))
    data = ai_client.generate_json(system, prompt, images, temperature=0.1, max_tokens=16384)
    out = {"boxes": {}, "missed": []}
    for b in data.get("boxes", []) or []:
        try:
            i = int(b.get("id")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(dets):
            continue
        verdict = str(b.get("verdict", "")).lower()
        if verdict not in ("confirmed", "relabeled", "rejected"):
            continue
        cls = b.get("class") if b.get("class") in classes else dets[i]["class_name"]
        if verdict == "relabeled" and cls == dets[i]["class_name"]:
            verdict = "confirmed"
        out["boxes"][i] = {"verdict": verdict, "class": cls, "confidence": _conf(b.get("confidence")),
                           "reason": _reason(b)}
    for m in data.get("missed", []) or []:
        box = _from1000(m.get("box"))
        if box and m.get("class") in classes:
            out["missed"].append({"class": m["class"], "box": box, "confidence": _conf(m.get("confidence")),
                                  "reason": _reason(m)})
    return out


def _reason(b):
    r = str(b.get("reason", "") or "").strip()
    loc = str(b.get("location", "") or "").strip()
    return (f"{r} (Location: {loc})" if loc and loc.lower() not in r.lower() else r)[:400]


def _conf(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.5


def fuse(yolo_conf, verdict, vlm_conf):
    wv = float(_cfg("VLM_WEIGHT", 0.4))
    wy = 1.0 - wv
    if verdict == "added":
        return round(wv * vlm_conf, 4)
    y = yolo_conf if yolo_conf is not None else 0.5
    if verdict == "rejected":
        return round(wy * y + wv * (1 - vlm_conf), 4)
    return round(wy * y + wv * vlm_conf, 4)


def apply_result(finding, res, user_note_prefix="VLM"):
    """Write one VLM verdict onto a Finding (fusion + optional relabel / auto-reject)."""
    finding.vlm_verdict = res["verdict"]
    finding.vlm_class = res["class"]
    finding.vlm_confidence = res["confidence"]
    finding.vlm_reason = res["reason"]
    finding.fused_confidence = fuse(finding.confidence, res["verdict"], res["confidence"])
    if res["verdict"] == "relabeled" and _cfg("VLM_RELABEL", True) and res["confidence"] >= (finding.confidence or 0):
        finding.class_name = res["class"]
        if finding.status == "pending":          # the starting severity follows the corrected type
            finding.severity = default_severity(finding.class_name,
                                                (finding.x2 - finding.x1) * (finding.y2 - finding.y1))
    if (res["verdict"] == "rejected" and _cfg("VLM_AUTO_REJECT", False)
            and finding.fused_confidence < float(_cfg("VLM_MIN_FUSED", 0.35)) and finding.status == "pending"):
        finding.status = "rejected"
        finding.reviewer_note = f"Auto-rejected: the VLM found no defect here ({res['reason']}). Restore it if you disagree."


def run_for_inspection(insp, progress=None):
    """Cross-check every frame that has AI findings. Returns (checked, note)."""
    from ..extensions import db
    from ..models import Finding
    from .worker import imread
    from pathlib import Path

    root = Path(current_app.config["UPLOAD_DIR"])
    class_names = _class_names()
    by_frame = {}
    for f in insp.findings:
        if f.source == "ai":
            by_frame.setdefault(f.frame_id, []).append(f)
    frames = [fr for fr in insp.frames if fr.id in by_frame]
    if _cfg("VLM_CHECK_EMPTY_IMAGES", True):
        frames += [fr for fr in insp.frames if fr.id not in by_frame and fr.media.kind == "image"]
    # most uncertain frames first, so a quota cut-off hurts least
    frames.sort(key=lambda fr: min((f.confidence or 1) for f in by_frame.get(fr.id, [])) if fr.id in by_frame else 2)
    limit = int(_cfg("VLM_MAX_FRAMES", 30))
    todo = frames[:limit]
    checked, added, note = 0, 0, None
    for n, fr in enumerate(todo, 1):
        if progress:
            progress(n, len(todo))
        img = imread(root / fr.image_path)
        if img is None:
            continue
        fs = by_frame.get(fr.id, [])
        dets = [{"class_name": f.ai_class_name or f.class_name, "confidence": f.confidence,
                 "box": [f.x1, f.y1, f.x2, f.y2]} for f in fs]
        try:
            res = check_image(img, dets, class_names)
        except ai_client.AIError as e:
            note = (f"Stopped after {checked} of {len(todo)} frames: "
                    + (f"rate limit reached ({e}). Run the check again in a minute." if e.quota else str(e)))
            break
        for i, f in enumerate(fs):
            if i in res["boxes"]:
                apply_result(f, res["boxes"][i])
        if _cfg("VLM_ADD_MISSED", True):
            existing = [[f.x1, f.y1, f.x2, f.y2] for f in insp.findings if f.frame_id == fr.id]
            for m in res["missed"]:
                if any(iou(m["box"], e) > 0.3 for e in existing):
                    continue
                if m["confidence"] < float(_cfg("VLM_MISSED_MIN_CONF", 0.6)):
                    continue
                x1, y1, x2, y2 = m["box"]
                nf = Finding(inspection_id=insp.id, frame_id=fr.id, class_name=m["class"], ai_class_name=m["class"],
                             confidence=None, x1=x1, y1=y1, x2=x2, y2=y2, source="vlm",
                             severity=default_severity(m["class"], (x2 - x1) * (y2 - y1)), status="pending",
                             vlm_verdict="added", vlm_class=m["class"], vlm_confidence=m["confidence"],
                             vlm_reason=m["reason"], fused_confidence=fuse(None, "added", m["confidence"]),
                             first_ts=fr.timestamp_s, last_ts=fr.timestamp_s, frame_ids=json.dumps([fr.id]))
                db.session.add(nf)
                existing.append(m["box"])
                added += 1
        checked += 1
        db.session.commit()
    skipped = len(frames) - len(todo)
    if note is None and skipped:
        note = f"Checked the {len(todo)} most uncertain frames; {skipped} more were skipped (VLM_MAX_FRAMES)."
    insp.vlm_frames_checked = checked
    insp.vlm_added = added
    insp.vlm_model = ai_client.settings()["model"]
    insp.vlm_status = "done" if note is None else ("partial" if checked else "failed")
    insp.vlm_note = note
    db.session.commit()
    return checked, note


def _class_names():
    from . import detector
    return detector.class_names(current_app.config["MODEL_PATH"])
