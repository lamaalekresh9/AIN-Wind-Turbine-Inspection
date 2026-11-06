"""AI chat about an inspection's detections and VLM results ("Ask Ain").

The model sees: the inspection details, every finding (YOLO class + confidence, VLM verdict, confidence
and reason, combined score, review status, severity, reviewer note, where it is), the reference text
for each defect type, and a few evidence crops. It answers in the language of the question.
"""
import json
import re
from pathlib import Path

from flask import current_app

from ..models import fmt_ts
from . import ai_client
from .evidence import crop, grid_location
from .knowledge import GENERAL_REFERENCES_AR, SEVERITY_EN, info

SYSTEM = """You are "Ain Assistant", a wind turbine blade inspection expert built into the Ain inspection platform.
You help inspectors and reviewers understand the results of ONE inspection: what YOLO detected, what the VLM
(vision-language model) cross-check concluded, how serious each finding may be, and what to do next.

Rules:
- Answer in the same language as the user's question (Arabic -> clear Modern Standard Arabic, English -> English).
- Base statements about THIS inspection only on the CONTEXT and the attached evidence images. Refer to findings by
  their codes (e.g. F-0003). Never invent findings, measurements in cm/m, dates or numbers that aren't in the context.
- You may add general engineering knowledge about blade defects, causes, risks and maintenance practice, but make it
  clear when something is general knowledge rather than a result of this inspection.
- Explain disagreements honestly: if YOLO and the VLM disagree, say so and say what the reviewer should look at.
- "pending" findings are not yet reviewed by a human; "accepted" ones are approved; "rejected" were dismissed;
  "uncertain" need re-inspection. Make this distinction when it matters.
- Ain is decision support: never certify a blade as safe, never predict exact remaining life or failure dates.
  For safety-critical questions, recommend inspection by a qualified technician.
- Be concise and practical: short paragraphs or bullet points, no filler. Use **bold** sparingly.
- If the question has nothing to do with this inspection or blade inspection, say briefly that you can only help
  with this inspection.

Return JSON only: {"answer": "<your answer>"}"""


def available():
    return bool(current_app.config.get("CHAT_ENABLED")) and ai_client.available()


def _finding_ctx(f):
    loc_en, _ = grid_location(f)
    d = {
        "code": f.code,
        "type": f.class_name,
        "type_name": info(f.class_name)["en"],
        "detected_by": {"ai": "YOLO", "vlm": "VLM only (YOLO missed it)", "manual": "added by reviewer"}.get(f.source, f.source),
        "yolo_class": f.ai_class_name if f.source == "ai" else None,
        "yolo_confidence": round(f.confidence, 2) if f.confidence is not None else None,
        "vlm_verdict": f.vlm_verdict or "not checked",
        "vlm_class": f.vlm_class,
        "vlm_confidence": round(f.vlm_confidence, 2) if f.vlm_confidence is not None else None,
        "vlm_reason": f.vlm_reason or "",
        "combined_score": round(f.fused_confidence, 2) if f.fused_confidence is not None else None,
        "review_status": f.status,
        "severity": SEVERITY_EN.get(f.severity, f.severity),
        "position_in_image": loc_en,
        "box_size_pct_of_image": round(f.area * 100, 2),
        "evidence": f.frame.label if f.frame else "",
        "reviewer_note": f.reviewer_note or "",
        "edited_by_reviewer": bool(f.edited),
    }
    if f.frame and f.frame.media and f.frame.media.kind == "video":
        d["video_time"] = f"{fmt_ts(f.first_ts)}-{fmt_ts(f.last_ts)}"
        d["frames_seen"] = f.occurrences
    return d


def build_context(insp):
    classes = sorted({f.class_name for f in insp.findings})
    refs = {c: {"what_it_is": info(c)["summary_en"], "reference_ar": info(c)["ref_ar"],
                "if_untreated_ar": info(c)["risk_ar"], "inspection_ar": info(c)["inspect_ar"],
                "maintenance_ar": info(c)["maintain_ar"]} for c in classes}
    c = insp.counts()
    return {
        "inspection": {
            "code": insp.code, "title": insp.title or "", "status": insp.status_label,
            "turbine": insp.turbine.code, "turbine_model": f"{insp.turbine.manufacturer or ''} {insp.turbine.model or ''}".strip(),
            "site": insp.turbine.site, "region": insp.turbine.region or "",
            "blade": insp.blade.label if insp.blade else "not specified",
            "flight_date": insp.inspection_date.isoformat() if insp.inspection_date else "",
            "drone": insp.drone_model or "", "weather": insp.weather or "", "inspector_notes": insp.notes or "",
            "media": [{"file": m.original_name, "kind": m.kind, "duration_s": m.duration_s} for m in insp.media],
            "yolo_model": insp.model_name, "yolo_confidence_threshold": insp.conf_threshold,
            "vlm_check": {"status": insp.vlm_status or "off", "model": insp.vlm_model, "frames_checked": insp.vlm_frames_checked,
                          "note": insp.vlm_note or ""},
            "review": {"accepted": c["accepted"], "rejected": c["rejected"], "uncertain": c["uncertain"],
                       "pending": c["pending"], "completed_by": insp.review_completed_by.name if insp.review_completed_by else None},
            "report": insp.report.status if insp.report else "not generated",
        },
        "findings": [_finding_ctx(f) for f in insp.findings],
        "defect_references": refs,
        "platform_limitations": GENERAL_REFERENCES_AR,
        "fusion_rule": "combined = 0.6*YOLO + 0.4*VLM (VLM confidence inverted when it rejects)",
    }


