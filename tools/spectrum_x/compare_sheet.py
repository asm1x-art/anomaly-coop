"""Rows of preview renders (glb_preview.py output) side by side, with a zoomed crop, into one labelled sheet.
python compare_sheet.py out.png "<title>" --crop x0 y0 x1 y1 --row "<label>" <dir> <name> [--row ...]
crop is in fractions of the side view."""
import sys
from PIL import Image, ImageDraw, ImageFont
a = sys.argv; out, title = a[1], a[2]
crop = tuple(map(float, a[a.index("--crop") + 1:a.index("--crop") + 5])) if "--crop" in a else None
rows = [(a[i + 1], a[i + 2], a[i + 3]) for i in range(len(a)) if a[i] == "--row"]
cell, pad, head, lab = 560, 12, 60, 300
cols = 3 if crop else 2
W = lab + cols * (cell + pad) + pad; H = head + len(rows) * (cell + pad) + pad
sh = Image.new("RGB", (W, H), (38, 38, 38)); dr = ImageDraw.Draw(sh)
f1 = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 30); f2 = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 24)
dr.text((pad, 12), title, fill=(235, 235, 235), font=f1)
for r, (label, d, n) in enumerate(rows):
    y = head + r * (cell + pad)
    dr.multiline_text((pad, y + 10), label.replace("|", "\n"), fill=(225, 225, 225), font=f2, spacing=6)
    views = [Image.open(f"{d}/{n}_34.png"), Image.open(f"{d}/{n}_side.png")]
    if crop:
        s = views[1]; w, h = s.size
        views.append(s.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h))))
    for c, im in enumerate(views):
        sh.paste(im.convert("RGB").resize((cell, cell), Image.LANCZOS), (lab + pad + c * (cell + pad), y))
sh.save(out); print(out)
