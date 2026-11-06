"""Merge detections of the same physical defect across neighbouring video frames (FR-06)."""


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def center_dist(a, b):
    ax, ay = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def consolidate(frame_dets, iou_thr=0.3, center_thr=0.06, max_gap=2):
    """frame_dets: ordered list of (sample_idx, frame_ref, timestamp, [det, ...]).

    A detection joins an existing track when it has the same class, the track was seen
    within `max_gap` sampled frames, and boxes overlap (IoU) or their centres are close.
    Each track becomes one finding whose evidence is its highest-confidence frame.
    """
    tracks, active = [], []
    for sidx, fref, ts, dets in frame_dets:
        active = [t for t in active if sidx - t["last_idx"] <= max_gap]
        used = set()
        for d in sorted(dets, key=lambda x: -x["confidence"]):
            best, best_score = None, 0.0
            for ti, t in enumerate(active):
                if ti in used or t["class_name"] != d["class_name"] or t["last_idx"] == sidx:
                    continue
                o = iou(t["last_box"], d["box"])
                cd = center_dist(t["last_box"], d["box"])
                if o >= iou_thr or cd <= center_thr:
                    score = o + (center_thr - cd if cd <= center_thr else 0)
                    if score > best_score:
                        best, best_score = ti, score
            if best is None:
                t = {
                    "class_name": d["class_name"],
                    "best": d, "best_frame": fref, "best_ts": ts,
                    "first_ts": ts, "last_ts": ts,
                    "last_idx": sidx, "last_box": d["box"],
                    "frames": [fref], "count": 1,
                }
                tracks.append(t)
                active.append(t)
                used.add(len(active) - 1)
            else:
                t = active[best]
                used.add(best)
                t["last_idx"], t["last_box"], t["last_ts"] = sidx, d["box"], ts
                t["count"] += 1
                if fref not in t["frames"]:
                    t["frames"].append(fref)
                if d["confidence"] > t["best"]["confidence"]:
                    t["best"], t["best_frame"], t["best_ts"] = d, fref, ts
    return tracks
