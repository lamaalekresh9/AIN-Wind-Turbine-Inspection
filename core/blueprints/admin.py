from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from sqlalchemy import func

from ..models import ASSIGNABLE_ROLES, ROLE_LABELS, AuditLog, Inspection, SupportTicket, TicketReply, User
from .. import settings_store
from ..services import ai_client, detector
from ..services.knowledge import class_catalog
from ..utils import admin_required, audit

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/users")
@login_required
@admin_required
def users():
    q = User.query
    if request.args.get("role") in ROLE_LABELS:
        q = q.filter(User.role == request.args["role"])
    if request.args.get("q"):
        like = f"%{request.args['q'].strip()}%"
        q = q.filter(db.or_(User.name.ilike(like), User.email.ilike(like)))
    counts = dict(db.session.query(Inspection.created_by_id, func.count(Inspection.id)).group_by(Inspection.created_by_id).all())
    reviewed = dict(db.session.query(Inspection.review_completed_by_id, func.count(Inspection.id))
                    .group_by(Inspection.review_completed_by_id).all())
    return render_template("admin/users.html", users=q.order_by(User.role, User.name).all(), roles=ASSIGNABLE_ROLES,
                           role_labels=ROLE_LABELS, counts=counts, reviewed=reviewed, args=request.args)


def _validate_user_form(f, user=None):
    from .auth import EMAIL_RE, password_problem

    name, email = f.get("name", "").strip(), f.get("email", "").strip().lower()
    if len(name) < 2:
        return "Enter the person's full name."
    if not EMAIL_RE.match(email):
        return "Enter a valid email address."
    clash = User.query.filter(User.email == email, User.id != (user.id if user else 0)).first()
    if clash:
        return "Another account already uses this email."
    pw = f.get("password", "")
    if (not user or pw) and password_problem(pw):
        return password_problem(pw)
    return None


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@admin_required
def create_user():
    f = request.form
    if request.method == "POST":
        err = _validate_user_form(f)
        role = f.get("role") if f.get("role") in ASSIGNABLE_ROLES else "inspector"
        if err:
            flash(err, "error")
        else:
            u = User(name=f["name"].strip(), email=f["email"].strip().lower(), role=role,
                     organization=f.get("organization", "").strip() or None,
                     job_title=f.get("job_title", "").strip() or None)
            u.set_password(f["password"])
            db.session.add(u)
            db.session.flush()
            audit("user.created", "user", u.id, email=u.email, role=role)
            db.session.commit()
            flash(f"Account created for {u.email} as {ROLE_LABELS[role]}.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", u=None, form=f, roles=ASSIGNABLE_ROLES, role_labels=ROLE_LABELS)


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_user(uid):
    u = db.session.get(User, uid)
    if not u:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))
    f = request.form
    if request.method == "POST":
        err = _validate_user_form(f, u)
        role = f.get("role")
        active = f.get("active") == "1"
        if u.id == current_user.id and (not active or (role and role != u.role)):
            err = err or "You can't change your own role or deactivate your own account."
        if role and role not in ASSIGNABLE_ROLES and role != u.role:
            err = err or "Choose Inspector or Human Reviewer."
        if err:
            flash(err, "error")
        else:
            changes = {}
            for k in ("name", "organization", "job_title", "phone"):
                v = f.get(k, "").strip() or None
                if v != getattr(u, k):
                    changes[k] = v
                    setattr(u, k, v)
            email = f["email"].strip().lower()
            if email != u.email:
                changes["email"] = email
                u.email = email
            if role and role != u.role:
                audit("user.role_changed", "user", u.id, email=u.email, previous=u.role, role=role)
                u.role = role
            if active != u.is_active:
                audit("user.activated" if active else "user.deactivated", "user", u.id, email=u.email)
                u.is_active_flag = active
            if f.get("password"):
                u.set_password(f["password"])
                changes["password"] = "reset"
            if changes:
                audit("user.updated", "user", u.id, **{k: ("***" if k == "password" else v) for k, v in changes.items()})
            db.session.commit()
            flash(f"{u.name} updated.", "success")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", u=u, form=f or u.__dict__, roles=ASSIGNABLE_ROLES,
                           role_labels=ROLE_LABELS)


