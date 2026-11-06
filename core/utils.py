import json
from functools import wraps

from flask import abort, current_app
from flask_login import current_user

from .extensions import db
from .models import AuditLog


def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


reviewer_required = roles_required("reviewer", "admin")
admin_required = roles_required("admin")


def audit(action, entity=None, entity_id=None, inspection_id=None, user_id=None, commit=False, **details):
    uid = user_id
    if uid is None and current_user and getattr(current_user, "is_authenticated", False):
        uid = current_user.id
    log = AuditLog(
        user_id=uid,
        inspection_id=inspection_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
    )
    db.session.add(log)
    if commit:
        db.session.commit()
    return log


ACTION_LABELS = {
    "user.signup": "created an account",
    "user.login": "signed in",
    "user.role_changed": "changed a user's role",
    "user.created": "created a user account",
    "user.activated": "reactivated a user account",
    "user.deactivated": "deactivated a user account",
    "settings.updated": "changed the platform settings",
    "inspection.submitted": "submitted an inspection for review",
    "inspection.resubmitted": "resubmitted an inspection for review",
    "inspection.downloaded": "downloaded inspection images",
    "review.rejected": "rejected an inspection",
    "user.updated": "updated a profile",
    "turbine.created": "added a turbine",
    "turbine.updated": "updated a turbine",
    "turbine.deleted": "deleted a turbine",
    "inspection.created": "started an inspection",
    "inspection.analyzed": "finished AI analysis",
    "inspection.failed": "AI analysis failed",
    "inspection.deleted": "deleted an inspection",
    "finding.accepted": "accepted a finding",
    "finding.rejected": "rejected a finding",
    "finding.uncertain": "marked a finding uncertain",
    "finding.edited": "edited a finding",
    "finding.reset": "reset a finding to pending",
    "finding.added": "added a manual finding",
    "review.completed": "approved an inspection",
    "review.reopened": "reopened the review",
    "report.generated": "generated the Arabic report",
    "report.edited": "edited the report",
    "report.issued": "issued the report",
    "report.exported": "exported the report PDF",
    "report.blocked": "tried to generate a report before review was complete",
    "support.ticket": "sent a support request",
    "chat.asked": "asked the AI assistant",
    "inspection.vlm": "finished the VLM cross-check",
    "inspection.vlm_started": "started a VLM cross-check",
}


def action_label(action):
    return ACTION_LABELS.get(action, action.replace(".", " ").replace("_", " "))
