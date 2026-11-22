"""Decal for the tablet's button panel: black rubber button tops with clear icons + a clean yellow radiation sign.
python tablet_decal.py <height.npy> <out.png> [--ppu 4000]
height.npy from height_probe.py over x -0.40..0.30, y -0.25..0.25 (the tablet turned by --rot-y -9.66, screen up = -x).
The decal covers x 0.07..0.20, y -0.20..0.20; bake.py lays it on with
  --decal-box "+y -x -0.20 -0.20 0.20 -0.07" --decal-normal +z
Buttons are found from the height map (tops above the panel's recess), so the black fill sits exactly on them."""
import sys, math
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
h = np.load(sys.argv[1]); out = sys.argv[2]
ppu = 4000; SS = 4                      # supersampling for the drawn shapes
X0, Y0 = -0.40, -0.25                   # origin of the height map
DX0, DX1, DY0, DY1 = 0.07, 0.20, -0.20, 0.20
r = lambda x: int(round((x - X0) * ppu)); c = lambda y: int(round((y - Y0) * ppu))
p = np.nan_to_num(h[r(DX0):r(DX1), c(DY0):c(DY1)], nan=0)
H, W = p.shape
lab, n = ndimage.label(p > 0.053)
btn = np.zeros_like(p, bool); boxes = []
for i, sl in enumerate(ndimage.find_objects(lab)):
    a, b = sl; m = lab == i + 1
    if a.start == 0 or b.start == 0 or a.stop == H or b.stop == W or m.sum() < 500:
        continue
    btn |= ndimage.binary_erosion(m, iterations=2)
    boxes.append((a.start, a.stop, b.start, b.stop))
# RGBA at SS x
img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
RUBBER = (24, 24, 26, 255); ICON = (214, 214, 208, 255)
bm = Image.fromarray((btn * 255).astype(np.uint8)).resize((W * SS, H * SS), Image.BILINEAR)
img.paste(Image.new("RGBA", img.size, RUBBER), (0, 0), bm)
def tri(cx, cy, s, ang):   # filled triangle pointing at ang (deg, 0 = right, 90 = up in the image)
    pts = [(cx + s * math.cos(math.radians(ang + k * 120)), cy - s * math.sin(math.radians(ang + k * 120))) for k in range(3)]
    d.polygon(pts, fill=ICON)
for (r0, r1, c0, c1) in boxes:
    cx, cy = (c0 + c1) / 2 * SS, (r0 + r1) / 2 * SS
    w, hh = (c1 - c0) * SS, (r1 - r0) * SS
    yc = Y0 + (c0 + c1) / 2 / ppu + (DY0 - Y0) ; xc = (r0 + r1) / 2 / ppu + DX0
    s = min(w, hh) * 0.22
    if yc < -0.07:                          # left column: menu (upper) and back (lower)
        if xc < 0.13:                       # menu: three lines in a frame
            fw, fh = s * 2.0, s * 1.5
            d.rounded_rectangle((cx - fw, cy - fh, cx + fw, cy + fh), radius=s * 0.25, outline=ICON, width=int(s * 0.28))
            for k in (-1, 0, 1):
                y = cy + k * fh * 0.45
                d.line((cx - fw * 0.6, y, cx + fw * 0.6, y), fill=ICON, width=int(s * 0.24))
        else:                               # back: U-turn arrow
            R = s * 1.1; lw = int(s * 0.32)
            d.arc((cx - R, cy - R, cx + R, cy + R), start=270, end=90, fill=ICON, width=lw)
            d.line((cx - R * 1.2, cy - R + lw / 2, cx, cy - R + lw / 2), fill=ICON, width=lw)
            d.line((cx - R * 1.2, cy + R - lw / 2, cx, cy + R - lw / 2), fill=ICON, width=lw)
            tri(cx - R * 1.35, cy - R + lw / 2, s * 0.75, 180)
    else:                                   # d-pad: arrow away from the pad's centre
        dy, dx = yc, xc - 0.131
        ang = 0 if dy > 0.01 else 180 if dy < -0.01 else (90 if dx < 0 else 270)
        tri(cx, cy, s * 1.1, ang)
# radiation sign: clean yellow triangle, black trefoil, right of the d-pad
sx, sy = c(0.125) - c(DY0), r(0.136) - r(DX0)
S = 0.036 * ppu * SS; cx, cy = sx * SS, sy * SS
pts = [(cx + S * math.cos(math.radians(90 + k * 120)), cy - S * math.sin(math.radians(90 + k * 120))) for k in range(3)]
d.polygon(pts, fill=(28, 26, 22, 255))
pts2 = [(cx + S * 0.86 * math.cos(math.radians(90 + k * 120)), cy - S * 0.86 * math.sin(math.radians(90 + k * 120))) for k in range(3)]
d.polygon(pts2, fill=(232, 188, 36, 255))
ty = cy + S * 0.02; R1, R0 = S * 0.33, S * 0.07
for k in range(3):
    a0 = 30 + k * 120 - 30                 # blades at 30, 150, 270 deg: two up, one down
    d.pieslice((cx - R1, ty - R1, cx + R1, ty + R1), start=-(a0 + 60), end=-a0, fill=(20, 20, 18, 255))
d.ellipse((cx - R0 * 1.7, ty - R0 * 1.7, cx + R0 * 1.7, ty + R0 * 1.7), fill=(232, 188, 36, 255))
d.ellipse((cx - R0, ty - R0, cx + R0, ty + R0), fill=(20, 20, 18, 255))
img = img.resize((W * 2, H * 2), Image.LANCZOS)
img.save(out); print(out, img.size, "buttons", len(boxes))
