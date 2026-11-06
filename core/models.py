import json
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager

ROLES = ("inspector", "reviewer", "admin")
ROLE_LABELS = {"inspector": "Inspector", "reviewer": "Human Reviewer", "admin": "Admin"}
ASSIGNABLE_ROLES = ("inspector", "reviewer")  # roles an admin can give from the UI

FINDING_STATUSES = ("pending", "accepted", "rejected", "uncertain")
# Workflow: queued -> processing -> draft (inspector checks AI results) -> in_review (submitted, pending review)
#           -> reviewed (approved by a reviewer) | rejected (returned to the inspector) -> reported (report issued)
INSPECTION_STATUSES = ("queued", "processing", "failed", "draft", "in_review", "reviewed", "rejected", "reported")
STATUS_LABELS = {
    "queued": "Queued",
    "processing": "Analyzing",
    "failed": "Analysis failed",
    "draft": "Ready to submit",
    "in_review": "Pending review",
    "reviewed": "Approved",
    "rejected": "Rejected",
    "reported": "Report issued",
}
# Statuses a reviewer can see (anything an inspector has submitted)
SUBMITTED_STATUSES = ("in_review", "reviewed", "rejected", "reported")


def now():
    return datetime.utcnow()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="inspector")
    organization = db.Column(db.String(160))
    phone = db.Column(db.String(40))
    job_title = db.Column(db.String(120))
    is_active_flag = db.Column(db.Boolean, default=True)
    default_frame_interval = db.Column(db.Float, default=1.0)
    created_at = db.Column(db.DateTime, default=now)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_active(self):
        return bool(self.is_active_flag)

    @property
    def can_review(self):
        return self.role in ("reviewer", "admin")

    @property
    def is_inspector(self):
        return self.role == "inspector"

    @property
    def is_reviewer(self):
        return self.role == "reviewer"

    @property
    def can_inspect(self):
        """Upload media, run detection, submit inspections."""
        return self.role in ("inspector", "admin")

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


class Turbine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120))
    site = db.Column(db.String(160), nullable=False)
    region = db.Column(db.String(120))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    manufacturer = db.Column(db.String(120))
    model = db.Column(db.String(120))
    hub_height_m = db.Column(db.Float)
    rotor_diameter_m = db.Column(db.Float)
    commission_year = db.Column(db.Integer)
    status = db.Column(db.String(20), default="operational")  # operational / maintenance / offline
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now)

    blades = db.relationship("Blade", backref="turbine", cascade="all, delete-orphan",
                             order_by="Blade.position")
    inspections = db.relationship("Inspection", backref="turbine",
                                  order_by="Inspection.created_at.desc()")

    @property
    def label(self):
        return f"{self.code} · {self.site}" if self.site else self.code


class Blade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    turbine_id = db.Column(db.Integer, db.ForeignKey("turbine.id"), nullable=False)
    position = db.Column(db.String(10), nullable=False)  # A / B / C
    serial = db.Column(db.String(80))
    length_m = db.Column(db.Float)
    material = db.Column(db.String(120))
    manufacturer = db.Column(db.String(120))
    install_year = db.Column(db.Integer)
    notes = db.Column(db.Text)

    @property
    def label(self):
        return f"Blade {self.position}"


