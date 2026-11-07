"""Defect reference corpus.

This is the *approved reference* text used to write the Arabic report (by the LLM or
the offline template), together with approved findings. The team should review and replace these entries with
text taken from their approved sources (manufacturer manuals, IEC 61400 / DNV
guidance, the dataset papers) before the final evaluation.
"""

from .model_card import limitations_ar as _model_limitation

# Categorical colours, fixed order (validated for colour-vision deficiency on light surfaces).
PALETTE = ["#eb6834", "#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

DEFECTS = {
    # ---- Classes of the current model (WTBD + GFD-YOLOX WTBlade, YOLO26m) ----
    "corrosion": {
        "en": "Corrosion / erosion",
        "ar": "تآكل",
        "color": "#eda100",
        "base_severity": "medium",
        "summary_en": "Material loss or roughened, pitted coating, most often along the leading edge.",
        "ref_ar": (
            "التآكل هو فقدان تدريجي لطبقة الطلاء أو المادة السطحية للشفرة، ويظهر على شكل سطح خشن أو متنقّر "
            "أو متقشر، وغالبًا ما يتركز على الحافة الأمامية بسبب اصطدام حبيبات الرمل والغبار وقطرات المطر بسرعة عالية."
        ),
        "risk_ar": (
            "يقلل التآكل من الكفاءة الهوائية للشفرة وبالتالي من إنتاج الطاقة، وإذا استمر فقد يصل إلى الطبقات "
            "المركبة الهيكلية ويسمح بدخول الرطوبة، مما يرفع تكلفة الإصلاح لاحقًا."
        ),
        "inspect_ar": "قياس امتداد التآكل وعمقه على الحافة الأمامية، والتحقق من وصوله إلى الألياف المركبة.",
        "maintain_ar": "ترميم المنطقة المتآكلة وإعادة طلائها، وتركيب شريط أو طبقة حماية للحافة الأمامية عند الحاجة.",
    },
    "crack": {
        "en": "Crack",
        "ar": "تشقق",
        "color": "#eb6834",
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
    "craze": {
        "en": "Crazing",
        "ar": "تشققات شعرية سطحية",
        "color": "#6250d6",
        "base_severity": "medium",
        "summary_en": "A visible network of fine hairline cracks in the surface coating.",
        "ref_ar": (
            "التشققات الشعرية السطحية هي شبكة ظاهرة من الشقوق الدقيقة في طبقة الطلاء الخارجية، تشبه تشقق "
            "طلاء الخزف، وترتبط عادة بتقادم الطلاء والتغيرات الحرارية والأشعة فوق البنفسجية."
        ),
        "risk_ar": (
            "تضعف التشققات الشعرية طبقة الحماية وتسمح بتسرب الرطوبة إلى ما تحت الطلاء، وقد تتسع مع الوقت "
            "فتتحول إلى تقشر في الطلاء أو تشققات أكبر."
        ),
        "inspect_ar": "توثيق مساحة المنطقة ومقارنتها بالفحوصات السابقة، والتحقق من عدم امتداد الشقوق إلى الطبقات المركبة.",
        "maintain_ar": "معالجة سطحية وإعادة طلاء المنطقة المصابة عند الصيانة المجدولة، أو قبلها إذا اتسعت المنطقة.",
    },
    "dirt": {
        "en": "Dirt / contamination",
        "ar": "اتساخ وتلوث سطحي",
        "color": "#008300",
        "base_severity": "low",
        "summary_en": "Dirt, oil or other contamination deposited on the blade surface.",
        "ref_ar": (
            "الاتساخ هو تراكم الأتربة أو الزيوت أو بقايا الحشرات أو مواد أخرى على سطح الشفرة دون فقدان "
            "في المادة نفسها. لا يُعد ضررًا إنشائيًا، لكنه يؤثر على أداء الشفرة وقد يخفي عيوبًا تحته."
        ),
        "risk_ar": (
            "يزيد الاتساخ من خشونة السطح فيقلل الكفاءة الهوائية وإنتاج الطاقة، وقد يخفي عيوبًا تحته، "
            "وإذا كان مصدره تسرب زيت فقد يدل على خلل في نظام الخطوة أو المحور."
        ),
        "inspect_ar": "التحقق من مصدر التلوث (غبار أو زيت أو غيره)، وإعادة فحص المنطقة بعد التنظيف للتأكد من عدم وجود عيب تحتها.",
        "maintain_ar": "تنظيف سطح الشفرة، وإصلاح مصدر التسرب إن وُجد.",
    },
    "hide_craze": {
        "en": "Hidden crazing",
        "ar": "تشققات شعرية مخفية",
        "color": "#2a78d6",
        "base_severity": "medium",
        "summary_en": "Fine hairline cracks partly under the surface coating, often only visible at a low light angle.",
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
        "en": "Surface eye (pits)",
        "ar": "عيب سطحي نقطي (ثقب أو تنقر)",
        "color": "#1baf7a",
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
    "surface_injure": {
        "en": "Surface damage",
        "ar": "تلف سطحي",
        "color": "#e87ba4",
        "base_severity": "medium",
        "summary_en": "Mechanical damage to the surface: chips, gouges, scratches or peeled coating.",
        "ref_ar": (
            "التلف السطحي هو ضرر ميكانيكي في سطح الشفرة مثل الخدوش العميقة أو الكشط أو تقشر الطلاء أو "
            "فقدان أجزاء صغيرة منه، وقد ينتج عن اصطدام أجسام أو عن أعمال النقل والتركيب والصيانة."
        ),
        "risk_ar": (
            "يكشف التلف السطحي الطبقات الداخلية للرطوبة والأشعة فوق البنفسجية، وقد يصبح نقطة بداية "
            "للتشقق أو التآكل إذا تُرك دون معالجة."
        ),
        "inspect_ar": "تحديد عمق التلف ومساحته، والتحقق من سلامة الألياف المركبة تحت المنطقة المصابة.",
        "maintain_ar": "صنفرة المنطقة وحشوها وإعادة طلائها وفق إجراءات الشركة المصنعة.",
    },
    "thunderstrike": {
        "en": "Lightning damage",
        "ar": "أثر صاعقة",
        "color": "#e34948",
        "base_severity": "high",
        "summary_en": "Burn marks, scorching or damaged material caused by a lightning strike.",
        "ref_ar": (
            "أثر الصاعقة هو حروق أو اسوداد أو تلف في المادة ناتج عن ضربة برق، ويظهر غالبًا قرب طرف الشفرة "
            "أو حول مستقبلات الصواعق."
        ),
        "risk_ar": (
            "قد يصاحب أثر الصاعقة تلف داخلي غير مرئي أو انفصال في الطبقات أو ضرر في نظام الحماية من الصواعق، "
            "مما قد يهدد سلامة الشفرة إذا استمر التشغيل دون فحص."
        ),
        "inspect_ar": "فحص هيكلي متخصص في أقرب وقت، واختبار نظام الحماية من الصواعق والتأريض.",
        "maintain_ar": "إصلاح الأضرار وإعادة اختبار نظام التأريض قبل إعادة التشغيل الكامل.",
    },
    # ---- Classes from WTBs2025, used automatically if a model trained on it is swapped in ----
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
    _model_limitation(),
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
