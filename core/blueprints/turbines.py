from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from ..extensions import db
from ..models import Blade, Finding, Inspection, Turbine
from ..permissions import ADMIN, INSPECTOR, roles, visible_inspections
from ..utils import admin_required, audit

bp = Blueprint("turbines", __name__)

FIELDS_STR = ["code", "name", "site", "region", "manufacturer", "model", "status", "notes"]
FIELDS_FLOAT = ["latitude", "longitude", "hub_height_m", "rotor_diameter_m"]


def _num(v, cast=float):
    v = (v or "").strip()
    if not v:
        return None
    return cast(v)


def _fill(t, form):
    for k in FIELDS_STR:
        setattr(t, k, (form.get(k) or "").strip() or None)
    for k in FIELDS_FLOAT:
        setattr(t, k, _num(form.get(k)))
    t.commission_year = _num(form.get("commission_year"), int)
    t.status = t.status or "operational"


@bp.route("/turbines")
@login_required
def index():
    q = Turbine.query
    s = request.args.get("q", "").strip()
    if s:
        like = f"%{s}%"
        q = q.filter(db.or_(Turbine.code.ilike(like), Turbine.site.ilike(like), Turbine.region.ilike(like)))
    if request.args.get("status"):
        q = q.filter(Turbine.status == request.args["status"])
    turbines = q.order_by(Turbine.site, Turbine.code).all()
    stats = {}
    vis = visible_inspections().with_entities(Inspection.id)  # inspectors only count their own inspections
    for tid, n in (db.session.query(Inspection.turbine_id, func.count(Inspection.id))
                   .filter(Inspection.id.in_(vis)).group_by(Inspection.turbine_id).all()):
        stats.setdefault(tid, {})["insp"] = n
    for tid, n in (db.session.query(Inspection.turbine_id, func.count(Finding.id))
                   .join(Finding, Finding.inspection_id == Inspection.id)
                   .filter(Finding.status == "accepted", Inspection.id.in_(vis))
                   .group_by(Inspection.turbine_id).all()):
        stats.setdefault(tid, {})["defects"] = n
    sites = {}
    for t in turbines:
        sites.setdefault(t.site, []).append(t)
    return render_template("turbines/index.html", sites=sites, stats=stats, args=request.args,
                           total=len(turbines))


