"""Loads the sample inspections in demo_data/ into a fresh database, automatically, on the first run.

What is in demo_data/:
  images/           real blade photos: WTBD test-split photos of the earlier merged v1.2 model and WTBs2025 photos
  manifest.json     the sample inspections: who uploaded them, when, and what happened in review.
                    The detections in it are the real output of the earlier merged v1.2 model on those photos
                    (confidence >= 0.25); the sample data was kept as it was when models/best.pt was switched to Ain 10.
                    Only the human side (reviewer decisions, comments, dates) is scripted, and the reviewer
                    decisions follow the dataset's own ground-truth labels.
  vlm_results.json  saved VLM verdicts, applied on load (see below). DEMO_CASES.md lists where each YOLO + VLM case
                    appears.

VLM results: the admin "Model & system" page has a button that runs the VLM cross-check on the sample images that
have no saved verdict yet and adds them to demo_data/vlm_results.json (saved verdicts are kept). The file is applied
every time the sample data is loaded (fresh database, reset-db, a copy of the folder on another laptop).

It runs once per database: an "demo_loaded" flag is stored, so deleting the sample inspections from the UI
does not bring them back. `flask --app app reset-db` creates a new database and loads them again.
Turn it off with DEMO_DATA = False in app.py.
"""
import json
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from .extensions import db
from .models import AppSetting, AuditLog, Blade, Finding, Frame, Inspection, Media, Report, SupportTicket, \
    TicketReply, Turbine, User

FLAG = "demo_loaded"
MAP_KEY = "demo_inspections"          # {inspection id: index in manifest.json}
STATE_KEY = "demo_vlm_state"          # progress of the "run VLM on sample inspections" job
RESULTS_FILE = "vlm_results.json"
PENDING_STATUSES = ("draft", "in_review", "rejected")   # nobody has decided yet: the VLM may relabel and add boxes


def _ts(base, days_ago, hour=10, minute=0):
    d = base - timedelta(days=days_ago)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _log(when, action, user, insp=None, entity="inspection", entity_id=None, **details):
    db.session.add(AuditLog(
        user_id=user.id if user else None, inspection_id=insp.id if insp else None, action=action,
        entity=entity, entity_id=entity_id if entity_id is not None else (insp.id if insp else None),
        details=json.dumps(details, ensure_ascii=False) if details else None, created_at=when))


def load_if_needed(app):
    cfg = app.config
    if not cfg.get("DEMO_DATA", True):
        return
    folder = Path(cfg.get("DEMO_DATA_DIR") or Path(cfg["INSTANCE_DIR"]).parent / "demo_data")
    manifest = folder / "manifest.json"
    if not manifest.exists():
        return
    if db.session.get(AppSetting, FLAG) or Inspection.query.first():
        return
    try:
        _load(app, folder, json.loads(manifest.read_text(encoding="utf-8")))
        db.session.add(AppSetting(key=FLAG, value=datetime.utcnow().isoformat(timespec="seconds")))
        db.session.commit()
        print(" * Sample inspections loaded from demo_data/")
    except Exception as e:  # noqa: BLE001 - never stop the app from starting over demo data
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f" * Could not load demo_data/: {e}")


