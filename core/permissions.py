"""Role-based access control: every permission decision in one place.

Roles
- inspector : uploads media, runs YOLO/VLM, views AI results, submits inspections. Sees ONLY their own inspections.
- reviewer  : sees inspections that have been submitted, accepts/rejects/edits findings, approves or rejects
              the inspection, generates and issues the Arabic report. Does not upload or manage users.
- admin     : manages users, settings and logs; sees everything; can step in for inspector or reviewer actions.

Routes call these helpers; templates use the same helpers (via the `perm` template global) only to decide
what to show. Hidden buttons are never the protection: the server checks again on every request.
"""
from functools import wraps

from flask import abort
from flask_login import current_user

from .extensions import db
from .models import SUBMITTED_STATUSES, Inspection

INSPECTOR, REVIEWER, ADMIN = "inspector", "reviewer", "admin"


def _role(user):
    return getattr(user, "role", None) if user and getattr(user, "is_authenticated", False) else None


# ------------------------------------------------------------------ visibility

def visible_inspections(user=None):
    """Query of the inspections this user may see."""
    user = user or current_user
    role = _role(user)
    q = Inspection.query
    if role == ADMIN:
        return q
    if role == REVIEWER:
        return q.filter(Inspection.status.in_(SUBMITTED_STATUSES))
    if role == INSPECTOR:
        return q.filter(Inspection.created_by_id == user.id)
    return q.filter(db.false())


def can_view(insp, user=None):
    user = user or current_user
    role = _role(user)
    if not insp or not role:
        return False
    if role == ADMIN:
        return True
    if role == REVIEWER:
        return insp.status in SUBMITTED_STATUSES
    return insp.created_by_id == user.id


def is_owner(insp, user=None):
    user = user or current_user
    return bool(insp and _role(user) and insp.created_by_id == user.id)


# ------------------------------------------------------------------ inspector actions

def can_create(user=None):
    return _role(user or current_user) in (INSPECTOR, ADMIN)


def can_manage(insp, user=None):
    """Re-run analysis, re-run the VLM check, add notes: the owner while it isn't under review, or an admin."""
    user = user or current_user
    if _role(user) == ADMIN:
        return insp.status != "reported"
    return is_owner(insp, user) and insp.status in ("draft", "rejected", "failed")


def can_submit(insp, user=None):
    user = user or current_user
    return (is_owner(insp, user) or _role(user) == ADMIN) and insp.status in ("draft", "rejected")


def can_delete(insp, user=None):
    user = user or current_user
    if _role(user) == ADMIN:
        return not insp.is_busy
    return is_owner(insp, user) and insp.status in ("draft", "failed", "rejected")


def can_download(insp, user=None):
    return can_view(insp, user)


# ------------------------------------------------------------------ reviewer actions

def can_review(insp, user=None):
    """Accept / reject / edit findings and approve or reject the inspection."""
    user = user or current_user
    return _role(user) in (REVIEWER, ADMIN) and insp.status == "in_review"


def can_reopen(insp, user=None):
    user = user or current_user
    return _role(user) in (REVIEWER, ADMIN) and insp.status in ("reviewed", "rejected") and not (
        insp.report and insp.report.status == "issued")


def can_open_review_page(insp, user=None):
    user = user or current_user
    return _role(user) in (REVIEWER, ADMIN) and can_view(insp, user)


def can_write_report(insp, user=None):
    """Generate, edit and issue the Arabic report."""
    user = user or current_user
    return _role(user) in (REVIEWER, ADMIN) and can_view(insp, user)


def can_view_report(insp, user=None):
    """Reviewers and admins see drafts; the inspector sees the report only once it's issued (final)."""
    user = user or current_user
    if not insp.report:
        return _role(user) in (REVIEWER, ADMIN) and can_view(insp, user)
    if _role(user) in (REVIEWER, ADMIN):
        return can_view(insp, user)
    return is_owner(insp, user) and insp.report.status == "issued"


def can_run_vlm(insp, user=None):
    user = user or current_user
    if insp.status == "in_review":
        return _role(user) in (REVIEWER, ADMIN)
    return can_manage(insp, user) and insp.status in ("draft", "rejected")


# ------------------------------------------------------------------ helpers for routes

def get_inspection_or_404(insp_id):
    """Inspections the user can't see answer 404, so their existence isn't revealed."""
    insp = db.session.get(Inspection, insp_id)
    if not insp or not can_view(insp):
        abort(404)
    return insp


def require(ok):
    if not ok:
        abort(403)


def roles(*allowed):
    """Route decorator: only these roles (checked after @login_required)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if _role(current_user) not in allowed:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


class _Perm:
    """Exposed to templates as `perm`, e.g. {% if perm.can_review(insp) %}."""
    can_view = staticmethod(can_view)
    is_owner = staticmethod(is_owner)
    can_create = staticmethod(can_create)
    can_manage = staticmethod(can_manage)
    can_submit = staticmethod(can_submit)
    can_delete = staticmethod(can_delete)
    can_download = staticmethod(can_download)
    can_review = staticmethod(can_review)
    can_reopen = staticmethod(can_reopen)
    can_open_review_page = staticmethod(can_open_review_page)
    can_write_report = staticmethod(can_write_report)
    can_view_report = staticmethod(can_view_report)
    can_run_vlm = staticmethod(can_run_vlm)


perm = _Perm()
