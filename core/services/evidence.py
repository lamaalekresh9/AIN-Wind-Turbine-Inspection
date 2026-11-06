"""Server-side evidence images (annotated frames and crops) for reports and PDF."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .knowledge import info


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def annotate(src_path, findings, out_path, highlight_id=None, max_side=1400):
    img = Image.open(src_path).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)))
        w, h = img.size
    draw = ImageDraw.Draw(img)
    lw = max(2, int(min(w, h) / 220))
    font = _font(max(12, int(min(w, h) / 40)))
    for f in findings:
        color = _hex(info(f.class_name)["color"])
        hl = highlight_id is None or f.id == highlight_id
        box = (f.x1 * w, f.y1 * h, f.x2 * w, f.y2 * h)
        draw.rectangle(box, outline=color if hl else (200, 200, 200), width=lw + (1 if f.id == highlight_id else 0))
        if hl:
            label = f"{f.code} {f.class_name}"
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            ty = box[1] - th - 6 if box[1] - th - 6 > 0 else box[1] + 2
            draw.rectangle((box[0], ty, box[0] + tw + 8, ty + th + 6), fill=color)
            draw.text((box[0] + 4, ty + 2), label, fill=(255, 255, 255), font=font)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88)
    return out_path


def crop(src_path, f, out_path, pad=0.6, min_side=220):
    img = Image.open(src_path).convert("RGB")
    w, h = img.size
    bw, bh = (f.x2 - f.x1) * w, (f.y2 - f.y1) * h
    cx, cy = (f.x1 + f.x2) / 2 * w, (f.y1 + f.y2) / 2 * h
    side_w = max(bw * (1 + pad * 2), min_side)
    side_h = max(bh * (1 + pad * 2), min_side)
    x1, y1 = max(0, cx - side_w / 2), max(0, cy - side_h / 2)
    x2, y2 = min(w, cx + side_w / 2), min(h, cy + side_h / 2)
    c = img.crop((int(x1), int(y1), int(x2), int(y2)))
    d = ImageDraw.Draw(c)
    color = _hex(info(f.class_name)["color"])
    d.rectangle((f.x1 * w - x1, f.y1 * h - y1, f.x2 * w - x1, f.y2 * h - y1), outline=color,
                width=max(2, int(min(c.size) / 120)))
    if max(c.size) > 700:
        r = 700 / max(c.size)
        c = c.resize((int(c.size[0] * r), int(c.size[1] * r)))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    c.save(out_path, "JPEG", quality=88)
    return out_path


def grid_location(f):
    """3x3 grid label of the finding centre (English, Arabic)."""
    cx, cy = (f.x1 + f.x2) / 2, (f.y1 + f.y2) / 2
    row = 0 if cy < 1 / 3 else (1 if cy < 2 / 3 else 2)
    col = 0 if cx < 1 / 3 else (1 if cx < 2 / 3 else 2)
    en_r, en_c = ["top", "middle", "bottom"][row], ["left", "center", "right"][col]
    ar_r, ar_c = ["أعلى", "وسط", "أسفل"][row], ["يسار", "المنتصف", "يمين"][col]
    en = "center" if (row, col) == (1, 1) else f"{en_r}-{en_c}"
    ar = "منتصف الصورة" if (row, col) == (1, 1) else f"{ar_r} {ar_c} الصورة"
    return en, ar