def _load(app, folder, m):
    now = datetime.utcnow()
    upload_root = Path(app.config["UPLOAD_DIR"])

    # ---------------------------------------------------------------- users and turbines
    users = {}
    for u in m.get("users", []):
        user = User.query.filter_by(email=u["email"]).first()
        if not user:
            user = User(name=u["name"], email=u["email"], role=u["role"], organization=u.get("organization", "Ain Demo"))
            user.set_password(u["password"])
            db.session.add(user)
        user.job_title = u.get("job_title") or user.job_title
        user.created_at = _ts(now, u.get("joined_days_ago", 60), 9)
        users[u["email"]] = user
    for u in User.query.all():
        users.setdefault(u.email, u)

    for t in m.get("turbines", []):
        if Turbine.query.filter_by(code=t["code"]).first():
            continue
        tb = Turbine(**{k: v for k, v in t.items() if k != "blade_length_m"})
        L = t.get("blade_length_m") or round(t["rotor_diameter_m"] / 2 - 2, 1)
        for pos in "ABC":
            tb.blades.append(Blade(position=pos, serial=f"{t['code']}-{pos}", length_m=L,
                                   material="Glass-fibre reinforced epoxy", manufacturer=t.get("manufacturer"),
                                   install_year=t.get("commission_year")))
        db.session.add(tb)
    db.session.flush()

    # ---------------------------------------------------------------- inspections, oldest first
    from .services.knowledge import default_severity
    from .services import report_writer

    model_name = Path(app.config["MODEL_PATH"]).name
    saved = read_vlm_results(folder)
    plans = sorted(enumerate(m["inspections"]), key=lambda t: -t[1]["days_ago"])
    demo_map = {}
    for n, (pidx, p) in enumerate(plans, start=1):
        sv = (saved.get("inspections") or {}).get(str(pidx)) if saved else None
        created = _ts(now, p["days_ago"], p.get("hour", 9), p.get("minute", 15))
        inspector = users[p["inspector"]]
        reviewer = users.get(p.get("reviewer")) if p.get("reviewer") else None
        turbine = Turbine.query.filter_by(code=p["turbine"]).first()
        blade = next((b for b in turbine.blades if b.position == p.get("blade")), None)
        insp = Inspection(
            code=f"INS-{created.year}-{n:04d}", title=p.get("title"), turbine_id=turbine.id,
            blade_id=blade.id if blade else None, inspection_date=created.date(),
            drone_model=p.get("drone_model"), operator_name=p.get("operator"), weather=p.get("weather"),
            notes=p.get("notes"), conf_threshold=p.get("conf", 0.25), frame_interval_s=1.0,
            model_name=model_name, vlm_enabled=True, status="draft", progress=100,
            progress_msg="Analysis complete", created_by_id=inspector.id, created_at=created,
            analyzed_at=created + timedelta(seconds=p.get("analysis_s", 20)),
            processing_seconds=p.get("analysis_s", 20),
        )
        db.session.add(insp)
        db.session.flush()
        demo_map[str(insp.id)] = pidx
        _log(created, "inspection.created", inspector, insp, files=len(p["images"]), turbine=turbine.code)
        _log(insp.analyzed_at, "inspection.analyzed", inspector, insp,
             findings=sum(len(i["detections"]) for i in p["images"]), seconds=insp.processing_seconds)

        rel_dir = Path(f"inspection_{insp.id}") / "media"
        (upload_root / rel_dir).mkdir(parents=True, exist_ok=True)
        decided_at = None
        if p.get("reviewed_days_ago") is not None:
            decided_at = _ts(now, p["reviewed_days_ago"], p.get("review_hour", 13), 5)
        for img in p["images"]:
            src = folder / "images" / img["file"]
            rel = rel_dir / f"{uuid.uuid4().hex[:12]}.jpg"
            shutil.copyfile(src, upload_root / rel)
            media = Media(inspection_id=insp.id, kind="image", original_name=img.get("name", img["file"]),
                          stored_path=rel.as_posix(), size_bytes=(upload_root / rel).stat().st_size,
                          width=img["w"], height=img["h"])
            db.session.add(media)
            db.session.flush()
            fr = Frame(inspection_id=insp.id, media_id=media.id, image_path=rel.as_posix(), width=img["w"],
                       height=img["h"], detections_count=len(img["detections"]))
            db.session.add(fr)
            db.session.flush()
            made = []
            for d in img["detections"]:
                x1, y1, x2, y2 = d["box"]
                r = d.get("review") or {}
                status = r.get("status", "pending") if decided_at or r.get("early") else "pending"
                cls = r.get("class") or d["class"]
                f = Finding(
                    inspection_id=insp.id, frame_id=fr.id, class_name=cls, ai_class_name=d["class"],
                    confidence=d["conf"], x1=x1, y1=y1, x2=x2, y2=y2,
                    ai_box=json.dumps([round(v, 5) for v in d["box"]]), source="ai",
                    severity=r.get("severity") or default_severity(cls, (x2 - x1) * (y2 - y1)),
                    status=status, edited=cls != d["class"], frame_ids=json.dumps([fr.id]),
                    reviewer_note=r.get("note") if status != "pending" else None, created_at=insp.analyzed_at,
                )
                if status != "pending" and reviewer:
                    f.reviewed_by_id, f.reviewed_at = reviewer.id, decided_at
                db.session.add(f)
                made.append(f)
            if sv:
                _apply_saved_image(insp, fr, made, (sv.get("images") or {}).get(img["file"]), p["status"],
                                   insp.analyzed_at)
            for a in (img.get("added") or []) if decided_at else []:
                x1, y1, x2, y2 = a["box"]
                db.session.add(Finding(
                    inspection_id=insp.id, frame_id=fr.id, class_name=a["class"], ai_class_name=None,
                    confidence=None, x1=x1, y1=y1, x2=x2, y2=y2, source="manual",
                    severity=a.get("severity") or default_severity(a["class"], (x2 - x1) * (y2 - y1)),
                    status="accepted", reviewer_note=a.get("note"), reviewed_by_id=reviewer.id if reviewer else None,
                    reviewed_at=decided_at, frame_ids=json.dumps([fr.id]), created_at=decided_at))
        db.session.flush()

        if sv:
            insp.vlm_status = sv.get("status", "done")
            insp.vlm_model = saved.get("model")
            insp.vlm_frames_checked = sv.get("frames_checked", 0)
            insp.vlm_added = sv.get("added", 0)
            insp.vlm_note = sv.get("note")

        # ------------------------------------------------------------ workflow
        st = p["status"]
        if st != "draft":
            insp.submitted_at = _ts(now, p["submitted_days_ago"], p.get("submit_hour", 15), 40)
            insp.submit_note = p.get("submit_note")
            _log(insp.submitted_at, "inspection.submitted", inspector, insp, note=insp.submit_note)
            insp.status = "in_review"
        if decided_at and reviewer:
            for f in insp.findings:
                if f.source == "manual":
                    _log(decided_at, "finding.added", reviewer, insp, entity="finding", entity_id=f.id,
                         class_name=f.class_name, frame=f.frame_id)
                elif f.status != "pending":
                    _log(decided_at, f"finding.{f.status}", reviewer, insp, entity="finding", entity_id=f.id,
                         previous="pending", finding=f.code)
        if st == "rejected":
            insp.status, insp.review_decision = "rejected", "rejected"
            insp.review_comment = p.get("review_comment")
            insp.review_completed_by_id, insp.review_completed_at = reviewer.id, decided_at
            _log(decided_at, "review.rejected", reviewer, insp, reason=insp.review_comment)
        elif st in ("reviewed", "reported"):
            insp.status, insp.review_decision = "reviewed", "approved"
            insp.review_comment = p.get("review_comment")
            insp.review_completed_by_id, insp.review_completed_at = reviewer.id, decided_at
            c = insp.counts()
            _log(decided_at, "review.completed", reviewer, insp, accepted=c["accepted"], rejected=c["rejected"],
                 uncertain=c["uncertain"])
            if p.get("report"):
                gen_at = decided_at + timedelta(minutes=12)
                content = report_writer.template_report(insp)
                rep = Report(inspection_id=insp.id, title=f"تقرير فحص شفرات توربين الرياح {turbine.code}",
                             generator="template", generation_note="Written from the Arabic templates.",
                             created_by_id=reviewer.id, created_at=gen_at, updated_at=gen_at, status="draft")
                rep.data = content
                db.session.add(rep)
                db.session.flush()
                _log(gen_at, "report.generated", reviewer, insp, generator="template")
                if st == "reported":
                    rep.status, rep.issued_by_id = "issued", reviewer.id
                    rep.issued_at = gen_at + timedelta(minutes=25)
                    insp.status = "reported"
                    _log(rep.issued_at, "report.issued", reviewer, insp, entity="report", entity_id=rep.id)
        db.session.flush()

    db.session.merge(AppSetting(key=MAP_KEY, value=json.dumps(demo_map)))

    # ---------------------------------------------------------------- support tickets
    for t in m.get("tickets", []):
        u = users.get(t["user"])
        opened = _ts(now, t["days_ago"], 11, 20)
        tk = SupportTicket(user_id=u.id if u else None, name=u.name if u else t["user"], email=t["user"],
                           topic=t.get("topic"), subject=t["subject"], message=t["message"],
                           status=t.get("status", "open"), created_at=opened, last_user_at=opened)
        db.session.add(tk)
        db.session.flush()
        for r in t.get("replies", []):
            when = _ts(now, r["days_ago"], 14, 0)
            author = users.get(r["author"])
            db.session.add(TicketReply(ticket_id=tk.id, author_id=author.id if author else None,
                                       from_staff=r.get("staff", False), body=r["body"], created_at=when))
            if r.get("staff"):
                tk.last_staff_at = when
            else:
                tk.last_user_at = when
    db.session.commit()


