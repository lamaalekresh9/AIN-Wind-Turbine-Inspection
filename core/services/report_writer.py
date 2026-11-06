"""Arabic inspection report: LLM-written (Gemini/OpenAI) with an offline template fallback.

Grounding: only ACCEPTED findings, their evidence crops, the inspection details and the
reference text in knowledge.py reach the model. Rejected, uncertain and pending findings
never do. Every finding id the model writes about is checked against the accepted list.
"""
import json
from pathlib import Path

from flask import current_app

from ..models import fmt_ts
from . import ai_client
from .evidence import grid_location
from .knowledge import GENERAL_REFERENCES_AR, RISK_AR, SEVERITY_AR, info

FIELDS = ("description", "location", "severity_assessment", "consequences", "inspection", "maintenance")
FIELD_LABELS_AR = {
    "description": "وصف الضرر",
    "location": "الموقع",
    "severity_assessment": "تقييم الخطورة",
    "consequences": "العواقب المحتملة إذا لم يُعالج",
    "inspection": "الفحص الموصى به",
    "maintenance": "الصيانة الموصى بها",
}


def overall_risk(findings):
    sev = {f.severity for f in findings}
    return "high" if "high" in sev else "medium" if "medium" in sev else "low"


def _location_ar(insp, f):
    _, loc = grid_location(f)
    blade = insp.blade.label.replace("Blade", "الشفرة") if insp.blade else "الشفرة"
    s = f"{blade}، في {loc} ({f.frame.label})"
    if f.frame.media.kind == "video":
        s += f"، يظهر بين {fmt_ts(f.first_ts)} و{fmt_ts(f.last_ts)} في {f.occurrences} إطارات"
    return s


def _area_ar(f):
    a = f.area
    return "صغيرة" if a < 0.01 else "متوسطة" if a < 0.06 else "كبيرة"


# ---------------------------------------------------------------- template

def template_report(insp):
    approved = insp.approved_findings
    counts = {}
    for f in approved:
        counts[info(f.class_name)["ar"]] = counts.get(info(f.class_name)["ar"], 0) + 1
    high = sum(1 for f in approved if f.severity == "high")
    risk = overall_risk(approved)
    blade = insp.blade.label.replace("Blade", "الشفرة") if insp.blade else "الشفرات"
    if approved:
        parts = "، ".join(f"{v} {k}" for k, v in counts.items())
        summary = (
            f"أُجري فحص بصري بمساعدة الذكاء الاصطناعي على {blade} للتوربين {insp.turbine.code} "
            f"في موقع {insp.turbine.site}. بعد المراجعة البشرية تم اعتماد {len(approved)} عيبًا "
            f"({parts})، منها {high} بدرجة خطورة عالية، ومستوى الخطورة العام {RISK_AR[risk]}."
        )
    else:
        summary = (
            f"أُجري فحص بصري بمساعدة الذكاء الاصطناعي على {blade} للتوربين {insp.turbine.code} "
            f"في موقع {insp.turbine.site}، ولم يتم اعتماد أي عيوب مرئية بعد المراجعة البشرية."
        )
    items = []
    for f in approved:
        d = info(f.class_name)
        conf = f"بدرجة ثقة {f.confidence:.0%}" if f.confidence is not None else (
            "رصده نموذج الرؤية واللغة" if f.source == "vlm" else "أضافه المراجع يدويًا")
        desc = f"{d['ar']} {conf}. {d['ref_ar']}"
        if f.reviewer_note:
            desc += f" ملاحظة المراجع: {f.reviewer_note}"
        sev = (f"الخطورة {SEVERITY_AR.get(f.severity)}، وفقًا لتقييم المراجع، مع مساحة {_area_ar(f)} "
               f"نسبيًا في الصورة.")
        items.append({
            "id": f.code, "description": desc, "location": _location_ar(insp, f), "severity_assessment": sev,
            "consequences": d["risk_ar"], "inspection": d["inspect_ar"], "maintenance": d["maintain_ar"],
        })
    recs = []
    if high:
        recs.append("إعطاء الأولوية للعيوب ذات الخطورة العالية وجدولة فحص عن قرب لها في أقرب وقت.")
    if approved:
        recs.append("مقارنة هذه النتائج بالفحص القادم لنفس الشفرة لرصد أي تطور في العيوب.")
    recs.append("الاحتفاظ بصور الأدلة المرفقة ضمن سجل صيانة التوربين.")
    return {
        "executive_summary": summary,
        "overall_risk": risk,
        "findings": items,
        "recommendations": recs,
        "limitations": list(GENERAL_REFERENCES_AR),
    }


# ---------------------------------------------------------------- LLM