def _pick_images(insp, focus, question):
    """Evidence crops for the findings the question is most likely about."""
    n = int(current_app.config.get("CHAT_MAX_IMAGES", 4))
    if n <= 0:
        return [], []
    by_code = {f.code: f for f in insp.findings}
    chosen = []
    if focus:
        chosen.append(focus)
    for code in re.findall(r"F-\d{4}", question.upper()):
        if code in by_code and by_code[code] not in chosen:
            chosen.append(by_code[code])
    sev = {"high": 0, "medium": 1, "low": 2}
    rest = sorted((f for f in insp.findings if f not in chosen and f.status != "rejected"),
                  key=lambda f: (f.vlm_verdict != "rejected", sev.get(f.severity, 3), -(f.fused_confidence or f.confidence or 0)))
    chosen += rest
    root = Path(current_app.config["UPLOAD_DIR"])
    imgs, codes = [], []
    for f in chosen[:n]:
        out = root / f"inspection_{insp.id}" / "evidence" / f"crop_{f.id}.jpg"
        try:
            crop(root / f.frame.image_path, f, out)
            imgs.append(out.read_bytes())
            codes.append(f.code)
        except Exception:  # noqa: BLE001
            continue
    return imgs, codes


def answer(insp, question, history, focus=None):
    """Returns (answer_text, mode). mode = 'ai' or 'offline'."""
    if not available():
        return _offline(insp, question), "offline"
    ctx = build_context(insp)
    images, codes = _pick_images(insp, focus, question)
    convo = "\n".join(f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}" for m in history[-8:])
    prompt = (
        "CONTEXT (JSON):\n" + json.dumps(ctx, ensure_ascii=False)
        + (f"\n\nAttached evidence crops, in order: {', '.join(codes)} (each crop shows the finding's box)." if codes else "")
        + (f"\n\nThe user selected finding {focus.code} for this question." if focus else "")
        + (f"\n\nConversation so far:\n{convo}" if convo else "")
        + f"\n\nUser question:\n{question}"
    )
    try:
        data = ai_client.generate_json(SYSTEM, prompt, images, temperature=0.3, max_tokens=8192)
    except ai_client.AIError as e:
        current_app.logger.warning("Chat failed: %s", e)
        return f"⚠️ The AI assistant isn't available right now ({e}).", "error"
    text = str(data.get("answer") or "").strip() if isinstance(data, dict) else ""
    return (text or "I couldn't produce an answer. Try rephrasing the question."), "ai"


def _offline(insp, q):
    c = insp.counts()
    ar = bool(re.search(r"[؀-ۿ]", q))
    if not insp.findings:
        return "لم يرصد النظام أي عيوب في هذا الفحص." if ar else "No findings were detected in this inspection."
    lines = [f"{f.code}: {info(f.class_name)['ar' if ar else 'en']} · "
             f"{(f.confidence or 0):.0%} · {f.vlm_label if not ar else (f.vlm_verdict or '-')} · {f.status}" for f in insp.findings]
    head = (f"المساعد الذكي يحتاج مفتاح API في ملف .env. ملخص الفحص: {c['total']} نتائج "
            f"({c['accepted']} مقبولة، {c['pending']} قيد المراجعة):" if ar else
            f"The AI chat needs an API key in .env. Summary: {c['total']} findings "
            f"({c['accepted']} accepted, {c['pending']} pending):")
    return head + "\n" + "\n".join(lines)


def answer_live(img_bgr, dets, history, question):
    """Chat about a single Live-detection image (nothing is stored)."""
    if not available():
        return "The AI chat needs an API key in .env.", "offline"
    from .vlm import _annotated  # same yellow numbered boxes the VLM saw
    items = []
    for i, d in enumerate(dets, 1):
        x1, y1, x2, y2 = d["box"]
        items.append({
            "id": f"#{i}", "type": d.get("class_name"), "yolo_confidence": d.get("confidence"),
            "vlm_verdict": d.get("vlm_verdict") or "not checked", "vlm_class": d.get("vlm_class"),
            "vlm_confidence": d.get("vlm_confidence"), "vlm_reason": d.get("vlm_reason") or "",
            "combined_score": d.get("fused"), "box_xyxy_normalized": [round(v, 3) for v in (x1, y1, x2, y2)],
        })
    images = [ai_client.jpeg_bytes(img_bgr)]
    if dets:
        images.append(ai_client.jpeg_bytes(_annotated(img_bgr, [d["box"] for d in dets])))
    convo = "\n".join(f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}" for m in history[-8:])
    prompt = ("This is a quick Live-detection check of one image (not a saved inspection). Image 1 is the photo; "
              + ("Image 2 shows the detections numbered #1, #2, ... in yellow. " if dets else "")
              + "\nDETECTIONS (JSON):\n" + json.dumps(items, ensure_ascii=False)
              + "\nDEFECT REFERENCES:\n" + json.dumps({c: info(c)["summary_en"] for c in {d.get("class_name") for d in dets}},
                                                       ensure_ascii=False)
              + (f"\n\nConversation so far:\n{convo}" if convo else "")
              + f"\n\nUser question:\n{question}")
    system = SYSTEM.replace("ONE inspection", "ONE image checked on the Live detection page").replace(
        "Refer to findings by\n  their codes (e.g. F-0003)", "Refer to detections by\n  their numbers (e.g. #2)")
    try:
        data = ai_client.generate_json(system, prompt, images, temperature=0.3, max_tokens=8192)
    except ai_client.AIError as e:
        return f"⚠️ The AI assistant isn't available right now ({e}).", "error"
    text = str(data.get("answer") or "").strip() if isinstance(data, dict) else ""
    return (text or "I couldn't produce an answer. Try rephrasing the question."), "ai"