# =====================================================================================================
# Saved VLM results
# =====================================================================================================
def demo_folder(app):
    return Path(app.config.get("DEMO_DATA_DIR") or Path(app.config["INSTANCE_DIR"]).parent / "demo_data")


def read_vlm_results(folder):
    f = Path(folder) / RESULTS_FILE
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _apply_saved_image(insp, fr, made, rec, plan_status, when):
    """Put the saved VLM verdicts back on the findings of one image (same order as manifest.json)."""
    if not rec:
        return
    from .services.knowledge import default_severity
    for i_str, r in (rec.get("boxes") or {}).items():
        i = int(i_str)
        if i >= len(made):
            continue
        f = made[i]
        f.vlm_verdict, f.vlm_class = r.get("verdict"), r.get("class")
        f.vlm_confidence, f.vlm_reason = r.get("confidence"), r.get("reason")
        f.fused_confidence = r.get("fused")
        if plan_status in PENDING_STATUSES and f.status == "pending" and r.get("final_class") \
                and r["final_class"] != f.class_name:
            f.class_name = r["final_class"]
            f.severity = r.get("severity") or default_severity(f.class_name, (f.x2 - f.x1) * (f.y2 - f.y1))
    if plan_status in PENDING_STATUSES:
        for a in rec.get("added") or []:
            x1, y1, x2, y2 = a["box"]
            db.session.add(Finding(
                inspection_id=insp.id, frame_id=fr.id, class_name=a["class"], ai_class_name=a["class"],
                confidence=None, x1=x1, y1=y1, x2=x2, y2=y2, source="vlm",
                severity=a.get("severity") or default_severity(a["class"], (x2 - x1) * (y2 - y1)), status="pending",
                vlm_verdict="added", vlm_class=a["class"], vlm_confidence=a.get("confidence"),
                vlm_reason=a.get("reason"), fused_confidence=a.get("fused"), frame_ids=json.dumps([fr.id]),
                created_at=when))


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def get_state():
    s = db.session.get(AppSetting, STATE_KEY)
    try:
        return json.loads(s.value) if s and s.value else {}
    except ValueError:
        return {}