@bp.route("/users/<int:uid>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(uid):
    u = db.session.get(User, uid)
    if not u or u.id == current_user.id:
        flash("You can't deactivate your own account.", "error")
    else:
        u.is_active_flag = not u.is_active
        audit("user.activated" if u.is_active else "user.deactivated", "user", u.id, email=u.email)
        db.session.commit()
        flash(f"{u.name} {'reactivated' if u.is_active else 'deactivated'}.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    if request.method == "POST":
        errors = settings_store.save(current_app._get_current_object(), request.form, current_user.id)
        for e in errors:
            flash(e, "error")
        if not errors:
            audit("settings.updated", "settings", None, commit=True)
            flash("Settings saved. They apply right away.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", fields=settings_store.EDITABLE, cfg=current_app.config)


@bp.route("/audit")
@login_required
@admin_required
def audit_log():
    q = AuditLog.query
    if request.args.get("action"):
        q = q.filter(AuditLog.action.like(request.args["action"] + "%"))
    if request.args.get("user"):
        q = q.filter(AuditLog.user_id == int(request.args["user"]))
    page = q.order_by(AuditLog.created_at.desc()).paginate(page=int(request.args.get("page", 1)),
                                                           per_page=30, error_out=False)
    return render_template("admin/audit.html", page=page, users=User.query.order_by(User.name).all(),
                           args=request.args)


@bp.route("/tickets")
@login_required
@admin_required
def tickets():
    show = request.args.get("show", "open")
    q = SupportTicket.query
    if show in ("open", "closed"):
        q = q.filter(SupportTicket.status == show)
    items = q.order_by(SupportTicket.created_at.desc()).all()
    items.sort(key=lambda t: (not t.awaiting_staff, t.status != "open"))  # needs a reply first
    counts = dict(db.session.query(SupportTicket.status, func.count(SupportTicket.id))
                  .group_by(SupportTicket.status).all())
    return render_template("admin/tickets.html", tickets=items, show=show, counts=counts)


@bp.route("/tickets/<int:tid>", methods=["GET", "POST"])
@login_required
@admin_required
def ticket(tid):
    t = db.session.get(SupportTicket, tid) or abort(404)
    if request.method == "POST":
        body = (request.form.get("body") or "").strip()[:5000]
        close = request.form.get("close") == "1"
        if not body and not close:
            flash("Write a reply first.", "error")
            return redirect(url_for("admin.ticket", tid=t.id))
        if body:
            db.session.add(TicketReply(ticket_id=t.id, author_id=current_user.id, from_staff=True, body=body))
            t.last_staff_at = datetime.utcnow()
            audit("support.reply", "ticket", t.id)
        if close and t.status == "open":
            t.status = "closed"
            audit("support.closed", "ticket", t.id)
        db.session.commit()
        flash("Reply sent. The user will see it in My support requests." if body else "Request marked resolved.",
              "success")
        return redirect(url_for("admin.ticket", tid=t.id))
    return render_template("admin/ticket.html", t=t)


@bp.route("/tickets/<int:tid>/status", methods=["POST"])
@login_required
@admin_required
def ticket_status(tid):
    t = db.session.get(SupportTicket, tid) or abort(404)
    t.status = "closed" if t.status == "open" else "open"
    audit("support.closed" if t.status == "closed" else "support.reopened", "ticket", t.id)
    db.session.commit()
    return redirect(request.form.get("next") or url_for("admin.ticket", tid=t.id))


@bp.route("/ai-test", methods=["POST"])
@login_required
@admin_required
def ai_test():
    if not ai_client.available():
        flash("No AI key found. Add GEMINI_API_KEY (or OPENAI_API_KEY) to the .env file next to app.py and restart.", "error")
    else:
        ok, msg, ms = ai_client.ping()
        flash(f"{ai_client.settings()['model']} ({ms} ms): {msg}", "success" if ok else "error")
    return redirect(url_for("admin.system"))


@bp.route("/system")
@login_required
@admin_required
def system():
    cfg = current_app.config
    mp = Path(cfg["MODEL_PATH"])
    names = detector.class_names(mp)
    return render_template("admin/system.html", model_path=mp, model_exists=mp.exists(),
                           model_size=round(mp.stat().st_size / 1e6, 1) if mp.exists() else None,
                           classes=class_catalog(names), ai=ai_client.status(),
                           seg=cfg["BLADE_SEG_MODEL_PATH"], seg_ready=detector.seg_available(cfg["BLADE_SEG_MODEL_PATH"]),
                           cfg=cfg)
