"""Runtime settings an admin can change from the UI (stored in the DB, override app.py)."""
from .extensions import db
from .models import AppSetting

# key -> (type, label, help, min, max)
EDITABLE = {
    "ALLOW_SIGNUP": (bool, "Allow self sign-up", "New accounts are created as Inspectors.", None, None),
    "DEFAULT_CONF": (float, "Default YOLO confidence", "Prefilled on new inspections and Live detection.", 0.05, 0.95),
    "MAX_FRAMES_PER_VIDEO": (int, "Max frames per video", "Frames analyzed per uploaded video.", 10, 2000),
    "VLM_ENABLED": (bool, "VLM cross-check", "Ask the VLM to confirm, reject or relabel every YOLO box.", None, None),
    "VLM_AUTO_REJECT": (bool, "Pre-reject likely false alarms", "Reviewers can still restore them.", None, None),
    "VLM_MIN_FUSED": (float, "False-alarm threshold", "Combined YOLO + VLM score below which a disputed box is flagged.", 0.05, 0.95),
    "VLM_MAX_FRAMES": (int, "Max frames per VLM check", "Protects the AI quota on long videos.", 1, 500),
    "LLM_REPORT_ENABLED": (bool, "LLM-written Arabic report", "Off = offline Arabic templates.", None, None),
    "CHAT_ENABLED": (bool, "Ask Ain chat", "AI chat about inspections and Live detection images.", None, None),
}


def _cast(kind, raw):
    if kind is bool:
        return str(raw).lower() in ("1", "true", "on", "yes")
    return kind(raw)


def load(app):
    with app.app_context():
        for s in AppSetting.query.all():
            if s.key in EDITABLE:
                try:
                    app.config[s.key] = _cast(EDITABLE[s.key][0], s.value)
                except (TypeError, ValueError):
                    pass


def save(app, form, user_id):
    """Validate and store submitted values. Returns a list of error messages."""
    errors = []
    for key, (kind, label, _help, lo, hi) in EDITABLE.items():
        vals = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
        raw = vals[-1] if vals and vals[-1] is not None else None  # checkbox "on" comes after the hidden "off"
        if raw is None:
            continue
        try:
            val = _cast(kind, raw)
        except (TypeError, ValueError):
            errors.append(f"{label}: enter a number.")
            continue
        if lo is not None and not (lo <= val <= hi):
            errors.append(f"{label}: must be between {lo} and {hi}.")
            continue
        row = db.session.get(AppSetting, key) or AppSetting(key=key)
        row.value = str(val)
        row.updated_by_id = user_id
        db.session.add(row)
        app.config[key] = val
    db.session.commit()
    return errors
