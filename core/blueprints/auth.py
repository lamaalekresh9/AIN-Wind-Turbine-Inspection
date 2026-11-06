import re
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import User
from ..utils import audit

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def password_problem(pw):
    if len(pw) < 8:
        return "Use at least 8 characters for the password."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "The password needs at least one letter and one number."
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        u = User.query.filter_by(email=email).first()
        if not u or not u.check_password(pw):
            flash("Email or password is incorrect.", "error")
        elif not u.is_active:
            flash("This account is disabled. Contact your admin.", "error")
        else:
            login_user(u, remember=bool(request.form.get("remember")))
            u.last_login_at = datetime.utcnow()
            audit("user.login", "user", u.id)
            db.session.commit()
            nxt = request.args.get("next")
            if nxt and not urlparse(nxt).netloc and nxt.startswith("/"):
                return redirect(nxt)
            return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html", allow_signup=current_app.config["ALLOW_SIGNUP"])


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if not current_app.config["ALLOW_SIGNUP"]:
        flash("Sign-up is closed. Ask an admin to create your account.", "info")
        return redirect(url_for("auth.login"))
    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        pw = form.get("password", "")
        err = None
        if len(name) < 2:
            err = "Enter your full name."
        elif not EMAIL_RE.match(email):
            err = "Enter a valid email address."
        elif User.query.filter_by(email=email).first():
            err = "An account with this email already exists. Sign in instead."
        elif pw != form.get("confirm", ""):
            err = "The two passwords don't match."
        else:
            err = password_problem(pw)
        if err:
            flash(err, "error")
        else:
            u = User(name=name, email=email, role="inspector",
                     organization=form.get("organization", "").strip() or None)
            u.set_password(pw)
            db.session.add(u)
            db.session.flush()
            audit("user.signup", "user", u.id, user_id=u.id)
            db.session.commit()
            login_user(u)
            flash("Account created. You're signed in as an inspector; an admin can grant reviewer access.", "success")
            return redirect(url_for("dashboard.index"))
    return render_template("auth/signup.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You're signed out.", "info")
    return redirect(url_for("main.home"))