@bp.route("/turbines/new", methods=["GET", "POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def new():
    if request.method == "POST":
        t = Turbine()
        try:
            _fill(t, request.form)
        except ValueError:
            flash("Coordinates, heights, diameter and year must be numbers.", "error")
            return render_template("turbines/form.html", t=None, form=request.form)
        if not t.code or not t.site:
            flash("Turbine ID and site are required.", "error")
            return render_template("turbines/form.html", t=None, form=request.form)
        if Turbine.query.filter_by(code=t.code).first():
            flash(f"A turbine with ID {t.code} already exists.", "error")
            return render_template("turbines/form.html", t=None, form=request.form)
        if request.form.get("add_blades"):
            length = _num(request.form.get("blade_length"))
            for p in "ABC":
                t.blades.append(Blade(position=p, serial=f"{t.code}-{p}", length_m=length,
                                      manufacturer=t.manufacturer))
        db.session.add(t)
        db.session.flush()
        audit("turbine.created", "turbine", t.id, code=t.code)
        db.session.commit()
        flash(f"Turbine {t.code} added.", "success")
        return redirect(url_for("turbines.detail", tid=t.id))
    return render_template("turbines/form.html", t=None, form={"status": "operational", "add_blades": "1"})


@bp.route("/turbines/<int:tid>")
@login_required
def detail(tid):
    t = db.session.get(Turbine, tid) or abort(404)
    vis = visible_inspections().with_entities(Inspection.id)
    per_blade = dict(db.session.query(Inspection.blade_id, func.count(Finding.id))
                     .join(Finding, Finding.inspection_id == Inspection.id)
                     .filter(Inspection.turbine_id == t.id, Finding.status == "accepted", Inspection.id.in_(vis))
                     .group_by(Inspection.blade_id).all())
    inspections = (visible_inspections().filter(Inspection.turbine_id == t.id)
                   .order_by(Inspection.created_at.desc()).all())
    return render_template("turbines/detail.html", t=t, per_blade=per_blade, inspections=inspections,
                           has_any=bool(t.inspections))


@bp.route("/turbines/<int:tid>/edit", methods=["GET", "POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def edit(tid):
    t = db.session.get(Turbine, tid) or abort(404)
    if request.method == "POST":
        old = t.code
        try:
            _fill(t, request.form)
        except ValueError:
            db.session.rollback()
            flash("Coordinates, heights, diameter and year must be numbers.", "error")
            return render_template("turbines/form.html", t=t, form=request.form)
        dup = Turbine.query.filter(Turbine.code == t.code, Turbine.id != t.id).first()
        if not t.code or not t.site or dup:
            db.session.rollback()
            flash("Turbine ID must be unique, and ID and site are required.", "error")
            return render_template("turbines/form.html", t=t, form=request.form)
        audit("turbine.updated", "turbine", t.id, code=t.code, previous_code=old)
        db.session.commit()
        flash("Turbine updated.", "success")
        return redirect(url_for("turbines.detail", tid=t.id))
    return render_template("turbines/form.html", t=t, form=t.__dict__)


@bp.route("/turbines/<int:tid>/delete", methods=["POST"])
@login_required
@admin_required
def delete(tid):
    t = db.session.get(Turbine, tid) or abort(404)
    if t.inspections:
        flash("This turbine has inspection records, so it can't be deleted. Set its status to offline instead.", "error")
        return redirect(url_for("turbines.detail", tid=t.id))
    audit("turbine.deleted", "turbine", t.id, code=t.code)
    db.session.delete(t)
    db.session.commit()
    flash("Turbine deleted.", "success")
    return redirect(url_for("turbines.index"))


@bp.route("/turbines/<int:tid>/blades", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def save_blade(tid):
    t = db.session.get(Turbine, tid) or abort(404)
    f = request.form
    bid = f.get("blade_id", type=int)
    b = db.session.get(Blade, bid) if bid else Blade(turbine_id=t.id)
    if bid and (not b or b.turbine_id != t.id):
        abort(404)
    pos = (f.get("position") or "").strip().upper()[:10]
    if not pos:
        flash("Blade position is required (for example A, B or C).", "error")
        return redirect(url_for("turbines.detail", tid=t.id))
    clash = Blade.query.filter(Blade.turbine_id == t.id, Blade.position == pos, Blade.id != (b.id or 0)).first()
    if clash:
        flash(f"Blade {pos} already exists on this turbine.", "error")
        return redirect(url_for("turbines.detail", tid=t.id))
    try:
        b.position = pos
        b.serial = f.get("serial", "").strip() or None
        b.length_m = _num(f.get("length_m"))
        b.material = f.get("material", "").strip() or None
        b.manufacturer = f.get("manufacturer", "").strip() or None
        b.install_year = _num(f.get("install_year"), int)
        b.notes = f.get("notes", "").strip() or None
    except ValueError:
        flash("Blade length and install year must be numbers.", "error")
        return redirect(url_for("turbines.detail", tid=t.id))
    db.session.add(b)
    audit("turbine.updated", "turbine", t.id, blade=pos)
    db.session.commit()
    flash(f"Blade {pos} saved.", "success")
    return redirect(url_for("turbines.detail", tid=t.id) + "#blades")


@bp.route("/turbines/<int:tid>/blades/<int:bid>/delete", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def delete_blade(tid, bid):
    b = db.session.get(Blade, bid)
    if not b or b.turbine_id != tid:
        abort(404)
    if Inspection.query.filter_by(blade_id=b.id).first():
        flash("This blade has inspection records and can't be deleted.", "error")
    else:
        db.session.delete(b)
        audit("turbine.updated", "turbine", tid, blade_deleted=b.position)
        db.session.commit()
        flash("Blade deleted.", "success")
    return redirect(url_for("turbines.detail", tid=tid) + "#blades")


@bp.route("/api/turbines/<int:tid>/blades")
@login_required
def blades_json(tid):
    t = db.session.get(Turbine, tid) or abort(404)
    return {"blades": [{"id": b.id, "label": b.label, "length": b.length_m} for b in t.blades]}