def _set_state(**kw):
    kw["at"] = datetime.utcnow().isoformat(timespec="seconds")
    db.session.merge(AppSetting(key=STATE_KEY, value=json.dumps(kw)))
    db.session.commit()


def status(app):
    """What the admin page shows about the sample data."""
    folder = demo_folder(app)
    mp = db.session.get(AppSetting, MAP_KEY)
    ids = [int(k) for k in json.loads(mp.value)] if mp and mp.value else []
    present = Inspection.query.filter(Inspection.id.in_(ids)).all() if ids else []
    saved = read_vlm_results(folder)
    missing = 0
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        demo_map = json.loads(mp.value) if mp and mp.value else {}
        for i in present:
            plan = manifest["inspections"][demo_map[str(i.id)]]
            rec = ((saved or {}).get("inspections") or {}).get(str(demo_map[str(i.id)])) or {}
            for im in plan["images"]:
                if (im["detections"] or plan["status"] in PENDING_STATUSES) and im["file"] not in (rec.get("images") or {}):
                    missing += 1
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return dict(available=(folder / "manifest.json").exists(), inspections=len(present), missing=missing,
                with_vlm=sum(1 for i in present if i.vlm_status in ("done", "partial")),
                images=sum(len(i.frames) for i in present), saved=saved and dict(
                    model=saved.get("model"), saved_at=saved.get("saved_at"),
                    inspections=len(saved.get("inspections") or {})),
                state=get_state())