class Inspection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True)
    title = db.Column(db.String(200))
    turbine_id = db.Column(db.Integer, db.ForeignKey("turbine.id"), nullable=False)
    blade_id = db.Column(db.Integer, db.ForeignKey("blade.id"))
    inspection_date = db.Column(db.Date)
    drone_model = db.Column(db.String(120))
    operator_name = db.Column(db.String(120))
    weather = db.Column(db.String(120))
    notes = db.Column(db.Text)

    conf_threshold = db.Column(db.Float, default=0.25)
    frame_interval_s = db.Column(db.Float, default=1.0)
    mask_enabled = db.Column(db.Boolean, default=False)
    mask_applied = db.Column(db.Boolean, default=False)
    model_name = db.Column(db.String(200))
    vlm_enabled = db.Column(db.Boolean, default=False)
    vlm_status = db.Column(db.String(12))  # running / done / partial / failed / None
    vlm_note = db.Column(db.Text)
    vlm_model = db.Column(db.String(80))
    vlm_frames_checked = db.Column(db.Integer, default=0)
    vlm_added = db.Column(db.Integer, default=0)

    status = db.Column(db.String(20), default="queued")
    progress = db.Column(db.Integer, default=0)
    progress_msg = db.Column(db.String(200))
    error = db.Column(db.Text)

    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now)
    analyzed_at = db.Column(db.DateTime)
    processing_seconds = db.Column(db.Float)
    review_completed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    review_completed_at = db.Column(db.DateTime)
    submitted_at = db.Column(db.DateTime)
    submit_note = db.Column(db.Text)        # inspector's note to the reviewer
    review_decision = db.Column(db.String(10))  # approved / rejected
    review_comment = db.Column(db.Text)     # reviewer's overall comment

    blade = db.relationship("Blade")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    review_completed_by = db.relationship("User", foreign_keys=[review_completed_by_id])
    media = db.relationship("Media", backref="inspection", cascade="all, delete-orphan")
    frames = db.relationship("Frame", backref="inspection", cascade="all, delete-orphan",
                             order_by="Frame.id")
    findings = db.relationship("Finding", backref="inspection", cascade="all, delete-orphan",
                               order_by="Finding.id")
    report = db.relationship("Report", backref="inspection", uselist=False,
                             cascade="all, delete-orphan")
    messages = db.relationship("ChatMessage", backref="inspection", cascade="all, delete-orphan",
                               order_by="ChatMessage.id")

    def counts(self):
        c = {s: 0 for s in FINDING_STATUSES}
        for f in self.findings:
            c[f.status] = c.get(f.status, 0) + 1
        c["total"] = len(self.findings)
        return c

    @property
    def pending_count(self):
        return sum(1 for f in self.findings if f.status == "pending")

    @property
    def approved_findings(self):
        return [f for f in self.findings if f.status == "accepted"]

    @property
    def is_busy(self):
        return self.status in ("queued", "processing")

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def is_submitted(self):
        return self.status in SUBMITTED_STATUSES


class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # image / video
    original_name = db.Column(db.String(255))
    stored_path = db.Column(db.String(400), nullable=False)  # relative to UPLOAD_DIR
    size_bytes = db.Column(db.Integer)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    duration_s = db.Column(db.Float)
    fps = db.Column(db.Float)


class Frame(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=False)
    media_id = db.Column(db.Integer, db.ForeignKey("media.id"), nullable=False)
    image_path = db.Column(db.String(400), nullable=False)  # relative to UPLOAD_DIR
    frame_index = db.Column(db.Integer)  # original video frame index
    timestamp_s = db.Column(db.Float)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    masked = db.Column(db.Boolean, default=False)
    detections_count = db.Column(db.Integer, default=0)

    media = db.relationship("Media")

    @property
    def label(self):
        if self.media and self.media.kind == "video":
            return f"{self.media.original_name} @ {fmt_ts(self.timestamp_s)}"
        return self.media.original_name if self.media else f"Frame {self.id}"


def fmt_ts(sec):
    if sec is None:
        return "-"
    sec = float(sec)
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"


