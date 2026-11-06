# Ain (عين): AI wind turbine blade inspection

Flask web platform that detects visible wind turbine blade defects in drone images and videos with YOLO. A human reviewer approves every finding, and the platform then generates an editable Arabic inspection report with PDF export.

Stack: Flask, SQLite (SQLAlchemy), plain HTML/CSS/JS, Ultralytics YOLO26, OpenAI (VLM + LLM) or Google Gemini, ReportLab (RTL PDF).

## Run it

```bash
python -m venv venv
# Windows: venv\Scripts\activate     macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env               # macOS/Linux: cp .env.example .env
python app.py
```

Open http://127.0.0.1:5000.

**Model settings** (confidence threshold, NMS IoU, max detections, image size, CPU/GPU, model path) are at the top of `app.py`. Change `CONFIDENCE = 0.25` and restart. It's the default for new inspections and the Live detection page; users can still adjust it per inspection or live. On the first run, the database is created at `instance/ain.db` and seeded with three demo turbines and these accounts:

| Role | Email | Password |
|---|---|---|
| Admin | admin@ain.local | Admin@123 |
| Reviewer | reviewer@ain.local | Review@123 |
| Inspector | inspector@ain.local | Inspect@123 |

## VLM + LLM (OpenAI)

1. Create a key at https://platform.openai.com/api-keys (the account needs a little credit) and put it in `.env`: `OPENAI_API_KEY=sk-...`
2. Restart `python app.py`. `AI_PROVIDER = "openai"` and `OPENAI_MODEL = "gpt-6-luna"` are set in `app.py`.
3. Check it: sign in as admin → Model & system → **Test AI connection**.

Cost: gpt-6-luna is $0.10 per 1M input tokens and $0.50 per 1M output tokens, so one image check is a fraction of a cent.
To use Gemini's free tier instead, set `AI_PROVIDER = "gemini"`, `AI_REQUESTS_PER_MINUTE = 8` and `GEMINI_API_KEY` in `.env`.
Without any key, Ain runs on YOLO only and writes reports from the Arabic templates in `core/services/knowledge.py`.

**1) VLM cross-check.** After YOLO, each image or frame with detections is sent to the VLM with the boxes drawn and listed.
For every box it answers *confirmed*, *relabeled* (other class) or *rejected* (no defect), with a confidence and a reason,
and it can add clear defects YOLO missed. Scores are fused:

| VLM verdict | Combined score |
|---|---|
| confirmed / relabeled | `(1-w)·YOLO + w·VLM` |
| rejected | `(1-w)·YOLO + w·(1-VLM)` |
| added by VLM | `w·VLM` |

`w = VLM_WEIGHT` (0.4). Rejected boxes below `VLM_MIN_COMBINED` are flagged as likely false alarms (or pre-rejected if
`VLM_AUTO_REJECT = True`). Reviewers get a "VLM disagrees" filter and "Accept all where both models agree".
Live detection has a "Cross-check with VLM" button too.

**VLM prompt.** Everything the VLM is told lives in `core/services/vlm_prompts.py`: blade anatomy, the normal blade
features that are *not* defects (lightning receptors, drain holes, vortex generators, seams, dirt, shadows, glare...),
a per-class guide (what each defect looks like and what it gets confused with), a step-by-step procedure, confidence
calibration and worked examples. Each box is also sent as a zoomed crop (`VLM_SEND_CROPS`). Add your own notes in
`VLM_EXTRA_INSTRUCTIONS` in `app.py`.

**2) LLM report.** After the review, the LLM writes the Arabic report from accepted findings + their evidence crops. For
each defect: description, location, severity assessment, consequences if untreated, recommended inspection, recommended
maintenance; plus an executive summary, overall risk, recommendations and limitations. Any finding id the model invents is
dropped, and missing fields fall back to the templates. Everything stays editable before the report is issued.

**Free-tier notes.** Gemini's free tier is roughly 10 requests/minute and ~1,500/day for Flash models (check your
limits at https://aistudio.google.com/rate-limit). Ain throttles itself to `AI_REQUESTS_PER_MINUTE = 8` and caps
`VLM_MAX_FRAMES = 30` per inspection. On the free tier, Google may use prompts and images to improve its products, so
don't upload confidential client imagery on a free key.

To use a GPU, install the CUDA build of PyTorch first (see pytorch.org), then set `DEVICE = "0"` in `app.py`.

Useful commands:
```bash
flask --app app reset-db       # wipe and reseed the database
flask --app app create-admin   # create your own admin account
```

## AI chat ("Ask Ain")

Every inspection has an **Ask Ain** tab once detection finishes. The assistant sees the inspection details, every
finding (YOLO class and confidence, VLM verdict and reason, combined score, review status, notes) and up to
`CHAT_MAX_IMAGES` evidence crops, and answers in Arabic or English. Conversations are saved per inspection.
The Live detection page has the same chat for a single image.

## Roles and workflow

Each role has its own dashboard, sidebar and pages. Access rules live in one place, `core/permissions.py`,
and every route checks them on the server, so typing a URL by hand doesn't get around them.
Another inspector's inspection returns **404**, and an action outside your role returns **403**.

