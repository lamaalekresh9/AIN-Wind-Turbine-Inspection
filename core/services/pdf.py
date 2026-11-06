"""Arabic (RTL) PDF export with ReportLab.

ReportLab doesn't shape Arabic, so each line is wrapped in logical order first,
then reshaped (arabic_reshaper) and reordered (python-bidi) before drawing.
"""
from datetime import datetime
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Flowable, Image, KeepTogether, PageBreak, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from ..models import fmt_ts
from .evidence import annotate, crop, grid_location
from .knowledge import RISK_AR, SEVERITY_AR, info
from .report_writer import FIELD_LABELS_AR, FIELDS, finding_text, overall_risk

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_registered = False

INK = colors.HexColor("#14273a")
MUTED = colors.HexColor("#5b6b7a")
LINE = colors.HexColor("#d5dde3")
BAND = colors.HexColor("#eef2f4")
ACCENT = colors.HexColor("#123b4a")


def _register():
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("Naskh", str(FONT_DIR / "NotoNaskhArabic-400.ttf")))
    pdfmetrics.registerFont(TTFont("Naskh-Bold", str(FONT_DIR / "NotoNaskhArabic-700.ttf")))
    _registered = True


def shape(text):
    return get_display(arabic_reshaper.reshape(text))


class RTL(Flowable):
    """Right-aligned, wrapped Arabic paragraph."""

    def __init__(self, text, size=11, bold=False, color=INK, leading=None, align="right", space_after=0):
        super().__init__()
        self.text = str(text or "")
        self.size = size
        self.font = "Naskh-Bold" if bold else "Naskh"
        self.color = color
        self.leading = leading or size * 1.75
        self.align = align
        self.space_after = space_after
        self.lines = []

    def _wrap_lines(self, width):
        lines = []
        for para in self.text.split("\n"):
            words, cur = para.split(), ""
            if not words:
                lines.append("")
                continue
            for w in words:
                trial = f"{cur} {w}".strip()
                if pdfmetrics.stringWidth(shape(trial), self.font, self.size) <= width or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
        return lines

    def wrap(self, aw, ah):
        self.width = aw
        self.lines = self._wrap_lines(aw)
        self.height = len(self.lines) * self.leading + self.space_after
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setFont(self.font, self.size)
        c.setFillColor(self.color)
        y = self.height - self.space_after - self.size * 1.15
        for ln in self.lines:
            s = shape(ln)
            if self.align == "center":
                c.drawCentredString(self.width / 2, y, s)
            elif self.align == "left":
                c.drawString(0, y, s)
            else:
                c.drawRightString(self.width, y, s)
            y -= self.leading


def _section(title):
    t = Table([[RTL(title, 13, bold=True, color=ACCENT)]], colWidths=[None])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, ACCENT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [Spacer(1, 6 * mm), t, Spacer(1, 3 * mm)]


def _kv_table(rows, width):
    """rows: list of (label, value) — rendered RTL as value | label with label on the right."""
    data = [[RTL(v, 10), RTL(k, 10, bold=True, color=MUTED)] for k, v in rows]
    t = Table(data, colWidths=[width * 0.68, width * 0.32])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (1, 0), (1, -1), BAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