def start_vlm_all(app, only_missing=True):
    import threading
    _set_state(state="running", msg="Starting")
    t = threading.Thread(target=_run_vlm_all, args=(app, only_missing), daemon=True)
    t.start()
    return t


def _run_vlm_all(app, only_missing=True):
    with app.app_context():
        try:
            _run_vlm_all_inner(app, only_missing)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            _set_state(state="failed", msg=str(e)[:300])


def _run_vlm_all_inner(app, only_missing=True):
    """Run the VLM on every sample inspection, then save the verdicts to demo_data/vlm_results.json.

    only_missing=True (the default button) keeps every verdict already saved in vlm_results.json and only checks the
    images that have none yet, so earlier results (and the demo cases built on them) never change.

    Inspections nobody has decided on yet (draft, in review, rejected) get the normal VLM treatment: it may correct the
    defect type and add defects YOLO missed. Inspections that were already reviewed only get the VLM opinion recorded
    next to each finding; the reviewer's decisions, types and the issued reports are never changed.
    """
    from .services import ai_client, vlm
    from .services.knowledge import default_severity
    from .services.worker import imread

    folder = demo_folder(app)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    mp = db.session.get(AppSetting, MAP_KEY)
    demo_map = {int(k): v for k, v in json.loads(mp.value).items()} if mp and mp.value else {}
    root = Path(app.config["UPLOAD_DIR"])
    class_names = vlm._class_names()
    todo = [(db.session.get(Inspection, i), pidx) for i, pidx in sorted(demo_map.items())]
    todo = [(i, p) for i, p in todo if i is not None]
    total = sum(len(i.frames) for i, _ in todo)
    old = (read_vlm_results(folder) or {}) if only_missing else {}
    old_insp = old.get("inspections") or {}
    out = {"about": "VLM cross-check of the sample inspections, applied automatically when demo_data/ is loaded.",
           "model": old.get("model") or ai_client.settings()["model"], "inspections": {}}
    done_frames, stop_note = 0, None
    for insp, pidx in todo:
        plan = manifest["inspections"][pidx]
        name2img = {im["name"]: im for im in plan["images"]}
        pending = insp.status in PENDING_STATUSES
        kept = (old_insp.get(str(pidx)) or {}).get("images") or {}
        rec_insp = {"status": "done", "frames_checked": 0, "added": 0, "images": {}}
        for fr in insp.frames:
            if stop_note:
                break
            done_frames += 1
            img_rec = name2img.get(fr.media.original_name if fr.media else None)
            if img_rec and img_rec["file"] in kept:    # already saved: keep it exactly as it is
                rec_insp["images"][img_rec["file"]] = kept[img_rec["file"]]
                rec_insp["frames_checked"] += 1
                rec_insp["added"] += len(kept[img_rec["file"]].get("added") or [])
                continue
            _set_state(state="running", msg=f"Checked {done_frames - 1} of {total} images ({insp.code})")
            if pending:                               # start clean: drop earlier VLM-added boxes on this image
                for f in list(insp.findings):
                    if f.source == "vlm" and f.status == "pending" and f.frame_id == fr.id:
                        db.session.delete(f)
                db.session.flush()
            fs = [f for f in insp.findings if f.frame_id == fr.id and f.source == "ai"]
            if not fs and not pending:
                continue
            img = imread(root / fr.image_path)
            if img is None:
                continue
            dets = [{"class_name": f.ai_class_name or f.class_name, "confidence": f.confidence,
                     "box": [f.x1, f.y1, f.x2, f.y2]} for f in fs]
            try:
                res = vlm.check_image(img, dets, class_names)
            except ai_client.AIError as e:
                stop_note = f"Stopped at {insp.code}: {e}"
                break
            rec = {"boxes": {}, "added": []}
            mboxes = [d["box"] for d in (img_rec or {}).get("detections", [])]
            for i, f in enumerate(fs):
                r = res["boxes"].get(i)
                if not r:
                    continue
                if pending and f.status == "pending":
                    vlm.apply_result(f, r)
                else:                                 # reviewed: record the opinion only
                    f.vlm_verdict, f.vlm_class, f.vlm_confidence, f.vlm_reason = \
                        r["verdict"], r["class"], r["confidence"], r["reason"]
                    f.fused_confidence = vlm.fuse(f.confidence, r["verdict"], r["confidence"])
                box = [f.x1, f.y1, f.x2, f.y2]
                best = max(range(len(mboxes)), key=lambda j: _iou(box, mboxes[j]), default=None)
                if best is not None and _iou(box, mboxes[best]) > 0.9:
                    rec["boxes"][str(best)] = dict(verdict=f.vlm_verdict, **{"class": f.vlm_class},
                                                   confidence=f.vlm_confidence, reason=f.vlm_reason,
                                                   fused=f.fused_confidence, final_class=f.class_name,
                                                   severity=f.severity)
            if pending and app.config.get("VLM_ADD_MISSED", True):
                existing = [[f.x1, f.y1, f.x2, f.y2] for f in insp.findings if f.frame_id == fr.id]
                for mm in res["missed"]:
                    if any(_iou(mm["box"], e) > 0.3 for e in existing):
                        continue
                    if mm["confidence"] < float(app.config.get("VLM_MISSED_MIN_CONF", 0.6)):
                        continue
                    x1, y1, x2, y2 = mm["box"]
                    sev = default_severity(mm["class"], (x2 - x1) * (y2 - y1))
                    fused = vlm.fuse(None, "added", mm["confidence"])
                    db.session.add(Finding(
                        inspection_id=insp.id, frame_id=fr.id, class_name=mm["class"], ai_class_name=mm["class"],
                        confidence=None, x1=x1, y1=y1, x2=x2, y2=y2, source="vlm", severity=sev, status="pending",
                        vlm_verdict="added", vlm_class=mm["class"], vlm_confidence=mm["confidence"],
                        vlm_reason=mm["reason"], fused_confidence=fused, frame_ids=json.dumps([fr.id])))
                    existing.append(mm["box"])
                    rec["added"].append(dict(box=[round(v, 5) for v in mm["box"]], confidence=mm["confidence"],
                                             reason=mm["reason"], fused=fused, severity=sev, **{"class": mm["class"]}))
                    rec_insp["added"] += 1
            rec_insp["frames_checked"] += 1
            if img_rec:
                rec_insp["images"][img_rec["file"]] = rec
            db.session.commit()
        if stop_note:
            rec_insp["status"], rec_insp["note"] = ("partial" if rec_insp["frames_checked"] else "failed"), stop_note
            for f_name, r in kept.items():            # never lose saved verdicts when a run stops early
                rec_insp["images"].setdefault(f_name, r)
        insp.vlm_enabled = True
        insp.vlm_status, insp.vlm_note = rec_insp["status"], rec_insp.get("note")
        insp.vlm_model, insp.vlm_frames_checked, insp.vlm_added = out["model"], rec_insp["frames_checked"], rec_insp["added"]
        db.session.commit()
        if rec_insp["frames_checked"]:
            out["inspections"][str(pidx)] = rec_insp
        if stop_note:
            break
    for k, v in old_insp.items():                     # inspections not reached in this run keep their saved results
        out["inspections"].setdefault(k, v)
    out["saved_at"] = datetime.utcnow().isoformat(timespec="seconds")
    if out["inspections"]:
        (folder / RESULTS_FILE).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if stop_note:
        _set_state(state="failed" if not out["inspections"] else "partial", msg=stop_note)
    else:
        _set_state(state="done", msg=f"Checked {done_frames} images in {len(out['inspections'])} inspections; "
                                     f"saved to demo_data/{RESULTS_FILE}")
