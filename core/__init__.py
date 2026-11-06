import json
from datetime import date, datetime
from pathlib import Path

from flask import Flask, render_template

from config import Config

from .extensions import csrf, db, login_manager


def create_app(settings=None, config_class=Config):
    """settings: dict of overrides (see app.py), e.g. {"DEFAULT_CONF": 0.4}."""
    app = Flask(__name__, instance_path=str(config_class.INSTANCE_DIR))
    app.config.from_object(config_class)
    for k, v in (settings or {}).items():
        app.config[k] = v
    if not isinstance(app.config["MODEL_PATH"], Path):
        p = Path(app.config["MODEL_PATH"])
        app.config["MODEL_PATH"] = p if p.is_absolute() else Path(config_class.INSTANCE_DIR).parent / p
    seg = app.config.get("BLADE_SEG_MODEL_PATH")
    if seg and not Path(seg).is_absolute():
        app.config["BLADE_SEG_MODEL_PATH"] = str(Path(config_class.INSTANCE_DIR).parent / seg)
    app.config["DEFAULT_CONF"] = min(0.95, max(0.05, float(app.config["DEFAULT_CONF"])))
    from .services import detector as _det
    _det.SETTINGS.update(iou=app.config["NMS_IOU"], max_det=app.config["MAX_DETECTIONS"])
    config_class.INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    config_class.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .blueprints import admin, auth, dashboard, inspections, live, main, profile, reports, turbines

    for bp in (main.bp, auth.bp, dashboard.bp, inspections.bp, live.bp, reports.bp, turbines.bp, profile.bp, admin.bp):
        app.register_blueprint(bp)

    _register_template_helpers(app)
    _register_errors(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
        from .extensions import add_missing_columns

        add_missing_columns()
        from .seed import seed_if_empty

        seed_if_empty(app)
        _migrate_statuses()

    from .settings_store import load as load_settings

    load_settings(app)

    from .services.worker import recover_stuck

    recover_stuck(app)
    return app


def _migrate_statuses():
    """Inspections created before the submit step existed were already 'in review'; nothing to change for them,
    but make sure old rows have review_decision filled for approved/reported ones."""
    from .models import Inspection

    for i in Inspection.query.filter(Inspection.status.in_(["reviewed", "reported"]),
                                     Inspection.review_decision.is_(None)).all():
        i.review_decision = "approved"
    db.session.commit()


def _register_template_helpers(app):
    from .models import fmt_ts
    from .services import detector
    from .services.knowledge import SEVERITY_EN, class_catalog, info
    from .utils import action_label

    from flask_login import current_user

    from .permissions import perm

    # Make current_user and perm available in every template, including imported macros and error pages
    # (fixes "'current_user' is undefined" when a macro or an error page is rendered).
    @app.context_processor
    def inject_user():
        counts = {}
        if getattr(current_user, "is_authenticated", False):
            from .models import Inspection
            from .permissions import visible_inspections

            try:
                if current_user.role in ("reviewer", "admin"):
                    counts["queue"] = Inspection.query.filter_by(status="in_review").count()
                elif current_user.role == "inspector":
                    counts["action"] = visible_inspections().filter(Inspection.status.in_(["draft", "rejected"])).count()
            except Exception:  # noqa: BLE001 — never break a page over a badge
                pass
        return {"current_user": current_user, "perm": perm, "nav_counts": counts}

    # globals (not a context processor) so imported macros can use them too
    app.jinja_env.globals.update(
        current_user=current_user,
        perm=perm,
        defect_info=info,
        severity_en=SEVERITY_EN,
        action_label=action_label,
        fmt_ts=fmt_ts,
        now_year=date.today().year,
    )

    @app.template_filter("dt")
    def dt(v, fmt="%d %b %Y, %H:%M"):
        if not v:
            return "-"
        return v.strftime(fmt)

    @app.template_filter("d")
    def d(v):
        if not v:
            return "-"
        return v.strftime("%d %b %Y")

    @app.template_filter("pct")
    def pct(v):
        return "-" if v is None else f"{v * 100:.0f}%"

    @app.template_filter("ago")
    def ago(v):
        if not v:
            return "-"
        s = (datetime.utcnow() - v).total_seconds()
        if s < 60:
            return "just now"
        if s < 3600:
            return f"{int(s // 60)} min ago"
        if s < 86400:
            return f"{int(s // 3600)} h ago"
        if s < 86400 * 30:
            return f"{int(s // 86400)} d ago"
        return v.strftime("%d %b %Y")

    @app.template_filter("tojson_ar")
    def tojson_ar(v):
        return json.dumps(v, ensure_ascii=False)

    app.jinja_env.globals["class_catalog"] = lambda: class_catalog(detector.class_names(app.config["MODEL_PATH"]))


def _register_errors(app):
    @app.errorhandler(403)
    def e403(e):
        return render_template("error.html", code=403, title="You don't have access to this page",
                               message="Your role doesn't include this action. Ask an admin to change your role if you need it."), 403

    @app.errorhandler(404)
    def e404(e):
        return render_template("error.html", code=404, title="Page not found",
                               message="The page or record you opened doesn't exist or was deleted."), 404

    @app.errorhandler(413)
    def e413(e):
        mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template("error.html", code=413, title="Upload too large",
                               message=f"The total upload limit is {mb} MB. Upload fewer files or a shorter video."), 413


def _register_cli(app):
    @app.cli.command("create-admin")
    def create_admin():
        """Create an admin account interactively."""
        import getpass

        from .models import User

        name = input("Name: ").strip()
        email = input("Email: ").strip().lower()
        pw = getpass.getpass("Password: ")
        u = User.query.filter_by(email=email).first() or User(email=email)
        u.name, u.role = name, "admin"
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        print(f"Admin {email} ready.")

    @app.cli.command("reset-db")
    def reset_db():
        """Drop and recreate all tables, then seed demo data."""
        from .seed import seed_if_empty

        db.drop_all()
        db.create_all()
        seed_if_empty(app, force=True)
        print("Database reset.")
