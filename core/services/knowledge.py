"""Defect reference corpus.

This is the *approved reference* text used to write the Arabic report (by the LLM or
the offline template), together with approved findings. The team should review and replace these entries with
text taken from their approved sources (manufacturer manuals, IEC 61400 / DNV
guidance, the dataset papers) before the final evaluation.
"""

# Categorical colours, fixed order (validated for colour-vision deficiency on light surfaces).
PALETTE = ["#eb6834", "#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

DEFECTS = {
    "crack": {
        "en": "Crack",
        "ar": "تشقق",
        "color": PALETTE[0],
        "base_severity": "high",
        "summary_en": "A visible linear fracture in the blade laminate or coating.",
        "ref_ar": (
            "التشقق هو كسر خطي مرئي في طبقة الطلاء أو في الطبقات المركبة للشفرة. "
            "قد ينتج عن الإجهاد المتكرر أو الصدمات أو عيوب التصنيع."
        ),
        "risk_ar": (
            "قد يمتد التشقق مع الأحمال الدورية لدوران الشفرة، ويسمح بدخول الرطوبة إلى الطبقات الداخلية، "
            "مما قد يؤدي إلى انفصال الطبقات وضعف هيكلي في الشفرة، وقد يتطلب إصلاحًا أكبر أو استبدال الشفرة "
            "وتوقف التوربين إذا تُرك دون معالجة."
        ),
        "inspect_ar": "فحص عن قرب بالحبال أو بالطائرة المسيّرة، وفحص بالموجات فوق الصوتية للتحقق من عمق التشقق وطوله.",
        "maintain_ar": "إصلاح التشقق وفق إجراءات الشركة المصنعة (صنفرة وحشو وترميم بالألياف ثم إعادة الطلاء)، ومتابعة المنطقة في الفحوصات القادمة.",
    },
    "hide_craze": {
        "en": "Hidden crazing",
        "ar": "تشققات شعرية مخفية",
        "color": PALETTE[1],
        "base_severity": "medium",
        "summary_en": "A network of fine hairline cracks, partly under the surface coating.",
        "ref_ar": (
            "التشققات الشعرية المخفية هي شبكة من الشقوق الدقيقة جدًا تظهر جزئيًا تحت طبقة الطلاء "
            "السطحية، وغالبًا ما ترتبط بتقادم الطلاء أو التغيرات الحرارية أو الإجهاد السطحي."
        ),
        "risk_ar": (
            "قد تتسع الشقوق الدقيقة وتتصل ببعضها مع الوقت، فتضعف طبقة الحماية وتسمح بتسرب الرطوبة والأشعة "
            "فوق البنفسجية إلى المادة المركبة، وقد تتحول إلى تشققات أكبر أو تقشر في الطلاء."
        ),
        "inspect_ar": "توثيق المنطقة ومقارنتها بالفحوصات السابقة، وفحص سلامة طبقة الطلاء عن قرب لتحديد عمق التشققات.",
        "maintain_ar": "معالجة سطحية وإعادة طلاء المنطقة المصابة عند الصيانة المجدولة، أو قبلها إذا اتسعت المنطقة.",
    },
    "surface_eye": {
        "en": "Surface eye",
        "ar": "عيب سطحي نقطي (ثقب أو تنقر)",
        "color": PALETTE[2],
        "base_severity": "low",
        "summary_en": "Small point defects such as pinholes, pits or voids on the blade surface.",
        "ref_ar": (
            "العيب السطحي النقطي هو ثقوب أو تنقرات صغيرة على سطح الشفرة، قد تنتج عن فقاعات هوائية "
            "أثناء التصنيع أو عن التآكل الموضعي."
        ),
        "risk_ar": (
            "تشكل الثقوب نقاط بداية للتآكل ودخول الرطوبة، وقد تتسع مع المطر والغبار والرمال فتتحول إلى "
            "تآكل سطحي يؤثر على الكفاءة الهوائية للشفرة."
        ),
        "inspect_ar": "رصد عدد العيوب وكثافتها ومقارنتها بالفحوصات السابقة لمعرفة سرعة انتشارها.",
        "maintain_ar": "حشو الثقوب وطلاؤها موضعيًا عند الصيانة المجدولة.",
    },
    # Classes from WTBs2025 — used automatically if you swap in a model trained on it.
    "erosion": {"en": "Erosion", "ar": "تآكل الحافة", "color": PALETTE[3], "base_severity": "medium",
                "summary_en": "Material loss, usually on the leading edge.",
                "ref_ar": "التآكل هو فقدان تدريجي للمادة، غالبًا على الحافة الأمامية للشفرة بسبب المطر والغبار والرمال.",
                "risk_ar": "يقلل التآكل من الكفاءة الهوائية وإنتاج الطاقة، وقد يصل إلى الطبقات الهيكلية إذا استمر.",
                "inspect_ar": "قياس امتداد التآكل وعمقه على الحافة الأمامية.",
                "maintain_ar": "ترميم الحافة الأمامية وتركيب طبقة أو شريط حماية."},
    "lightning_strike": {"en": "Lightning strike", "ar": "أثر صاعقة", "color": PALETTE[7], "base_severity": "high",
                         "summary_en": "Burn marks or damage from a lightning strike.",
                         "ref_ar": "أثر الصاعقة هو حروق أو تلف ناتج عن ضربة برق.",
                         "risk_ar": "قد يصاحبه تلف داخلي غير مرئي أو انفصال في الطبقات يهدد سلامة الشفرة.",
                         "inspect_ar": "فحص نظام الحماية من الصواعق وإجراء فحص هيكلي متخصص في أقرب وقت.",
                         "maintain_ar": "إصلاح الأضرار وإعادة اختبار نظام التأريض قبل إعادة التشغيل الكامل."},
    "oil_leakage": {"en": "Oil leakage", "ar": "تسرب زيت", "color": PALETTE[5], "base_severity": "medium",
                    "summary_en": "Oil traces on the blade surface.",
                    "ref_ar": "تسرب الزيت هو آثار زيت على سطح الشفرة غالبًا مصدرها نظام الخطوة أو المحور.",
                    "risk_ar": "يدل على خلل محتمل في نظام الخطوة، ويجذب الأتربة فيسرع تدهور السطح.",
                    "inspect_ar": "تحديد مصدر التسرب في نظام الخطوة أو المحور.",
                    "maintain_ar": "إصلاح مصدر التسرب وتنظيف سطح الشفرة."},
}

GENERIC = {
    "ar": None,
    "base_severity": "medium",
    "summary_en": "Visible surface defect detected by the model.",
    "ref_ar": "عيب سطحي مرئي تم رصده بواسطة نموذج الرؤية الحاسوبية.",
    "risk_ar": "قد يتطور العيب إذا تُرك دون متابعة.",
    "inspect_ar": "مراجعة العيب عن قرب من قبل مفتش مؤهل.",
    "maintain_ar": "تحديد إجراء الصيانة المناسب بعد الفحص عن قرب.",
}

RISK_AR = {"low": "منخفض", "medium": "متوسط", "high": "مرتفع"}

SEVERITY_AR = {"low": "منخفضة", "medium": "متوسطة", "high": "عالية"}
SEVERITY_EN = {"low": "Low", "medium": "Medium", "high": "High"}

GENERAL_REFERENCES_AR = [
    "نظام عين أداة مساعدة لاتخاذ القرار ولا يحل محل المفتش المؤهل، ولا يقدم شهادة بالسلامة الإنشائية للتوربين.",
    "يكتشف النظام العيوب السطحية المرئية في الصور الملونة فقط، ولا يكتشف العيوب الداخلية أو المخفية.",
    "جميع النتائج الواردة في التقرير تمت مراجعتها واعتمادها من قبل مراجع بشري قبل إصدار التقرير.",
]


def info(class_name, index=None):
    d = DEFECTS.get(class_name)
    if d:
        return d
    color = PALETTE[(index or 0) % len(PALETTE)]
    pretty = class_name.replace("_", " ").capitalize()
    return {**GENERIC, "en": pretty, "ar": pretty, "color": color}


def class_catalog(names):
    """names: list of class names in model order -> list of dicts for the UI."""
    out = []
    for i, n in enumerate(names):
        d = info(n, i)
        out.append({"name": n, "en": d["en"], "ar": d["ar"], "color": d["color"]})
    return out


def default_severity(class_name, area):
    """Starting severity suggestion; the reviewer always has the final say."""
    base = info(class_name).get("base_severity", "medium")
    order = ["low", "medium", "high"]
    i = order.index(base)
    if area > 0.08 and i < 2:
        i += 1
    return order[i]
