"""Rebuilds demo_data/ from the WTBD test split. You don't need to run this to use the app.

    python demo_data/build_manifest.py <WTBD JPEGImages folder> <wtbd_split_boxes.csv> [<WTBs2025 images folder>]

1. Takes only images whose split is "test" in wtbd_split_boxes.csv (the near-duplicate-aware split the model was
   evaluated on), so the model never trained on any of them.
2. Runs models/best.pt on each one (confidence 0.25, 1024 px) and stores every detection exactly as returned.
3. Scripts the reviewer's decisions from the dataset's ground-truth boxes: a detection that overlaps a labelled
   defect of the same type is accepted; one with the wrong type is accepted with the type corrected; one that
   overlaps nothing is rejected as a false alarm; a labelled defect the model missed is added by hand.
   Inspections still waiting for a decision (review queue, draft, rejected) can use photos from a third dataset
   the model never saw at all (WTBs2025); they need no labels because nobody has decided on them yet.
4. Writes demo_data/images/ and demo_data/manifest.json. The app loads them into a fresh database on start-up.
"""
import csv
import json
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

CONF, IMGSZ, MATCH_IOU, MISS_IOU = 0.25, 1024, 0.4, 0.3


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def load_gt(csv_path):
    gt, split = defaultdict(list), {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            split[r["stem"]] = r["split"]
            W, H = float(r["W"]), float(r["H"])
            gt[r["stem"]].append({"class": r["cls"], "box": [float(r["x1"]) / W, float(r["y1"]) / H,
                                                            float(r["x2"]) / W, float(r["y2"]) / H]})
    return gt, split


def find_image(folder, stem):
    for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
        p = folder / f"{stem}{ext}"
        if p.exists():
            return p
    return None


def analyse(images_dir, csv_path):
    import cv2
    from ultralytics import YOLO

    gt, split = load_gt(csv_path)
    model = YOLO(str(ROOT / "models" / "best.pt"))
    out = []
    for stem in sorted((s for s, sp in split.items() if sp == "test"), key=lambda s: int(s) if s.isdigit() else s):
        p = find_image(images_dir, stem)
        if not p:
            continue
        img = cv2.imread(str(p))
        h, w = img.shape[:2]
        res = model.predict(img, conf=CONF, imgsz=IMGSZ, iou=0.7, verbose=False)[0]
        dets = []
        for b, c, k in zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
            dets.append({"class": res.names[int(k)], "conf": round(float(c), 4),
                         "box": [round(min(1, max(0, v)), 5) for v in b]})
        # reviewer decisions from ground truth
        used = set()
        for d in sorted(dets, key=lambda d: -d["conf"]):
            best, bi = 0, None
            for i, g in enumerate(gt[stem]):
                if i in used:
                    continue
                v = iou(d["box"], g["box"])
                if v > best:
                    best, bi = v, i
            if bi is not None and best >= MATCH_IOU:
                used.add(bi)
                g = gt[stem][bi]
                d["review"] = {"status": "accepted"} if g["class"] == d["class"] else \
                    {"status": "accepted", "class": g["class"]}
            else:
                d["review"] = {"status": "rejected"}
        missed = [g for i, g in enumerate(gt[stem])
                  if i not in used and all(iou(g["box"], d["box"]) < MISS_IOU for d in dets)]
        out.append({"stem": stem, "path": p, "w": w, "h": h, "dets": dets, "gt": gt[stem], "missed": missed})
    return out


def analyse_unlabelled(folder, limit=160, seed=3):
    from ultralytics import YOLO
    model = YOLO(str(ROOT / "models" / "best.pt"))
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    random.Random(seed).shuffle(files)
    out = []
    for i in range(0, min(limit, len(files)), 16):
        batch = files[i:min(i + 16, limit)]
        for p, res in zip(batch, model.predict([str(x) for x in batch], conf=CONF, imgsz=IMGSZ, iou=0.7, verbose=False)):
            h, w = res.orig_shape
            dets = [{"class": res.names[int(k)], "conf": round(float(c), 4), "box": [round(min(1, max(0, v)), 5) for v in b]}
                    for b, c, k in zip(res.boxes.xyxyn.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist())]
            out.append({"stem": p.stem.split("_jpg")[0], "path": p, "w": w, "h": h, "dets": dets, "gt": [], "missed": []})
    return out


REJECT_NOTES = ["Paint seam, not a defect.", "Shadow on an intact surface.", "Reflection / glare.",
                "Background, not the blade.", "Surface is intact here.", None, None]

# Each plan: status, days ago (created / submitted / reviewed), people, turbine and blade, number of images.
PLANS = [
    dict(status="reported", days_ago=38, submitted_days_ago=37, reviewed_days_ago=36, inspector="inspector@ain.local",
         reviewer="reviewer@ain.local", turbine="DJ-WTG-07", blade="A", n=4, report=True,
         title="Quarterly blade check, Unit 7", weather="Clear, wind 6 m/s", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Omar Alshehri", submit_note="Leading edge of blade A looks worse than last quarter.",
         review_comment="Findings confirmed. The lightning damage needs a structural check before full restart; "
                        "the leading-edge corrosion can wait for the next maintenance window."),
    dict(status="reported", days_ago=31, submitted_days_ago=31, reviewed_days_ago=29, inspector="lina@ain.local",
         reviewer="khalid@ain.local", turbine="YB-WTG-03", blade="B", n=4, report=True,
         title="Post-storm inspection, Unit 3", weather="Hazy, dust in the air", drone_model="DJI Mavic 3 Enterprise",
         operator="Lina Alharbi", submit_note="Flown after last week's thunderstorm.",
         review_comment="No lightning damage found after the storm. The crack needs a close inspection before the "
                        "next maintenance window."),
    dict(status="reported", days_ago=24, submitted_days_ago=23, reviewed_days_ago=22, inspector="faisal@ain.local",
         reviewer="reviewer@ain.local", turbine="DJ-WTG-12", blade="C", n=4, report=True,
         title="Maintenance follow-up, Unit 12", weather="Clear", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Faisal Alqahtani", review_comment="Coating damage is spreading; schedule recoating."),
    dict(source="wtbs", status="rejected", days_ago=18, submitted_days_ago=18, reviewed_days_ago=17, inspector="inspector@ain.local",
         reviewer="khalid@ain.local", turbine="DJ-WTG-07", blade="B", n=3, title="Blade B close-up",
         weather="Windy, gusts 11 m/s", drone_model="DJI Mavic 3 Enterprise", operator="Omar Alshehri",
         review_comment="Two of the three photos are taken from too far away to judge the blade surface. "
                        "Please re-fly blade B at 8 to 10 m and resubmit."),
    dict(status="reported", days_ago=15, submitted_days_ago=14, reviewed_days_ago=13, inspector="lina@ain.local",
         reviewer="reviewer@ain.local", turbine="YB-WTG-08", blade="A", n=4, report=True,
         title="Annual inspection, Unit 8", weather="Clear, wind 4 m/s", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Lina Alharbi", review_comment="Approved. Several cracks on blade A: schedule rope-access repair."),
    dict(status="reviewed", days_ago=10, submitted_days_ago=9, reviewed_days_ago=8, inspector="faisal@ain.local",
         reviewer="khalid@ain.local", turbine="DJ-WTG-15", blade="B", n=4, report=True,
         title="Routine inspection, Unit 15", weather="Clear", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Faisal Alqahtani", review_comment="Approved. Report drafted, waiting for sign-off."),
    dict(status="reviewed", days_ago=6, submitted_days_ago=5, reviewed_days_ago=4, inspector="inspector@ain.local",
         reviewer="reviewer@ain.local", turbine="YB-WTG-03", blade="C", n=3, report=False,
         title="Blade C spot check", weather="Clear", drone_model="DJI Mavic 3 Enterprise", operator="Omar Alshehri",
         review_comment="Approved."),
    dict(source="wtbs", status="in_review", days_ago=3, submitted_days_ago=2, inspector="lina@ain.local", turbine="DJ-WTG-12",
         blade="A", n=4, title="Blade A leading edge", weather="Light dust", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Lina Alharbi", submit_note="Please check the tip area first."),
    dict(source="wtbs", status="in_review", days_ago=2, submitted_days_ago=1, inspector="inspector@ain.local", turbine="YB-WTG-08",
         blade="B", n=3, title="Blade B routine", weather="Clear", drone_model="DJI Mavic 3 Enterprise",
         operator="Omar Alshehri"),
    dict(source="wtbs", status="in_review", days_ago=1, submitted_days_ago=0, inspector="faisal@ain.local", turbine="DJ-WTG-07",
         blade="C", n=3, title="Blade C after cleaning", weather="Clear, wind 5 m/s",
         drone_model="DJI Matrice 350 RTK + H20T", operator="Faisal Alqahtani"),
    dict(source="wtbs", status="draft", days_ago=0, inspector="inspector@ain.local", turbine="DJ-WTG-15", blade="A", n=3,
         title="Blade A morning flight", weather="Clear", drone_model="DJI Matrice 350 RTK + H20T",
         operator="Omar Alshehri"),
]

USERS = [
    dict(name="Admin User", email="admin@ain.local", password="Admin@123", role="admin", job_title="Platform admin",
         joined_days_ago=90),
    dict(name="Sara Reviewer", email="reviewer@ain.local", password="Review@123", role="reviewer",
         job_title="Senior blade inspection engineer", joined_days_ago=88),
    dict(name="Khalid Alotaibi", email="khalid@ain.local", password="Review@123", role="reviewer",
         job_title="Blade integrity engineer", joined_days_ago=80),
    dict(name="Omar Inspector", email="inspector@ain.local", password="Inspect@123", role="inspector",
         job_title="Drone inspection pilot", joined_days_ago=85),
    dict(name="Lina Alharbi", email="lina@ain.local", password="Inspect@123", role="inspector",
         job_title="Drone inspection pilot", joined_days_ago=70),
    dict(name="Faisal Alqahtani", email="faisal@ain.local", password="Inspect@123", role="inspector",
         job_title="Field technician", joined_days_ago=60),
]

TURBINES = [
    dict(code="DJ-WTG-15", name="Unit 15", site="Dumat Al Jandal Wind Farm", region="Al Jouf", latitude=29.85,
         longitude=39.93, manufacturer="Vestas", model="V150-4.2 MW", hub_height_m=105, rotor_diameter_m=150,
         commission_year=2022, status="operational"),
    dict(code="YB-WTG-08", name="Unit 8", site="Yanbu Wind Project", region="Madinah", latitude=24.11,
         longitude=38.09, manufacturer="Siemens Gamesa", model="SG 5.0-145", hub_height_m=110, rotor_diameter_m=145,
         commission_year=2025, status="operational"),
]

TICKETS = [
    dict(user="inspector@ain.local", days_ago=26, topic="Uploads", status="closed",
         subject="Video upload stayed at 0%",
         message="I uploaded a 9-minute video and the progress stayed at 0% for a long time.",
         replies=[dict(author="admin@ain.local", staff=True, days_ago=26,
                       body="Long videos are analysed in the background. Use a 2-second frame interval for videos "
                            "over 5 minutes, and you can close the page while it runs."),
                  dict(author="inspector@ain.local", days_ago=25, body="Worked with 2 seconds, thanks.")]),
    dict(user="lina@ain.local", days_ago=1, topic="Feature request", status="open",
         subject="Blade masking for desert backgrounds",
         message="Sand in the background sometimes gets boxed. Can blade masking be turned on for our site?"),
]


def choose(analysed, rng):
    """Pick images for the plans: mostly images with confirmed defects, every class covered, a few false alarms."""
    good = [a for a in analysed if any(d["review"]["status"] == "accepted" for d in a["dets"])]
    rng.shuffle(good)
    by_class = defaultdict(list)
    for a in good:
        for d in a["dets"]:
            if d["review"]["status"] == "accepted":
                by_class[d["review"].get("class", d["class"])].append(a)
    picked, seen = [], set()
    for cls in sorted(by_class):                      # one image per class first
        for a in by_class[cls]:
            if a["stem"] not in seen:
                picked.append(a)
                seen.add(a["stem"])
                break
    for a in good:
        if a["stem"] not in seen and len(a["dets"]) <= 6:
            picked.append(a)
            seen.add(a["stem"])
    need = sum(p["n"] for p in PLANS if p.get("source") != "wtbs")
    rng.shuffle(picked)
    rest = [a for a in analysed if a["stem"] not in seen]
    rest.sort(key=lambda a: (-len(a["dets"]) if len(a["dets"]) <= 6 else 0))
    picked += rest                                     # top up if there aren't enough confirmed images
    if len(picked) < need:
        raise SystemExit(f"Need {need} test images, found {len(picked)}.")
    return picked[:need]


def choose_unlabelled(un, rng):
    """Queue/draft: photos with 1-4 confident detections. Rejected: wide shots with at most one detection."""
    rng.shuffle(un)
    queue = [a for a in un if 1 <= len(a["dets"]) <= 4 and max(d["conf"] for d in a["dets"]) >= 0.35]
    wide = [a for a in un if len(a["dets"]) <= 1 and a not in queue]
    return queue, wide


def main(images_dir, csv_path, unlabelled_dir=None):
    rng = random.Random(7)
    if not unlabelled_dir:
        for pl in PLANS:
            pl.pop("source", None)
    import os
    import pickle
    cache = os.environ.get("AIN_DEMO_CACHE")          # optional: reuse the model runs between rebuilds
    if cache and Path(cache).exists():
        analysed, unlabelled = pickle.loads(Path(cache).read_bytes())
    else:
        analysed = analyse(Path(images_dir), Path(csv_path))
        unlabelled = analyse_unlabelled(unlabelled_dir) if unlabelled_dir else []
        if cache:
            Path(cache).write_bytes(pickle.dumps((analysed, unlabelled)))
    labelled_plans = [pl for pl in PLANS if pl.get("source") != "wtbs"]
    need = sum(pl["n"] for pl in labelled_plans)
    chosen = choose(analysed, rng)[:need] if need else []
    queue, wide = choose_unlabelled(unlabelled, rng) if unlabelled_dir else ([], [])
    out_imgs = HERE / "images"
    shutil.rmtree(out_imgs, ignore_errors=True)
    out_imgs.mkdir(parents=True)
    plans, k = [], 0
    for i, plan in enumerate(PLANS):
        p = {key: v for key, v in plan.items() if key not in ("n", "source")}
        p["images"] = []
        for j in range(plan["n"]):
            if plan.get("source") == "wtbs":
                a = (wide if plan["status"] == "rejected" else queue).pop(0)
                name = f"wtbs_{a['stem']}.jpg"
                dataset = "WTBs2025 (never used for training)"
            else:
                a = chosen[k]
                k += 1
                name = f"wtbd_{a['stem']}.jpg"
                dataset = "WTBD test split"
            shutil.copyfile(a["path"], out_imgs / name)
            dets = json.loads(json.dumps(a["dets"]))
            for d in dets:
                if plan["status"] in ("in_review", "draft", "rejected"):
                    d.pop("review", None)
                    continue
                r = d["review"]
                if r["status"] == "rejected":
                    note = rng.choice(REJECT_NOTES)
                    if note:
                        r["note"] = note
                elif r["status"] == "accepted" and d["conf"] < 0.35 and rng.random() < 0.35:
                    r["status"] = "uncertain"
                    r["note"] = "Needs a closer photo to confirm."
            added = [] if plan["status"] in ("in_review", "draft", "rejected") else \
                [{"class": g["class"], "box": [round(v, 5) for v in g["box"]]} for g in a["missed"][:1]]
            p["images"].append({"file": name, "name": f"DJI_{20260000 + int(a['stem']) if a['stem'].isdigit() else a['stem']}.jpg",
                                "w": a["w"], "h": a["h"], "detections": dets, "added": added,
                                "source": {"dataset": dataset, "stem": a["stem"]}})
        plans.append(p)
    manifest = {
        "about": "Sample inspections for the Ain demo. Photos: WTBD test split (reviewed inspections) and WTBs2025 "
                 "(inspections still awaiting a decision); the model was never trained on either. "
                 "Detections: real output of models/best.pt at confidence 0.25. Reviewer decisions follow the "
                 "dataset's ground-truth labels. Built by demo_data/build_manifest.py.",
        "model": "models/best.pt (YOLO26m, WTBD + GFD-YOLOX WTBlade, merged v1.2)",
        "users": USERS, "turbines": TURBINES, "inspections": plans, "tickets": TICKETS,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tp = sum(1 for a in analysed for d in a["dets"] if d["review"]["status"] == "accepted")
    nd = sum(len(a["dets"]) for a in analysed)
    ng = sum(len(a["gt"]) for a in analysed)
    print(f"test images analysed: {len(analysed)}; detections {nd}, matched {tp} of {ng} labelled defects "
          f"(precision {tp / max(1, nd):.2f}, recall {tp / max(1, ng):.2f} at conf {CONF}, IoU {MATCH_IOU})")
    print(f"wrote {sum(len(p['images']) for p in plans)} images and {len(plans)} inspections to {HERE}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
