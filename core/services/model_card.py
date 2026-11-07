"""What the detection model is and how well it measured, in one place.

The home page, the FAQ, the admin "Model & system" page and the limitations section of every Arabic report read
from here. If you swap models/best.pt, update these numbers from that model's own test results.

Source of the numbers: Senior Project/runs/ain10_merged_test30/yolo26m_merged_cls8_neardup_test30_cv5/ on the team
Drive (results_test_final.csv, per_class_final.csv, summary.json; split fingerprint 14f5b1163bc61e7e).
Protocol: 30% of the data (760 images, both datasets) was held out as the test set and never used for training,
model selection or choosing the number of epochs. 5-fold cross-validation ran on the other 70%, and the final model
was trained once on the whole 70%. Near-duplicate photos were kept on the same side of every split.
"""

MODEL_CARD = {
    "name": "YOLO26m, WTBD + GFD-YOLOX WTBlade (Ain 10)",
    "architecture": "YOLO26m (Ultralytics 8.4.157), COCO-pretrained",
    "trained": "7 Nov 2026",
    "image_size": 1024,
    "training": "70% train / 30% held-out test, 5-fold cross-validation on the 70%, "
                "final model trained on the whole 70% for 98 epochs, seed 0",
    "datasets": "WTBD (1,065 images, 6 classes) merged with GFD-YOLOX WTBlade (1,411 images, 5 classes), 2,476 images; "
                "corrosion, hide_craze and thunderstrike merged across the two, dirt and surface_eye kept from GFD",
    "split": {"total": 2476, "train": 1716, "test": 760, "test_wtbd": 316, "test_gfd": 444, "test_boxes": 1343,
              "folds": 5, "fingerprint": "14f5b1163bc61e7e"},
    # Headline = the whole 30% test set (both datasets together)
    "headline": {"set": "Test, both datasets", "images": 760, "precision": 0.612, "recall": 0.681,
                 "map50": 0.667, "map50_95": 0.369},
    "test_sets": [
        {"set": "Test, both datasets", "images": 760, "precision": 0.612, "recall": 0.681, "map50": 0.667,
         "map50_95": 0.369, "p_app": 0.664, "r_app": 0.614},
        {"set": "Test, WTBD only", "images": 316, "precision": 0.833, "recall": 0.724, "map50": 0.775,
         "map50_95": 0.421, "p_app": 0.733, "r_app": 0.728},
        {"set": "Test, GFD only", "images": 444, "precision": 0.528, "recall": 0.615, "map50": 0.555,
         "map50_95": 0.301, "p_app": 0.640, "r_app": 0.482},
    ],
    # 5-fold cross-validation on the 70%: each fold model scored on its own validation fold (mean and SD)
    "cv": [
        {"set": "Both datasets", "images": "~159 / fold", "precision": (0.620, 0.053), "recall": (0.634, 0.041),
         "map50": (0.661, 0.030), "map50_95": (0.325, 0.005)},
        {"set": "WTBD", "images": "~91 / fold", "precision": (0.796, 0.071), "recall": (0.719, 0.049),
         "map50": (0.777, 0.055), "map50_95": (0.415, 0.027)},
        {"set": "GFD", "images": "~68 / fold", "precision": (0.451, 0.096), "recall": (0.541, 0.052),
         "map50": (0.491, 0.045), "map50_95": (0.191, 0.015)},
    ],
    # Test AP@0.5 per class (None = class not in that dataset)
    "per_class_ap50": {
        "corrosion": {"all": 0.349, "WTBD": 0.448, "GFD": 0.323},
        "crack": {"all": 0.853, "WTBD": 0.856, "GFD": None},
        "craze": {"all": 0.840, "WTBD": 0.913, "GFD": None},
        "dirt": {"all": 0.898, "WTBD": None, "GFD": 0.902},
        "hide_craze": {"all": 0.630, "WTBD": 0.788, "GFD": 0.576},
        "surface_eye": {"all": 0.231, "WTBD": None, "GFD": 0.233},
        "surface_injure": {"all": 0.776, "WTBD": 0.838, "GFD": None},
        "thunderstrike": {"all": 0.762, "WTBD": 0.806, "GFD": 0.740},
    },
}


def pct(v):
    return f"{round(v * 100)}%"


def limitations_ar():
    """One sentence for the limitations section of the Arabic report."""
    h = MODEL_CARD["headline"]
    return (f"حقق نموذج الكشف الحالي على {h['images']} صورة اختبار مستقلة من مجموعتي البيانات WTBD وGFD "
            f"لم تُستخدم في التدريب متوسط دقة (mAP@0.5) بنسبة {pct(h['map50'])}، ودقة (Precision) بنسبة "
            f"{pct(h['precision'])}، واسترجاعًا (Recall) بنسبة {pct(h['recall'])}، لذلك قد لا يرصد بعض العيوب "
            "الصغيرة أو غير الواضحة، ويُنصح بمراجعة الصور يدويًا في المناطق الحرجة.")
