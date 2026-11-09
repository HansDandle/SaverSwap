"""Draws the Roku app icons (roku/images/icon_hd.png 290x218, icon_fhd.png 540x405).
Needs Pillow: pip install pillow. Only for maintainers; the icons are committed."""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "roku", "images")


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def icon(w, h):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    top, bottom = (14, 60, 92), (8, 20, 36)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    # a soft "screen glow" ring with two arrows suggesting swap
    cx, cy, r = w // 2, int(h * 0.42), int(h * 0.22)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(92, 200, 220), width=max(3, w // 90))
    a, gap, lw, head = int(r * 0.55), int(r * 0.28), max(4, w // 60), int(r * 0.28)

    def arrow(y, right, color):
        x0, x1 = (cx - a, cx + a) if right else (cx + a, cx - a)
        tip = x1
        base = x1 - head if right else x1 + head
        d.line([(x0, y), (base, y)], fill=color, width=lw)
        d.polygon([(tip, y), (base, y - head // 1.4), (base, y + head // 1.4)], fill=color)

    arrow(cy - gap, True, (240, 196, 120))
    arrow(cy + gap, False, (240, 150, 90))
    f = font(int(h * 0.15))
    text = "SaverSwap"
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, h * 0.74), text, font=f, fill=(235, 244, 248))
    return img


os.makedirs(OUT, exist_ok=True)
icon(540, 405).save(os.path.join(OUT, "icon_fhd.png"))
icon(290, 218).save(os.path.join(OUT, "icon_hd.png"))
print("icons written to", os.path.abspath(OUT))
