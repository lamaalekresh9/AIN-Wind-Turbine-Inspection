"""One dashboard per role: Inspector, Human Reviewer, Admin."""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_

from ..extensions import db
from ..models import ROLE_LABELS, STATUS_LABELS, AuditLog, Finding, Inspection, Report, Turbine, User
from ..permissions import ADMIN, INSPECTOR, REVIEWER, visible_inspections
from ..services import ai_client, detector
from ..services.knowledge import class_catalog

bp = Blueprint("dashboard", __name__)


def _by_class(insp_ids_q):
    names = detector.class_names(current_app.config["MODEL_PATH"])
    cat = class_catalog(names)
    acc = dict(db.session.query(Finding.class_name, func.count(Finding.id))
               .filter(Finding.status == "accepted", Finding.inspection_id.in_(insp_ids_q))
               .group_by(Finding.class_name).all())
    det = dict(db.session.query(Finding.ai_class_name, func.count(Finding.id))
               .filter(Finding.source == "ai", Finding.inspection_id.in_(insp_ids_q))
               .group_by(Finding.ai_class_name).all())
    return [{"label": c["en"], "name": c["name"], "color": c["color"], "accepted": acc.get(c["name"], 0),
             "detected": det.get(c["name"], 0)} for c in cat]


def _per_week(q):
    today = datetime.utcnow().date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=7)
    weeks = [start + timedelta(weeks=i) for i in range(8)]
    dates = [i.created_at.date() for i in q.filter(
        Inspection.created_at >= datetime.combine(start, datetime.min.time())).all()]
    return [{"label": w.strftime("%d %b"), "value": sum(1 for d in dates if w <= d < w + timedelta(weeks=1))}
            for w in weeks]


def _review_split(insp_ids_q):
    rows = dict(db.session.query(Finding.status, func.count(Finding.id))
                .filter(Finding.inspection_id.in_(insp_ids_q)).group_by(Finding.status).all())
    return {s: rows.get(s, 0) for s in ("accepted", "rejected", "uncertain", "pending")}


@bp.route("/dashboard")
@login_required
def index():
    role = current_user.role
    if role == INSPECTOR:
        return _inspector()
    if role == REVIEWER:
        return _reviewer()
    if role == ADMIN:
        return _admin()
    return render_template("error.html", code=403, title="No dashboard for this role",
                           message="Ask an admin to assign you a role."), 403


def _inspector():
    mine = visible_inspections()  # only this inspector's inspections
    ids = mine.with_entities(Inspection.id)
    by_status = dict(db.session.query(Inspection.status, func.count(Inspection.id))
                     .filter(Inspection.id.in_(ids)).group_by(Inspection.status).all())
    action = (mine.filter(Inspection.status.in_(["draft", "rejected", "failed"]))
              .order_by(Inspection.created_at.desc()).all())
    running = mine.filter(Inspection.status.in_(["queued", "processing"])).all()
    recent = mine.order_by(Inspection.created_at.desc()).limit(8).all()
    return render_template(
        "dashboards/inspector.html",
        stats={"total": sum(by_status.values()),
               "draft": by_status.get("draft", 0),
               "pending": by_status.get("in_review", 0),
               "approved": by_status.get("reviewed", 0) + by_status.get("reported", 0),
               "rejected": by_status.get("rejected", 0),
               "reported": by_status.get("reported", 0)},
        action=action, running=running, recent=recent,
        charts={"by_class": _by_class(ids), "per_week": _per_week(mine)},
    )


def _reviewer():
    vis = visible_inspections()  # submitted inspections from every inspector
    ids = vis.with_entities(Inspection.id)
    queue = vis.filter(Inspection.status == "in_review").order_by(Inspection.submitted_at.asc().nullsfirst(),
                                                                   Inspection.created_at).all()
    need_report = (vis.filter(Inspection.status == "reviewed")
                   .order_by(Inspection.review_completed_at).all())
    mine_done = (vis.filter(Inspection.review_completed_by_id == current_user.id)
                 .order_by(Inspection.review_completed_at.desc()).limit(8).all())
    my_approved = vis.filter(Inspection.review_completed_by_id == current_user.id,
                             Inspection.review_decision == "approved").count()
    my_rejected = vis.filter(Inspection.review_completed_by_id == current_user.id,
                             Inspection.review_decision == "rejected").count()
    my_reports = Report.query.filter_by(issued_by_id=current_user.id, status="issued").count()
    return render_template(
        "dashboards/reviewer.html",
        stats={"queue": len(queue), "need_report": len(need_report), "approved": my_approved,
               "rejected": my_rejected, "reports": my_reports},
        queue=queue, need_report=need_report, mine_done=mine_done,
        charts={"by_class": _by_class(ids), "review": _review_split(ids)},
    )


def _admin():
    all_ids = Inspection.query.with_entities(Inspection.id)
    users_by_role = dict(db.session.query(User.role, func.count(User.id)).group_by(User.role).all())
    inactive = User.query.filter_by(is_active_flag=False).count()
    by_status = dict(db.session.query(Inspection.status, func.count(Inspection.id)).group_by(Inspection.status).all())
    decisions = dict(db.session.query(Inspection.review_decision, func.count(Inspection.id))
                     .filter(Inspection.review_decision.isnot(None)).group_by(Inspection.review_decision).all())
    # every inspector (even with 0 inspections), busiest first
    per_inspector = (db.session.query(User, func.count(Inspection.id),
                                      func.sum(case((Inspection.status == "in_review", 1), else_=0)))
                     .outerjoin(Inspection, Inspection.created_by_id == User.id)
                     .filter(or_(User.role == INSPECTOR, Inspection.id.isnot(None)))
                     .group_by(User.id).order_by(func.count(Inspection.id).desc(), User.name).limit(6).all())
    # every reviewer (even with 0 decisions) + admins who reviewed something
    per_reviewer = (db.session.query(User,
                                     func.sum(case((Inspection.review_decision == "approved", 1), else_=0)),
                                     func.sum(case((Inspection.review_decision == "rejected", 1), else_=0)))
                    .outerjoin(Inspection, Inspection.review_completed_by_id == User.id)
                    .filter(or_(User.role == REVIEWER, Inspection.id.isnot(None)))
                    .group_by(User.id).order_by(func.count(Inspection.id).desc(), User.name).limit(6).all())
    activity = AuditLog.query.filter(AuditLog.action != "user.login").order_by(AuditLog.created_at.desc()).limit(20).all()
    oldest_pending = Inspection.query.filter_by(status="in_review").order_by(Inspection.submitted_at).first()
    return render_template(
        "dashboards/admin.html",
        users_by_role=users_by_role, role_labels=ROLE_LABELS, inactive=inactive,
        status_rows=[(s, STATUS_LABELS[s], by_status.get(s, 0)) for s in STATUS_LABELS],
        total_insp=sum(by_status.values()), decisions=decisions,
        per_inspector=per_inspector, per_reviewer=per_reviewer, activity=activity,
        reports_issued=Report.query.filter_by(status="issued").count(),
        turbines=Turbine.query.count(), oldest_pending=oldest_pending,
        ai=ai_client.status(),
        charts={"by_class": _by_class(all_ids), "per_week": _per_week(Inspection.query),
                "review": _review_split(all_ids)},
    )
