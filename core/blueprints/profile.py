from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import AuditLog, Inspection, User
from ..utils import audit
from .auth import EMAIL_RE, password_problem

bp = Blueprint("profile", __name__)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def index():
    u = current_user
    if request.method == "POST":
        section = request.form.get("section")
        f = request.form
        if section == "info":
            email = f.get("email", "").strip().lower()
            if len(f.get("name", "").strip()) < 2:
                flash("Enter your full name.", "error")
            elif not EMAIL_RE.match(email):
                flash("Enter a valid email address.", "error")
            elif User.query.filter(User.email == email, User.id != u.id).first():
                flash("Another account already uses this email.", "error")
            else:
                u.name = f["name"].strip()
                u.email = email
                u.organization = f.get("organization", "").strip() or None
                u.job_title = f.get("job_title", "").strip() or None
                u.phone = f.get("phone", "").strip() or None
                audit("user.updated", "user", u.id, section="info")
                db.session.commit()
                flash("Profile saved.", "success")
        elif section == "password":
            if not u.check_password(f.get("current", "")):
                flash("Your current password is incorrect.", "error")
            elif f.get("new") != f.get("confirm"):
                flash("The new passwords don't match.", "error")
            elif (p := password_problem(f.get("new", ""))):
                flash(p, "error")
            else:
                u.set_password(f["new"])
                audit("user.updated", "user", u.id, section="password")
                db.session.commit()
                flash("Password changed.", "success")
        elif section == "prefs":
            try:
                interval = float(f.get("default_frame_interval"))
                assert 0.1 <= interval <= 30
                u.default_frame_interval = interval
                db.session.commit()
                flash("Analysis defaults saved. They'll be prefilled on new inspections.", "success")
            except (TypeError, ValueError, AssertionError):
                flash("Frame interval must be between 0.1 and 30 seconds.", "error")
        return redirect(url_for("profile.index") + f"#{section or ''}")
    mine = Inspection.query.filter_by(created_by_id=u.id).count()
    reviewed = Inspection.query.filter_by(review_completed_by_id=u.id).count()
    activity = AuditLog.query.filter_by(user_id=u.id).order_by(AuditLog.created_at.desc()).limit(8).all()
    return render_template("profile.html", mine=mine, reviewed=reviewed, activity=activity)
