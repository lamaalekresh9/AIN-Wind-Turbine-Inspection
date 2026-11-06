from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import SupportTicket
from ..utils import audit

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    return render_template("home.html", public_page=True)


FAQS = [
    ("What images work best?",
     "Close-range RGB photos of the blade surface taken by a drone in daylight. The model was trained at 1024 px, so "
     "any resolution works, but blurry or very distant shots will miss small defects."),
    ("Which defects does Ain detect?",
     "The current model detects three visible surface defect types: cracks, hidden crazing (fine hairline cracks under "
     "the coating) and surface eyes (pinholes and pits). Internal damage that isn't visible in a photo is out of scope."),
    ("How does video analysis work?",
     "Ain samples one frame every N seconds (you choose N when you start the inspection), runs detection on each frame, "
     "then merges detections of the same defect across neighbouring frames so it appears once in the findings list."),
    ("Why can't I generate the report yet?",
     "Every finding must be reviewed first. Accept, reject, edit or mark each one as uncertain, then select Complete "
     "review. Only accepted findings go into the Arabic report; uncertain ones are listed as needing re-inspection."),
    ("Who can review findings?",
     "Reviewers and admins. Inspectors can upload media and view results but can't approve findings or issue reports."),
    ("What does the VLM cross-check do?",
     "After YOLO finds defects, a vision-language model (Gemini by default) looks at the same image and says, for each "
     "box, whether it agrees there is a defect, thinks it's a different type, or sees no defect. The two scores are "
     "combined. Boxes the VLM disagrees with are flagged as likely false alarms, and clear defects YOLO missed are added "
     "as \"Found by VLM\". A reviewer still decides every finding."),
    ("What can I ask the AI assistant?",
     "Open the Ask Ain tab of any inspection after the detection finishes. Ask in Arabic or English about the findings, "
     "why YOLO and the VLM disagree, how serious a defect is, what happens if it isn't repaired, or what maintenance to "
     "plan. Pick a finding on the right to ask about that one. On the Live detection page you can also ask about a single image."),
    ("Which AI writes the report?",
     "A language model (Gemini by default) writes the Arabic report from the accepted findings and their evidence images. "
     "If no API key is set or the free limit is reached, Ain falls back to fixed Arabic templates."),
    ("Can I edit the Arabic report?",
     "Yes. After the report is generated, reviewers can edit every section, save drafts, and export a PDF. Issuing the "
     "report locks it."),
    ("What does the confidence score mean?",
     "It's the model's own certainty for that box, from 0 to 100%. Findings below the threshold you set are discarded "
     "before review. A lower threshold finds more defects but adds more false alarms to review."),
    ("What is blade masking?",
     "An optional step that removes the sky, tower and ground before detection. It needs a blade segmentation model. "
     "Until one is configured, the toggle is recorded and images are analyzed unmasked."),
]

STEPS = [
    ("Add the turbine", "Open Turbines and register the turbine with its site and blades A, B and C."),
    ("Start an inspection", "Choose the turbine and blade, add the flight details, and upload photos or a video."),
    ("Wait for AI analysis", "Ain detects defects on every image or sampled frame. Progress is shown live."),
    ("Review every finding", "A reviewer accepts, rejects, corrects or marks each finding uncertain, then completes the review."),
    ("Generate the Arabic report", "Ain writes the report from accepted findings only. Edit it and export a PDF."),
]


@bp.route("/help", methods=["GET", "POST"])
def help_center():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not (name and email and subject and message):
            flash("Fill in your name, email, subject and message.", "error")
        else:
            t = SupportTicket(user_id=current_user.id if current_user.is_authenticated else None,
                              name=name, email=email, subject=subject, message=message,
                              topic=request.form.get("topic"))
            db.session.add(t)
            db.session.flush()
            audit("support.ticket", "ticket", t.id, subject=subject)
            db.session.commit()
            flash("Message sent. The support team will reply by email.", "success")
            return redirect(url_for("main.help_center") + "#contact")
    return render_template("help.html", faqs=FAQS, steps=STEPS)


@bp.route("/files/<path:rel>")
@login_required
def files(rel):
    """Uploaded media and frames. Only served when the user may see the inspection they belong to."""
    import re

    from ..extensions import db
    from ..models import Inspection
    from ..permissions import can_view

    root = Path(current_app.config["UPLOAD_DIR"]).resolve()
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file():
        abort(404)
    m = re.match(r"inspection_(\d+)/", rel)
    if not m or not can_view(db.session.get(Inspection, int(m.group(1)))):
        abort(404)
    return send_from_directory(root, rel)