class Finding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=False)
    frame_id = db.Column(db.Integer, db.ForeignKey("frame.id"), nullable=False)
    class_name = db.Column(db.String(60), nullable=False)
    confidence = db.Column(db.Float)  # None for manual findings
    # normalized xyxy (0..1)
    x1 = db.Column(db.Float, nullable=False)
    y1 = db.Column(db.Float, nullable=False)
    x2 = db.Column(db.Float, nullable=False)
    y2 = db.Column(db.Float, nullable=False)
    ai_class_name = db.Column(db.String(60))
    ai_box = db.Column(db.String(120))  # JSON of the original AI box
    source = db.Column(db.String(10), default="ai")  # ai (YOLO) / vlm (found by the VLM) / manual
    severity = db.Column(db.String(10), default="medium")  # low / medium / high
    status = db.Column(db.String(12), default="pending")
    edited = db.Column(db.Boolean, default=False)
    occurrences = db.Column(db.Integer, default=1)
    first_ts = db.Column(db.Float)
    last_ts = db.Column(db.Float)
    frame_ids = db.Column(db.Text)  # JSON list of all frames this defect appeared in
    reviewer_note = db.Column(db.Text)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now)
    # VLM cross-check
    vlm_verdict = db.Column(db.String(12))  # confirmed / relabeled / rejected / added / None
    vlm_class = db.Column(db.String(60))
    vlm_confidence = db.Column(db.Float)
    vlm_reason = db.Column(db.Text)
    fused_confidence = db.Column(db.Float)

    frame = db.relationship("Frame")
    reviewed_by = db.relationship("User")

    @property
    def area(self):
        return max(0.0, (self.x2 - self.x1)) * max(0.0, (self.y2 - self.y1))

    @property
    def code(self):
        return f"F-{self.id:04d}"

    @property
    def models_agree(self):
        return self.vlm_verdict in ("confirmed", "relabeled")

    @property
    def vlm_label(self):
        return {"confirmed": "VLM confirms", "relabeled": "VLM relabeled",
                "rejected": "VLM disagrees", "added": "Found by VLM"}.get(self.vlm_verdict, "Not cross-checked")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "frame_id": self.frame_id,
            "class_name": self.class_name,
            "ai_class_name": self.ai_class_name,
            "confidence": self.confidence,
            "box": [self.x1, self.y1, self.x2, self.y2],
            "ai_box": json.loads(self.ai_box) if self.ai_box else None,
            "source": self.source,
            "severity": self.severity,
            "status": self.status,
            "edited": self.edited,
            "occurrences": self.occurrences,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "reviewer_note": self.reviewer_note or "",
            "reviewed_by": self.reviewed_by.name if self.reviewed_by else None,
            "reviewed_at": self.reviewed_at.strftime("%Y-%m-%d %H:%M") if self.reviewed_at else None,
            "vlm_verdict": self.vlm_verdict,
            "vlm_class": self.vlm_class,
            "vlm_confidence": self.vlm_confidence,
            "vlm_reason": self.vlm_reason or "",
            "fused_confidence": self.fused_confidence,
        }


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), unique=True, nullable=False)
    title = db.Column(db.String(300))
    content = db.Column(db.Text)  # JSON
    status = db.Column(db.String(10), default="draft")  # draft / issued
    generator = db.Column(db.String(20), default="template")  # llm / template
    llm_model = db.Column(db.String(80))
    generation_note = db.Column(db.String(300))
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=now)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
    issued_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    issued_at = db.Column(db.DateTime)

    created_by = db.relationship("User", foreign_keys=[created_by_id])
    issued_by = db.relationship("User", foreign_keys=[issued_by_id])

    @property
    def data(self):
        try:
            return json.loads(self.content or "{}")
        except ValueError:
            return {}

    @data.setter
    def data(self, value):
        self.content = json.dumps(value, ensure_ascii=False)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    finding_id = db.Column(db.Integer, db.ForeignKey("finding.id", ondelete="SET NULL"))
    role = db.Column(db.String(10), nullable=False)  # user / assistant
    content = db.Column(db.Text, nullable=False)
    mode = db.Column(db.String(10))  # ai / offline / error
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")
    finding = db.relationship("Finding")


class AppSetting(db.Model):
    """Admin-editable runtime settings (override the values from app.py)."""
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(400))
    updated_at = db.Column(db.DateTime, default=now, onupdate=now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspection.id", ondelete="SET NULL"))
    action = db.Column(db.String(60), nullable=False)
    entity = db.Column(db.String(40))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now, index=True)

    user = db.relationship("User")

    @property
    def details_dict(self):
        try:
            return json.loads(self.details or "{}")
        except ValueError:
            return {}


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    topic = db.Column(db.String(60))
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(12), default="open")  # open / closed
    created_at = db.Column(db.DateTime, default=now)

    user = db.relationship("User")
