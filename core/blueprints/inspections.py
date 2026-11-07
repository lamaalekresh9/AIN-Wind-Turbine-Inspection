import json
import shutil
import uuid
from datetime import date, datetime
from pathlib import Path

import io
import zipfile

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import STATUS_LABELS, Blade, Finding, Frame, Inspection, Media, Turbine, User
from ..permissions import (ADMIN, INSPECTOR, REVIEWER, can_delete, can_manage, can_open_review_page, can_reopen,
                           can_review, can_run_vlm, can_submit, can_view, get_inspection_or_404, require, roles,
                           visible_inspections)
from ..services import ai_client, detector, worker
from ..services.evidence import annotate
from ..services.knowledge import class_catalog, default_severity
from ..utils import audit

bp = Blueprint("inspections", __name__)


def _get(insp_id):
    """Every inspection route goes through here: unknown or not-yours -> 404."""
    return get_inspection_or_404(insp_id)


def _next_code():
    year = date.today().year
    prefix = f"INS-{year}-"
    last = (Inspection.query.filter(Inspection.code.like(prefix + "%"))
            .order_by(Inspection.id.desc()).first())
    n = int(last.code.split("-")[-1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# ------------------------------------------------------------------ history

@bp.route("/inspections")
@login_required
def history():
    q = visible_inspections()
    a = request.args
    if a.get("inspector") and current_user.role in (REVIEWER, ADMIN):
        q = q.filter(Inspection.created_by_id == int(a["inspector"]))
    if a.get("reviewer") and current_user.role in (REVIEWER, ADMIN):
        q = q.filter(Inspection.review_completed_by_id == int(a["reviewer"]))
    if a.get("q"):
        like = f"%{a['q'].strip()}%"
        q = q.filter(db.or_(Inspection.code.ilike(like), Inspection.title.ilike(like)))
    if a.get("turbine"):
        q = q.filter(Inspection.turbine_id == int(a["turbine"]))
    if a.get("status"):
        q = q.filter(Inspection.status == a["status"])
    if a.get("from"):
        q = q.filter(Inspection.inspection_date >= a["from"])
    if a.get("to"):
        q = q.filter(Inspection.inspection_date <= a["to"])
    page = q.order_by(Inspection.created_at.desc()).paginate(page=int(a.get("page", 1)), per_page=15,
                                                             error_out=False)
    statuses = ["in_review", "reviewed", "rejected", "reported"]
    if current_user.role != REVIEWER:
        statuses = ["processing", "draft"] + statuses + ["failed"]
    inspectors = (User.query.filter(User.role.in_([INSPECTOR, ADMIN])).order_by(User.name).all()
                  if current_user.role in (REVIEWER, ADMIN) else [])
    reviewers = (User.query.filter(User.role.in_([REVIEWER, ADMIN])).order_by(User.name).all()
                 if current_user.role in (REVIEWER, ADMIN) else [])
    return render_template("inspections/history.html", page=page,
                           turbines=Turbine.query.order_by(Turbine.code).all(), args=a,
                           statuses=[(s, STATUS_LABELS[s]) for s in statuses], inspectors=inspectors,
                           reviewers=reviewers)


# ------------------------------------------------------------------ new

@bp.route("/inspections/new", methods=["GET", "POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def new():
    turbines = Turbine.query.order_by(Turbine.code).all()
    cfg = current_app.config
    if request.method == "POST":
        f = request.form
        files = [x for x in request.files.getlist("media") if x and x.filename]
        errors = []
        turbine = db.session.get(Turbine, int(f.get("turbine_id") or 0))
        if not turbine:
            errors.append("Choose the turbine you inspected.")
        if not files:
            errors.append("Add at least one image or video.")
        allowed = cfg["ALLOWED_IMAGE_EXT"] | cfg["ALLOWED_VIDEO_EXT"]
        for x in files:
            if _ext(x.filename) not in allowed:
                errors.append(f"{x.filename}: file type isn't supported. Use JPG, PNG, BMP, WEBP, MP4, MOV, AVI or MKV.")
        try:
            conf = float(f.get("conf_threshold") or cfg["DEFAULT_CONF"])
            interval = float(f.get("frame_interval_s") or cfg["DEFAULT_FRAME_INTERVAL"])
            if not (0.05 <= conf <= 0.95):
                errors.append("Confidence threshold must be between 0.05 and 0.95.")
            if not (0.1 <= interval <= 30):
                errors.append("Frame interval must be between 0.1 and 30 seconds.")
        except ValueError:
            errors.append("Confidence and frame interval must be numbers.")
            conf, interval = cfg["DEFAULT_CONF"], cfg["DEFAULT_FRAME_INTERVAL"]
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("inspections/new.html", turbines=turbines, form=f,
                                   seg_ready=detector.seg_available(cfg["BLADE_SEG_MODEL_PATH"]), ai=ai_client.status()), 400

        blade = db.session.get(Blade, int(f.get("blade_id") or 0)) if f.get("blade_id") else None
        insp = Inspection(
            code=_next_code(),
            title=f.get("title", "").strip() or None,
            turbine_id=turbine.id,
            blade_id=blade.id if blade and blade.turbine_id == turbine.id else None,
            inspection_date=datetime.strptime(f["inspection_date"], "%Y-%m-%d").date()
            if f.get("inspection_date") else date.today(),
            drone_model=f.get("drone_model", "").strip() or None,
            operator_name=f.get("operator_name", "").strip() or None,
            weather=f.get("weather", "").strip() or None,
            notes=f.get("notes", "").strip() or None,
            conf_threshold=conf,
            frame_interval_s=interval,
            mask_enabled=bool(f.get("mask_enabled")),
            vlm_enabled=bool(f.get("vlm_enabled")) and ai_client.available() and bool(cfg.get("VLM_ENABLED")),
            created_by_id=current_user.id,
            status="queued",
            progress_msg="Queued",
        )
        db.session.add(insp)
        db.session.flush()
        root = Path(cfg["UPLOAD_DIR"])
        rel_dir = Path(f"inspection_{insp.id}") / "media"
        (root / rel_dir).mkdir(parents=True, exist_ok=True)
        too_big = []
        for x in files:
            ext = _ext(x.filename)
            kind = "video" if ext in cfg["ALLOWED_VIDEO_EXT"] else "image"
            rel = rel_dir / f"{uuid.uuid4().hex[:12]}.{ext}"
            x.save(root / rel)
            size = (root / rel).stat().st_size
            if kind == "image" and size > cfg["MAX_IMAGE_MB"] * 1024 * 1024:
                (root / rel).unlink(missing_ok=True)
                too_big.append(x.filename)
                continue
            db.session.add(Media(inspection_id=insp.id, kind=kind,
                                 original_name=secure_filename(x.filename) or x.filename,
                                 stored_path=rel.as_posix(), size_bytes=size))
        if too_big and len(too_big) == len(files):
            db.session.rollback()
            shutil.rmtree(root / f"inspection_{insp.id}", ignore_errors=True)
            flash(f"Every image was over {cfg['MAX_IMAGE_MB']} MB. Resize the images and upload again.", "error")
            return redirect(url_for("inspections.new"))
        audit("inspection.created", "inspection", insp.id, inspection_id=insp.id,
              files=len(files) - len(too_big), turbine=turbine.code)
        db.session.commit()
        if too_big:
            flash(f"Skipped files over {cfg['MAX_IMAGE_MB']} MB: {', '.join(too_big)}", "info")
        worker.start(current_app._get_current_object(), insp.id)
        return redirect(url_for("inspections.detail", insp_id=insp.id))

    pre = request.args.get("turbine", type=int)
    return render_template("inspections/new.html", turbines=turbines,
                           form={"turbine_id": pre, "conf_threshold": cfg["DEFAULT_CONF"],
                                 "frame_interval_s": current_user.default_frame_interval or cfg["DEFAULT_FRAME_INTERVAL"],
                                 "inspection_date": date.today().isoformat(), "vlm_enabled": "1"},
                           seg_ready=detector.seg_available(cfg["BLADE_SEG_MODEL_PATH"]), ai=ai_client.status())


# ------------------------------------------------------------------ results

def viewer_payload(insp, only_with_findings=False):
    by_frame = {}
    for f in insp.findings:
        by_frame.setdefault(f.frame_id, []).append(f.id)
    frames = []
    for fr in insp.frames:
        if only_with_findings and fr.id not in by_frame:
            continue
        frames.append({
            "id": fr.id,
            "url": url_for("main.files", rel=fr.image_path),
            "w": fr.width, "h": fr.height,
            "label": fr.label,
            "kind": fr.media.kind,
            "ts": fr.timestamp_s,
            "findings": by_frame.get(fr.id, []),
        })
    names = detector.class_names(current_app.config["MODEL_PATH"])
    present = {f.class_name for f in insp.findings}
    cat = class_catalog(names + sorted(present - set(names)))
    return {"frames": frames, "findings": [f.to_dict() for f in insp.findings], "classes": cat,
            "counts": insp.counts()}


@bp.route("/inspections/<int:insp_id>")
@login_required
def detail(insp_id):
    insp = _get(insp_id)
    payload = None if insp.is_busy else viewer_payload(insp, only_with_findings=False)
    return render_template("inspections/detail.html", insp=insp, payload=payload, tab="results",
                           ai=ai_client.status())


@bp.route("/inspections/<int:insp_id>/status")
@login_required
def status(insp_id):
    insp = _get(insp_id)
    return jsonify(status=insp.status, label=insp.status_label, progress=insp.progress or 0,
                   message=insp.progress_msg or "", error=insp.error, findings=len(insp.findings),
                   vlm_status=insp.vlm_status)


@bp.route("/inspections/<int:insp_id>/rerun", methods=["POST"])
@login_required
def rerun(insp_id):
    insp = _get(insp_id)
    require(can_manage(insp))
    if insp.is_busy:
        flash("This inspection is already being analyzed.", "info")
    elif insp.report and insp.report.status == "issued":
        flash("The report for this inspection is issued, so the analysis can't run again.", "error")
    else:
        worker.reset_analysis(insp, current_app.config["UPLOAD_DIR"])
        audit("inspection.created", "inspection", insp.id, inspection_id=insp.id, rerun=True, commit=True)
        worker.start(current_app._get_current_object(), insp.id)
        flash("Analysis restarted. Previous findings and review decisions were cleared.", "info")
    return redirect(url_for("inspections.detail", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/delete", methods=["POST"])
@login_required
def delete(insp_id):
    insp = _get(insp_id)
    require(can_delete(insp))
    if insp.is_busy:
        flash("Wait for the analysis to finish before deleting.", "error")
        return redirect(url_for("inspections.detail", insp_id=insp.id))
    code = insp.code
    audit("inspection.deleted", "inspection", insp.id, code=code)
    db.session.delete(insp)
    db.session.commit()
    shutil.rmtree(Path(current_app.config["UPLOAD_DIR"]) / f"inspection_{insp_id}", ignore_errors=True)
    flash(f"Inspection {code} deleted.", "success")
    return redirect(url_for("inspections.history"))


# ------------------------------------------------------------------ review

@bp.route("/inspections/<int:insp_id>/review")
@login_required
def review(insp_id):
    insp = _get(insp_id)
    require(can_open_review_page(insp))
    if insp.is_busy or insp.status == "failed":
        return redirect(url_for("inspections.detail", insp_id=insp.id))
    payload = viewer_payload(insp)
    can_edit = can_review(insp)
    return render_template("inspections/review.html", insp=insp, payload=payload, tab="review", can_edit=can_edit,
                           ai=ai_client.status(), min_fused=current_app.config.get("VLM_MIN_FUSED", 0.35))


def _review_guard(insp):
    if current_user.role not in (REVIEWER, ADMIN):
        return jsonify(error="Only Human Reviewers can accept, reject or edit findings."), 403
    if not can_review(insp):
        return jsonify(error="This inspection isn't open for review."), 409
    return None


VALID_STATUS = {"pending", "accepted", "rejected", "uncertain"}
VALID_SEV = {"low", "medium", "high"}


def _clean_box(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in box]
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    if x2 - x1 < 0.003 or y2 - y1 < 0.003:
        return None
    return [x1, y1, x2, y2]


@bp.route("/api/findings/<int:fid>", methods=["POST"])
@login_required
def update_finding(fid):
    f = db.session.get(Finding, fid)
    if not f or not can_view(f.inspection):
        abort(404)
    insp = f.inspection
    g = _review_guard(insp)
    if g:
        return g
    data = request.get_json(silent=True) or {}
    changes = {}
    if "class_name" in data and data["class_name"] and data["class_name"] != f.class_name:
        changes["class"] = [f.class_name, data["class_name"]]
        f.class_name = data["class_name"][:60]
    if "box" in data:
        b = _clean_box(data["box"])
        if b is None:
            return jsonify(error="The box is too small or invalid. Draw it again."), 400
        if [round(v, 4) for v in b] != [round(v, 4) for v in (f.x1, f.y1, f.x2, f.y2)]:
            changes["box"] = True
            f.x1, f.y1, f.x2, f.y2 = b
    if "severity" in data and data["severity"] in VALID_SEV and data["severity"] != f.severity:
        changes["severity"] = [f.severity, data["severity"]]
        f.severity = data["severity"]
    if "note" in data:
        note = (data.get("note") or "").strip()[:2000]
        if note != (f.reviewer_note or ""):
            changes["note"] = True
            f.reviewer_note = note or None
    if f.source == "ai" and (changes.get("class") or changes.get("box")):
        f.edited = True
    new_status = data.get("status")
    if new_status and new_status not in VALID_STATUS:
        return jsonify(error="Unknown status."), 400
    if changes:
        audit("finding.edited", "finding", f.id, inspection_id=insp.id, **{k: v for k, v in changes.items()})
    if new_status and new_status != f.status:
        old = f.status
        f.status = new_status
        act = {"accepted": "finding.accepted", "rejected": "finding.rejected",
               "uncertain": "finding.uncertain", "pending": "finding.reset"}[new_status]
        audit(act, "finding", f.id, inspection_id=insp.id, previous=old, finding=f.code)
    if new_status or changes:
        f.reviewed_by_id = current_user.id
        f.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(finding=f.to_dict(), counts=insp.counts())


@bp.route("/inspections/<int:insp_id>/findings", methods=["POST"])
@login_required
def add_finding(insp_id):
    insp = _get(insp_id)
    g = _review_guard(insp)
    if g:
        return g
    data = request.get_json(silent=True) or {}
    fr = db.session.get(Frame, int(data.get("frame_id") or 0))
    if not fr or fr.inspection_id != insp.id:
        return jsonify(error="Choose an image or frame first."), 400
    b = _clean_box(data.get("box"))
    if b is None:
        return jsonify(error="Draw a box around the defect first."), 400
    cls = (data.get("class_name") or "").strip()
    if not cls:
        return jsonify(error="Choose the defect type."), 400
    sev = data.get("severity") if data.get("severity") in VALID_SEV else default_severity(cls, (b[2] - b[0]) * (b[3] - b[1]))
    f = Finding(inspection_id=insp.id, frame_id=fr.id, class_name=cls, ai_class_name=None, confidence=None,
                x1=b[0], y1=b[1], x2=b[2], y2=b[3], source="manual", severity=sev, status="accepted",
                reviewer_note=(data.get("note") or "").strip() or None, reviewed_by_id=current_user.id,
                reviewed_at=datetime.utcnow(), first_ts=fr.timestamp_s, last_ts=fr.timestamp_s,
                frame_ids=json.dumps([fr.id]))
    db.session.add(f)
    db.session.flush()
    audit("finding.added", "finding", f.id, inspection_id=insp.id, class_name=cls, frame=fr.id)
    db.session.commit()
    return jsonify(finding=f.to_dict(), counts=insp.counts())


@bp.route("/inspections/<int:insp_id>/complete-review", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def complete_review(insp_id):
    """Reviewer confirms the final findings and approves the inspection."""
    insp = _get(insp_id)
    if not can_review(insp):
        flash("This inspection isn't waiting for review.", "info")
        return redirect(url_for("inspections.review", insp_id=insp.id))
    pending = insp.pending_count
    if pending:
        flash(f"{pending} finding{'s are' if pending != 1 else ' is'} still pending. Review every finding before "
              "confirming the findings.", "error")
        return redirect(url_for("inspections.review", insp_id=insp.id))
    insp.status = "reviewed"
    insp.review_decision = "approved"
    insp.review_comment = (request.form.get("comment") or "").strip()[:4000] or None
    insp.review_completed_by_id = current_user.id
    insp.review_completed_at = datetime.utcnow()
    c = insp.counts()
    audit("review.completed", "inspection", insp.id, inspection_id=insp.id,
          accepted=c["accepted"], rejected=c["rejected"], uncertain=c["uncertain"])
    db.session.commit()
    flash("Findings confirmed and inspection approved. You can now generate the Arabic report.", "success")
    return redirect(url_for("reports.view", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/reject", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def reject_inspection(insp_id):
    """Send the whole inspection back to the inspector (e.g. unusable images), with a reason."""
    insp = _get(insp_id)
    require(can_review(insp))
    comment = (request.form.get("comment") or "").strip()[:4000]
    if not comment:
        flash("Write a reason so the inspector knows what to fix.", "error")
        return redirect(url_for("inspections.review", insp_id=insp.id))
    insp.status = "rejected"
    insp.review_decision = "rejected"
    insp.review_comment = comment
    insp.review_completed_by_id = current_user.id
    insp.review_completed_at = datetime.utcnow()
    audit("review.rejected", "inspection", insp.id, inspection_id=insp.id, reason=comment)
    db.session.commit()
    flash(f"{insp.code} was rejected and returned to the inspector.", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/inspections/<int:insp_id>/reopen-review", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def reopen_review(insp_id):
    insp = _get(insp_id)
    if insp.report and insp.report.status == "issued":
        flash("The report is issued, so the review can't be reopened.", "error")
    elif can_reopen(insp):
        if insp.report:
            db.session.delete(insp.report)
        insp.status = "in_review"
        insp.review_decision = None
        insp.review_completed_at = None
        insp.review_completed_by_id = None
        audit("review.reopened", "inspection", insp.id, inspection_id=insp.id)
        db.session.commit()
        flash("Review reopened. Any draft report was discarded and must be generated again.", "info")
    else:
        abort(403)
    return redirect(url_for("inspections.review", insp_id=insp.id))


# ------------------------------------------------------------------ inspector: submit + downloads

@bp.route("/inspections/<int:insp_id>/submit", methods=["POST"])
@login_required
@roles(INSPECTOR, ADMIN)
def submit(insp_id):
    insp = _get(insp_id)
    require(can_submit(insp))
    if insp.vlm_status == "running":
        flash("Wait for the VLM check to finish before submitting.", "error")
        return redirect(url_for("inspections.detail", insp_id=insp.id))
    resubmit = insp.status == "rejected"
    insp.status = "in_review"
    insp.submitted_at = datetime.utcnow()
    insp.submit_note = (request.form.get("note") or "").strip()[:4000] or None
    insp.review_decision = None
    insp.review_completed_at = None
    insp.review_completed_by_id = None
    audit("inspection.resubmitted" if resubmit else "inspection.submitted", "inspection", insp.id,
          inspection_id=insp.id, note=insp.submit_note)
    db.session.commit()
    flash(f"{insp.code} was submitted for human review.", "success")
    return redirect(url_for("inspections.detail", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/media/<int:mid>/download")
@login_required
def download_original(insp_id, mid):
    insp = _get(insp_id)
    m = db.session.get(Media, mid)
    if not m or m.inspection_id != insp.id:
        abort(404)
    path = Path(current_app.config["UPLOAD_DIR"]) / m.stored_path
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=m.original_name or path.name)


def _annotated_path(insp, fr):
    fs = [f for f in insp.findings if f.frame_id == fr.id and f.status != "rejected"]
    out = Path(current_app.config["UPLOAD_DIR"]) / f"inspection_{insp.id}" / "annotated" / f"frame_{fr.id}.jpg"
    annotate(Path(current_app.config["UPLOAD_DIR"]) / fr.image_path, fs, out, max_side=2400)
    return out


def _annotated_name(fr):
    stem = Path(fr.media.original_name or "image").stem
    return f"{stem}_t{fr.timestamp_s:.1f}s_annotated.jpg" if fr.media.kind == "video" else f"{stem}_annotated.jpg"


@bp.route("/inspections/<int:insp_id>/frames/<int:fid>/annotated.jpg")
@login_required
def download_annotated(insp_id, fid):
    insp = _get(insp_id)
    fr = db.session.get(Frame, fid)
    if not fr or fr.inspection_id != insp.id:
        abort(404)
    return send_file(_annotated_path(insp, fr), as_attachment=request.args.get("inline") != "1",
                     download_name=_annotated_name(fr), mimetype="image/jpeg")


@bp.route("/inspections/<int:insp_id>/download.zip")
@login_required
def download_zip(insp_id):
    """Originals (photos only; videos can be large) + an annotated image for every frame with detections."""
    insp = _get(insp_id)
    root = Path(current_app.config["UPLOAD_DIR"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for m in insp.media:
            if m.kind == "image" and (root / m.stored_path).is_file():
                z.write(root / m.stored_path, f"original/{m.original_name}")
        frames_with = {f.frame_id for f in insp.findings if f.status != "rejected"}
        for fr in insp.frames:
            if fr.id in frames_with:
                z.write(_annotated_path(insp, fr), f"annotated/{_annotated_name(fr)}")
        rows = ["code,class,yolo_confidence,vlm_verdict,combined,severity,review_status,evidence"]
        for f in insp.findings:
            rows.append(",".join(str(x if x is not None else "") for x in (
                f.code, f.class_name, f.confidence and round(f.confidence, 3), f.vlm_verdict,
                f.fused_confidence and round(f.fused_confidence, 3), f.severity, f.status,
                (f.frame.label if f.frame else "").replace(",", " "))))
        z.writestr("findings.csv", "\n".join(rows))
    buf.seek(0)
    audit("inspection.downloaded", "inspection", insp.id, inspection_id=insp.id, commit=True)
    return send_file(buf, as_attachment=True, download_name=f"{insp.code}_images.zip", mimetype="application/zip")


# ------------------------------------------------------------------ VLM

@bp.route("/inspections/<int:insp_id>/vlm", methods=["POST"])
@login_required
def run_vlm(insp_id):
    insp = _get(insp_id)
    require(can_run_vlm(insp))
    if not ai_client.available():
        flash("No AI key is set in .env, so the VLM check can't run.", "error")
    elif insp.vlm_status == "running":
        flash("The VLM check is already running.", "info")
    else:
        insp.vlm_enabled = True
        insp.vlm_status = "running"
        db.session.commit()
        worker.start_vlm(current_app._get_current_object(), insp.id)
        audit("inspection.vlm_started", "inspection", insp.id, inspection_id=insp.id, commit=True)
        flash("VLM cross-check started. Results appear on this page when it finishes.", "info")
    return redirect(url_for("inspections.detail", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/accept-agreed", methods=["POST"])
@login_required
def accept_agreed(insp_id):
    """Accept every pending finding where YOLO and the VLM agree (combined score above the threshold)."""
    insp = _get(insp_id)
    g = _review_guard(insp)
    if g:
        return g
    thr = float(current_app.config.get("VLM_MIN_FUSED", 0.35))
    n = 0
    for f in insp.findings:
        if f.status == "pending" and f.source == "ai" and f.vlm_verdict in ("confirmed", "relabeled") \
                and (f.fused_confidence or 0) >= thr:
            f.status = "accepted"
            f.reviewed_by_id = current_user.id
            f.reviewed_at = datetime.utcnow()
            audit("finding.accepted", "finding", f.id, inspection_id=insp.id, finding=f.code, bulk="models_agree")
            n += 1
    db.session.commit()
    return jsonify(accepted=n, findings=[f.to_dict() for f in insp.findings], counts=insp.counts())
