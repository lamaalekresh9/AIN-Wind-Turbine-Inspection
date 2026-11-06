from datetime import datetime
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import ChatMessage, Finding, Inspection, Report
from ..services import ai_client
from ..services import chat as chat_service
from ..services import report_writer
from ..services.evidence import grid_location
from ..services.pdf import build_pdf
from ..permissions import (ADMIN, REVIEWER, can_view_report, can_write_report, get_inspection_or_404, require,
                           roles, visible_inspections)
from ..utils import audit

bp = Blueprint("reports", __name__)


def _get(insp_id):
    return get_inspection_or_404(insp_id)


def gate_problem(insp):
    """FR-08: the report can't be generated until every finding is resolved and the review is complete."""
    if insp.is_busy:
        return "The AI analysis is still running."
    if insp.status == "failed":
        return "The AI analysis failed. Run it again first."
    if insp.status == "draft":
        return "The inspector hasn't submitted this inspection for review yet."
    if insp.status == "rejected":
        return "The reviewer rejected this inspection and returned it to the inspector."
    pending = insp.pending_count
    if pending:
        return (f"{pending} finding{'s are' if pending != 1 else ' is'} still pending review. "
                "Every finding must be accepted, rejected, edited or marked uncertain first.")
    if insp.status == "in_review":
        return "All findings are resolved, but the reviewer hasn't confirmed the final findings yet (Human review tab)."
    return None


@bp.route("/inspections/<int:insp_id>/report")
@login_required
def view(insp_id):
    insp = _get(insp_id)
    require(can_view_report(insp))
    report = insp.report
    rows = []
    if report:
        texts = {x["id"]: x for x in report.data.get("findings", [])}
        for f in insp.approved_findings:
            rows.append({"f": f, "text": report_writer.finding_text(texts.get(f.code)), "loc": grid_location(f)[1]})
    return render_template("reports/report.html", insp=insp, report=report, rows=rows, tab="report",
                           gate=gate_problem(insp), ai=ai_client.status(),
                           llm_on=current_app.config.get("LLM_REPORT_ENABLED"),
                           fields=report_writer.FIELDS, labels=report_writer.FIELD_LABELS_AR,
                           risk=(report.data.get("overall_risk") if report else None)
                           or report_writer.overall_risk(insp.approved_findings),
                           editing=request.args.get("edit") == "1" and report and report.status == "draft"
                           and can_write_report(insp))