SYSTEM = """أنت مهندس فحص شفرات توربينات رياح خبير، وتكتب تقارير فحص فنية باللغة العربية الفصحى المهنية.
ستستلم بيانات الفحص، وقائمة العيوب التي اعتمدها المراجع البشري، ونصوصًا مرجعية معتمدة عن كل نوع عيب، وصورًا مقربة للأدلة بنفس ترتيب العيوب.
القواعد:
1. اكتب فقط عن العيوب الواردة في findings وبنفس رموزها (مثل F-0003). لا تضف عيوبًا أخرى.
2. استخدم الصور لوصف شكل الضرر وموقعه بدقة، ولا تخترع قياسات بالسنتيمتر أو المتر.
3. التزم بدرجة الخطورة التي حددها المراجع (severity) واشرح سببها.
4. لا تتنبأ بمواعيد دقيقة أو بالعمر المتبقي للشفرة، ولا تقدم شهادة سلامة.
5. لكل عيب اكتب: description (نوع الضرر وشكله)، location (موقعه على الشفرة وفي الصورة)، severity_assessment (تقييم الخطورة المحتملة)، consequences (ما الذي قد يسببه إذا لم يُعالج)، inspection (الفحص الموصى به)، maintenance (الصيانة الموصى بها).
أعد JSON فقط بالشكل:
{"executive_summary": "...", "findings": [{"id": "F-0001", "description": "...", "location": "...", "severity_assessment": "...", "consequences": "...", "inspection": "...", "maintenance": "..."}], "recommendations": ["..."], "limitations": ["..."]}"""


def _crop_jpeg(insp, f):
    from .evidence import crop
    root = Path(current_app.config["UPLOAD_DIR"])
    out = root / f"inspection_{insp.id}" / "evidence" / f"crop_{f.id}.jpg"
    crop(root / f.frame.image_path, f, out)
    return out.read_bytes()


def _facts(insp, f):
    d = info(f.class_name)
    fact = {
        "id": f.code,
        "type_ar": d["ar"],
        "type_en": d["en"],
        "severity": SEVERITY_AR.get(f.severity),
        "location": _location_ar(insp, f),
        "relative_size_in_image": _area_ar(f),
        "detector_confidence": round(f.confidence, 2) if f.confidence is not None else None,
        "source": {"ai": "YOLO", "vlm": "VLM", "manual": "المراجع"}.get(f.source, f.source),
        "reviewer_note": f.reviewer_note or "",
    }
    if f.vlm_reason and f.vlm_verdict in ("confirmed", "relabeled", "added"):
        fact["visual_check"] = f.vlm_reason
    return fact


def generate(insp):
    """Returns (content, generator, note)."""
    fallback = template_report(insp)
    cfg = current_app.config
    if not cfg.get("LLM_REPORT_ENABLED") or not ai_client.available():
        why = "LLM reports are turned off in app.py" if not cfg.get("LLM_REPORT_ENABLED") else "No AI key set in .env"
        return fallback, "template", f"{why}: written from the Arabic templates."
    approved = insp.approved_findings
    if not approved:
        return fallback, "template", "No accepted findings: written from the Arabic templates."
    with_imgs = approved[: int(cfg.get("REPORT_MAX_IMAGES", 8))]
    images = []
    for f in with_imgs:
        try:
            images.append(_crop_jpeg(insp, f))
        except Exception:  # noqa: BLE001
            pass
    refs, seen = [], set()
    for f in approved:
        if f.class_name not in seen:
            seen.add(f.class_name)
            d = info(f.class_name)
            refs.append({"type": d["ar"], "reference": d["ref_ar"], "if_untreated": d["risk_ar"],
                         "inspection": d["inspect_ar"], "maintenance": d["maintain_ar"]})
    payload = {
        "inspection": {
            "code": insp.code, "turbine": insp.turbine.code, "turbine_model": insp.turbine.model or "",
            "site": insp.turbine.site, "blade": insp.blade.label if insp.blade else "غير محدد",
            "date": insp.inspection_date.isoformat() if insp.inspection_date else "",
            "weather": insp.weather or "", "inspector_notes": insp.notes or "",
            "overall_risk": RISK_AR[overall_risk(approved)],
        },
        "findings": [_facts(insp, f) for f in approved],
        "images_order": [f.code for f in with_imgs][: len(images)],
        "references": refs,
        "general_limitations": GENERAL_REFERENCES_AR,
    }
    try:
        data = ai_client.generate_json(SYSTEM, json.dumps(payload, ensure_ascii=False), images,
                                       temperature=0.3, max_tokens=32768)
    except ai_client.AIError as e:
        current_app.logger.warning("LLM report failed: %s", e)
        why = str(e)
        return fallback, "template", f"The language model couldn't write the report ({why}); Arabic templates used instead."

    by_id = {x.get("id"): x for x in data.get("findings", []) if isinstance(x, dict)}
    items = []
    for tf in fallback["findings"]:
        g = by_id.get(tf["id"]) or {}
        items.append({k: (str(g.get(k) or "").strip() or tf[k]) if k != "id" else tf["id"] for k in ("id",) + FIELDS})
    content = {
        "executive_summary": (data.get("executive_summary") or fallback["executive_summary"]).strip(),
        "overall_risk": fallback["overall_risk"],
        "findings": items,
        "recommendations": [str(x).strip() for x in data.get("recommendations", []) if str(x).strip()]
        or fallback["recommendations"],
        "limitations": [str(x).strip() for x in data.get("limitations", []) if str(x).strip()]
        or fallback["limitations"],
    }
    return content, "llm", f"Written by {ai_client.settings()['model']} from accepted findings and their evidence images."


def finding_text(item):
    """Back-compat for reports created before the 6-field layout."""
    if not item:
        return {k: "" for k in FIELDS}
    if "location" not in item and "recommended_action" in item:
        return {"description": item.get("description", ""), "location": "", "severity_assessment": "",
                "consequences": "", "inspection": item.get("recommended_action", ""), "maintenance": ""}
    return {k: item.get(k, "") for k in FIELDS}