def _grid_table(header, rows, widths):
    """Columns are given in reading order (right to left) and flipped for drawing."""
    data = [[RTL(h, 10, bold=True, align="center") for h in reversed(header)]]
    for r in rows:
        data.append([RTL(c, 10, align="center") for c in reversed(r)])
    t = Table(data, colWidths=list(reversed(widths)))
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def build_pdf(insp, report, upload_root, out_path):
    _register()
    upload_root = Path(upload_root)
    ev_dir = upload_root / f"inspection_{insp.id}" / "evidence"
    data = report.data
    approved = insp.approved_findings
    counts = insp.counts()
    draft = report.status != "issued"

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
                            topMargin=22 * mm, bottomMargin=18 * mm,
                            title=f"Ain inspection report {insp.code}", author="Ain")
    W = A4[0] - 32 * mm
    story = []

    story.append(RTL(report.title or "تقرير فحص شفرات توربين الرياح", 18, bold=True, color=ACCENT))
    story.append(RTL(f"رقم الفحص: {insp.code}    حالة التقرير: {'مسودة' if draft else 'صادر ومعتمد'}", 10,
                     color=MUTED, space_after=4))

    reviewer = insp.review_completed_by.name if insp.review_completed_by else "-"
    meta = [
        ("التوربين", f"{insp.turbine.code} ({insp.turbine.name or ''})".replace(" ()", "")),
        ("الموقع", f"{insp.turbine.site}{' - ' + insp.turbine.region if insp.turbine.region else ''}"),
        ("الشفرة", insp.blade.label.replace("Blade", "الشفرة") if insp.blade else "غير محددة"),
        ("تاريخ الفحص", insp.inspection_date.isoformat() if insp.inspection_date else "-"),
        ("الطائرة المسيّرة", insp.drone_model or "-"),
        ("الأحوال الجوية", insp.weather or "-"),
        ("أنشأ الفحص", insp.created_by.name if insp.created_by else "-"),
        ("المراجع المعتمِد", reviewer),
        ("تاريخ اعتماد المراجعة", insp.review_completed_at.strftime("%Y-%m-%d") if insp.review_completed_at else "-"),
        ("نموذج الكشف", f"{insp.model_name or '-'}  (حد الثقة {insp.conf_threshold:.2f})"
         + (f" + {insp.vlm_model}" if insp.vlm_model and insp.vlm_status in ("done", "partial") else "")),
        ("مستوى الخطورة العام", RISK_AR[data.get("overall_risk") or overall_risk(approved)]),
    ]
    story.append(_kv_table(meta, W))

    story += _section("الملخص التنفيذي")
    story.append(RTL(data.get("executive_summary", ""), 11))

    story += _section("ملخص الرصد والمراجعة")
    ai_total = sum(1 for f in insp.findings if f.source == "ai")
    manual = sum(1 for f in insp.findings if f.source == "manual")
    vlm_added = sum(1 for f in insp.findings if f.source == "vlm")
    story.append(_grid_table(
        ["رصد YOLO", "أضافها VLM", "مقبولة", "مرفوضة", "غير مؤكدة", "مضافة يدويًا"],
        [[str(ai_total), str(vlm_added), str(counts["accepted"]), str(counts["rejected"]), str(counts["uncertain"]),
          str(manual)]],
        [W / 6] * 6,
    ))
    if approved:
        story.append(Spacer(1, 3 * mm))
        by = {}
        for f in approved:
            k = info(f.class_name)["ar"]
            by.setdefault(k, {"low": 0, "medium": 0, "high": 0})
            by[k][f.severity] = by[k].get(f.severity, 0) + 1
        rows = [[k, str(sum(v.values())), str(v["high"]), str(v["medium"]), str(v["low"])] for k, v in by.items()]
        story.append(_grid_table(["نوع العيب", "العدد", "عالية", "متوسطة", "منخفضة"], rows,
                                 [W * 0.36, W * 0.16, W * 0.16, W * 0.16, W * 0.16]))

    story.append(CondPageBreak(70 * mm))
    story += _section("العيوب المعتمدة")
    if not approved:
        story.append(RTL("لم يتم اعتماد أي عيوب في هذا الفحص.", 11))
    texts = {x["id"]: finding_text(x) for x in data.get("findings", [])}
    for f in approved:
        d = info(f.class_name)
        src = upload_root / f.frame.image_path
        cp = ev_dir / f"crop_{f.id}.jpg"
        try:
            crop(src, f, cp)
            img = Image(str(cp))
            r = min(55 * mm / img.imageWidth, 55 * mm / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * r, img.imageHeight * r
        except Exception:
            img = Spacer(1, 1)
        t = texts.get(f.code) or finding_text(None)
        conf = f"{f.confidence:.0%}" if f.confidence is not None else ("VLM" if f.source == "vlm" else "يدوي")
        _, loc = grid_location(f)
        ev = f.frame.label
        if f.frame.media.kind == "video":
            ev += f"  |  ظهر في {f.occurrences} إطارات ({fmt_ts(f.first_ts)} - {fmt_ts(f.last_ts)})"
        head = [
            RTL(f"{f.code}   {d['ar']}", 12.5, bold=True),
            RTL(f"الخطورة: {SEVERITY_AR.get(f.severity)}    الثقة: {conf}    الموقع في الصورة: {loc}", 9.5, color=MUTED),
            RTL(f"الدليل: {ev}", 9, color=MUTED),
        ]
        if f.vlm_verdict in ("confirmed", "relabeled", "added") and f.fused_confidence is not None:
            head.append(RTL(f"نموذج VLM: {dict(confirmed='أكد العيب', relabeled='أكد العيب وعدّل نوعه', added='رصد العيب')[f.vlm_verdict]}"
                            f" · الدرجة المدمجة {f.fused_confidence:.0%}", 9, color=MUTED))
        inner = Table([[r] for r in head], colWidths=[W - 60 * mm - 18])
        inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        row = Table([[img, inner]], colWidths=[60 * mm, W - 60 * mm])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEAFTER", (1, 0), (1, 0), 3, colors.HexColor(d["color"])),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (1, 0), (1, 0), 10), ("LEFTPADDING", (1, 0), (1, 0), 8),
        ]))
        fields = []
        for k in FIELDS:
            if t.get(k):
                fields.append(RTL(FIELD_LABELS_AR[k], 10.5, bold=True, color=INK))
                fields.append(RTL(t[k], 10.5, color=ACCENT if k in ("inspection", "maintenance") else INK,
                                  space_after=2))
        story.append(KeepTogether([row] + fields[:2]))
        story.extend(fields[2:])
        story.append(Spacer(1, 5 * mm))

    story += _section("التوصيات")
    for r in data.get("recommendations", []):
        story.append(RTL(f"• {r}", 11))

    lims = list(data.get("limitations", []))
    if counts["uncertain"]:
        lims.append(f"توجد {counts['uncertain']} نتائج صنّفها المراجع كغير مؤكدة، ولم تُدرج في هذا التقرير وتتطلب إعادة فحص.")
    story += _section("حدود التقرير")
    for r in lims:
        story.append(RTL(f"• {r}", 10.5, color=MUTED))

    frames = []
    for f in approved:
        if f.frame not in frames:
            frames.append(f.frame)
    if frames:
        story.append(PageBreak())
        story.append(RTL("ملحق: الصور المشروحة", 13, bold=True, color=ACCENT, space_after=4))
        for fr in frames:
            fs = [f for f in approved if f.frame_id == fr.id]
            ap = ev_dir / f"annot_{fr.id}.jpg"
            try:
                annotate(upload_root / fr.image_path, fs, ap)
                img = Image(str(ap))
                r = min(W / img.imageWidth, 110 * mm / img.imageHeight)
                img.drawWidth, img.drawHeight = img.imageWidth * r, img.imageHeight * r
                story.append(KeepTogether([img, RTL(f"{fr.label}  —  " + "، ".join(f.code for f in fs), 9,
                                                    color=MUTED, align="center", space_after=8)]))
            except Exception:
                continue

    story += _section("الاعتماد")
    if draft:
        story.append(RTL("هذه مسودة لم تصدر بعد ولا يعتد بها.", 11, bold=True, color=colors.HexColor("#b4361f")))
    else:
        story.append(RTL(f"صدر هذا التقرير واعتمده: {report.issued_by.name if report.issued_by else '-'} "
                         f"بتاريخ {report.issued_at.strftime('%Y-%m-%d %H:%M') if report.issued_at else '-'}", 11))
    story.append(RTL("أُعدّ هذا التقرير بمساعدة منصة عين للذكاء الاصطناعي، وجميع النتائج الواردة فيه اعتمدها مراجع بشري.",
                     9, color=MUTED))

    gen = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    def on_page(c, d):
        c.saveState()
        c.setFillColor(ACCENT)
        c.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Naskh-Bold", 12)
        c.drawRightString(A4[0] - 16 * mm, A4[1] - 8 * mm, shape("عين | منصة فحص شفرات توربينات الرياح"))
        c.setFont("Helvetica", 8)
        c.drawString(16 * mm, A4[1] - 7.8 * mm, f"{insp.code}")
        c.setFillColor(MUTED)
        c.drawString(16 * mm, 9 * mm, f"Generated {gen}")
        c.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {d.page}")
        if draft:
            c.setFillColor(colors.Color(0.85, 0.2, 0.1, alpha=0.08))
            c.setFont("Naskh-Bold", 90)
            c.translate(A4[0] / 2, A4[1] / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, shape("مسودة"))
        c.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out_path
