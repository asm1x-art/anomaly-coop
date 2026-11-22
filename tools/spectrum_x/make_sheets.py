"""Contact sheets with labels from preview_hud.py's frames.  python make_sheets.py <dir> <out.png> <cols> <png>..."""
import sys, os
from PIL import Image, ImageDraw, ImageFont
d, out, cols = sys.argv[1], sys.argv[2], int(sys.argv[3])
names = sys.argv[4:]
ims = [Image.open(os.path.join(d, n)).convert("RGB") for n in names]
w, h = ims[0].size; rows = (len(ims) + cols - 1) // cols
S = Image.new("RGB", (cols * w, rows * h), (0, 0, 0)); dr = ImageDraw.Draw(S)
try:
    f = ImageFont.truetype("arial.ttf", max(14, h // 22))
except OSError:
    f = ImageFont.load_default()
for i, (n, im) in enumerate(zip(names, ims)):
    x, y = (i % cols) * w, (i // cols) * h
    S.paste(im, (x, y)); label = os.path.splitext(n)[0].replace("spectrum_x_", "")
    dr.rectangle((x, y, x + w - 1, y + h - 1), outline=(20, 20, 20))
    dr.text((x + 8, y + 6), label, fill=(255, 255, 255), font=f, stroke_width=2, stroke_fill=(0, 0, 0))
S.save(out); print(out, S.size)