@bp.route("/inspections/<int:insp_id>/report/generate", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def generate(insp_id):
    insp = _get(insp_id)
    require(can_write_report(insp))
    problem = gate_problem(insp)
    if problem:
        audit("report.blocked", "inspection", insp.id, inspection_id=insp.id, reason=problem, commit=True)
        flash(f"Report not generated. {problem}", "error")
        return redirect(url_for("reports.view", insp_id=insp.id))
    if insp.report and insp.report.status == "issued":
        flash("This report is already issued and can't be regenerated.", "error")
        return redirect(url_for("reports.view", insp_id=insp.id))
    content, generator, note = report_writer.generate(insp)
    rep = insp.report or Report(inspection_id=insp.id)
    rep.title = f"تقرير فحص شفرات توربين الرياح {insp.turbine.code}"
    rep.data = content
    rep.generator = generator
    rep.llm_model = ai_client.settings()["model"] if generator == "llm" else None
    rep.generation_note = note
    rep.created_by_id = current_user.id
    rep.status = "draft"
    db.session.add(rep)
    audit("report.generated", "inspection", insp.id, inspection_id=insp.id, generator=generator)
    db.session.commit()
    if generator == "llm":
        flash("Arabic report written by the language model. Read it through, edit anything that needs it, then issue it.", "success")
    else:
        flash(f"Arabic report generated. {note}", "info")
    return redirect(url_for("reports.view", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/report/save", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def save(insp_id):
    insp = _get(insp_id)
    require(can_write_report(insp))
    rep = insp.report
    if not rep or rep.status != "draft":
        flash("Only draft reports can be edited.", "error")
        return redirect(url_for("reports.view", insp_id=insp.id))
    f = request.form
    data = rep.data
    data["executive_summary"] = f.get("executive_summary", "").strip()
    items = []
    for item in data.get("findings", []):
        t = report_writer.finding_text(item)
        items.append({"id": item["id"], **{k: f.get(f"{k}_{item['id']}", t[k]).strip() for k in report_writer.FIELDS}})
    data["findings"] = items
    data["recommendations"] = [x.strip() for x in f.get("recommendations", "").splitlines() if x.strip()]
    data["limitations"] = [x.strip() for x in f.get("limitations", "").splitlines() if x.strip()]
    rep.title = f.get("title", rep.title).strip() or rep.title
    rep.data = data
    audit("report.edited", "report", rep.id, inspection_id=insp.id)
    db.session.commit()
    flash("Report saved.", "success")
    return redirect(url_for("reports.view", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/report/issue", methods=["POST"])
@login_required
@roles(REVIEWER, ADMIN)
def issue(insp_id):
    insp = _get(insp_id)
    require(can_write_report(insp))
    rep = insp.report
    if not rep or rep.status != "draft":
        flash("There's no draft report to issue.", "error")
        return redirect(url_for("reports.view", insp_id=insp.id))
    rep.status = "issued"
    rep.issued_by_id = current_user.id
    rep.issued_at = datetime.utcnow()
    insp.status = "reported"
    audit("report.issued", "report", rep.id, inspection_id=insp.id)
    db.session.commit()
    flash("Report issued. It's now locked and available in the inspection history.", "success")
    return redirect(url_for("reports.view", insp_id=insp.id))


@bp.route("/inspections/<int:insp_id>/report.pdf")
@login_required
def pdf(insp_id):
    insp = _get(insp_id)
    rep = insp.report
    if not rep:
        abort(404)
    require(can_view_report(insp))
    out_dir = Path(current_app.config["UPLOAD_DIR"]) / f"inspection_{insp.id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{insp.code}_report.pdf"
    build_pdf(insp, rep, current_app.config["UPLOAD_DIR"], out)
    audit("report.exported", "report", rep.id, inspection_id=insp.id, commit=True)
    suffix = "" if rep.status == "issued" else "_DRAFT"
    return send_file(out, as_attachment=request.args.get("inline") != "1",
                     download_name=f"{insp.code}_report{suffix}.pdf", mimetype="application/pdf")


# ------------------------------------------------------------------ AI chat ("Ask Ain")

@bp.route("/inspections/<int:insp_id>/assistant")
@login_required
def assistant(insp_id):
    insp = _get(insp_id)
    focus = db.session.get(Finding, request.args.get("finding", type=int) or 0)
    if focus and focus.inspection_id != insp.id:
        focus = None
    return render_template("reports/assistant.html", insp=insp, tab="assistant", messages=insp.messages,
                           ready=not insp.is_busy and insp.status != "failed", ai=ai_client.status(),
                           chat_on=chat_service.available(), focus=focus)


@bp.route("/inspections/<int:insp_id>/assistant/ask", methods=["POST"])
@login_required
def ask(insp_id):
    insp = _get(insp_id)
    if insp.is_busy or insp.status == "failed":
        return jsonify(error="Wait for the detection to finish before asking."), 409
    data = request.get_json(silent=True) or {}
    q = (data.get("question") or "").strip()[:2000]
    if not q:
        return jsonify(error="Type a question first."), 400
    focus = db.session.get(Finding, int(data.get("finding_id") or 0))
    if focus and focus.inspection_id != insp.id:
        focus = None
    history = list(insp.messages)
    answer, mode = chat_service.answer(insp, q, history, focus)
    db.session.add_all([
        ChatMessage(inspection_id=insp.id, user_id=current_user.id, role="user", content=q,
                    finding_id=focus.id if focus else None),
        ChatMessage(inspection_id=insp.id, role="assistant", content=answer, mode=mode,
                    finding_id=focus.id if focus else None),
    ])
    audit("chat.asked", "inspection", insp.id, inspection_id=insp.id, mode=mode,
          finding=focus.code if focus else None)
    db.session.commit()
    return jsonify(answer=answer, mode=mode)


@bp.route("/inspections/<int:insp_id>/assistant/clear", methods=["POST"])
@login_required
def clear_chat(insp_id):
    insp = _get(insp_id)
    for m in list(insp.messages):
        db.session.delete(m)
    db.session.commit()
    return redirect(url_for("reports.assistant", insp_id=insp.id))


# ------------------------------------------------------------------ reports list (reviewers + admins)

@bp.route("/reports")
@login_required
@roles(REVIEWER, ADMIN)
def index():
    q = Report.query.join(Inspection).filter(Inspection.id.in_(visible_inspections().with_entities(Inspection.id)))
    st = request.args.get("status")
    if st in ("draft", "issued"):
        q = q.filter(Report.status == st)
    reports = q.order_by(Report.updated_at.desc()).all()
    awaiting = (visible_inspections().filter(Inspection.status == "reviewed")
                .filter(~Inspection.report.has()).order_by(Inspection.review_completed_at).all())
    return render_template("reports/index.html", reports=reports, awaiting=awaiting, args=request.args)