| Role | Can | Can't |
|---|---|---|
| Inspector | Upload images and videos, run YOLO + VLM, see results, download originals, annotated images and ZIP, use Ask Ain and Live detection, submit for review, fix and resubmit after a rejection, view the final report once issued | See other inspectors' inspections, accept or reject findings, write or issue reports, open admin pages |
| Human Reviewer | See every *submitted* inspection, accept, reject or edit findings, add comments, approve or reject the whole inspection, generate, edit and issue the Arabic report, download the PDF | Upload, see unsubmitted drafts, manage users |
| Admin | See everything, add, edit and deactivate users, assign Inspector or Reviewer, change settings (`/admin/settings`), read system logs, review and write reports | (Admins are created from the command line: `flask --app app create-admin`) |

Statuses: **Ready to submit** (after the AI analysis) → **Pending review** (submitted) → **Approved** or **Rejected** (rejected inspections go back to the inspector) → **Report issued** (final).
A report can only be generated from approved findings and is final only after the reviewer issues it.

New sign-ups are always Inspectors and start with an empty history.

## Pages

| Page | URL |
|---|---|
| Home | `/` |
| Login / Sign up | `/login`, `/signup` |
| Dashboard (different for each role) | `/dashboard` |
| Submit for review | `POST /inspections/<id>/submit` |
| Reports list (reviewer / admin) | `/reports` |
| Downloads | `/inspections/<id>/download.zip`, `.../media/<mid>/download`, `.../frames/<fid>/annotated.jpg` |
| New inspection / upload | `/inspections/new` |
| AI defect detection results | `/inspections/<id>` |
| Human verification and review | `/inspections/<id>/review` |
| Arabic report generator | `/inspections/<id>/report` (+ edit and PDF export) |
| Live detection (camera / video / image) | `/live` |
| AI chat about an inspection | `/inspections/<id>/assistant` |
| Inspection history | `/inspections` |
| Turbine management | `/turbines` |
| Support / help center | `/help` |
| Profile / settings | `/profile` |
| Admin: users, settings, audit log, support requests, model info | `/admin/...` |

## How the proposal requirements map to the code

| Req | Where |
|---|---|
| FR-01 Media upload + validation | `blueprints/inspections.py: new()` |
| FR-02 Frame extraction with timestamps | `services/worker.py: _process_video()` |
| FR-03 Blade masking (toggle) | `services/detector.py: mask_blade()`. Passthrough until `BLADE_SEG_MODEL_PATH` points to a YOLO-seg model |
| FR-04 Detection (class, confidence, box) | `services/detector.py: predict()` |
| FR-05 Evidence persistence | `models.py: Frame, Finding`. Every finding links to its frame and timestamp |
| FR-06 Duplicate consolidation | `services/consolidate.py`. Same class + IoU or centre distance + frame gap |
| FR-07 Review workflow + audit log | `review.html`, `static/js/review.js`, `utils.audit()`, `/admin/audit` |
| FR-08 Approval gate | `reports.gate_problem()`, enforced on the server, not only in the UI |
| FR-04 Detection + VLM fusion | `services/detector.py`, `services/vlm.py`, `services/ai_client.py` |
| FR-10 Arabic LLM report + RTL PDF | `services/report_writer.py`, `services/pdf.py` |
| FR-11 Inspection history | `/inspections` |
| NFR-02 Traceability | Only accepted findings go into the report; each one cites its source frame |

## Project structure

```
app.py                          entry point + model settings (confidence, IoU, device)
config.py, .env.example, requirements.txt
models/best.pt                  YOLO26l, trained at 1024 px (crack, hide_craze, surface_eye)
core/
  __init__.py  models.py  seed.py  utils.py
  permissions.py                who can see / do what (used by routes and templates)
  settings_store.py             admin-editable settings saved in the DB
  blueprints/  main, auth, dashboard, inspections, reports, turbines, profile, admin
  services/    detector, worker, consolidate, evidence, ai_client, vlm, report_writer, pdf, knowledge
  templates/   Jinja pages
  static/      css/app.css, js/(app, viewer, review).js, fonts, vendor/chart.umd.js
instance/                       created at runtime: SQLite DB + uploads
```

## Notes

- Live detection: the camera mode runs in the browser, which only allows camera access on `http://localhost` / `http://127.0.0.1` or over HTTPS. To use a phone camera on the same Wi-Fi, run behind HTTPS (for example `flask --app app run --host 0.0.0.0 --cert adhoc`, which needs `pip install pyopenssl`). Live detection doesn't save anything; use New inspection for the reviewed workflow.

- Defect references: the Arabic text in `services/knowledge.py` is the reference text the Arabic report is built from. Have the team check it against your sources before the final evaluation.
- Swapping models: replace `models/best.pt`. Class names are read from the model. Classes from WTBs2025 (erosion, lightning strike, oil leakage) already have Arabic entries; any other class falls back to a generic description.
- Video analysis runs in a background thread, so you can close the page while it works. Don't run with Flask's auto-reloader, because it would start the analysis twice. `app.py` already disables it.
