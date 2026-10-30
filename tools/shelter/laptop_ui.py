# The Chemist's laptop, a modern dark desktop (docs/coop/shelter.md, "План развития", phase 1; its look:
# gamedata/scripts/ui_shelter_style.script): the wallpaper and the system's sign on it, the programs' icons, the plan's
# marks, the system's glyphs, a white to tint, a disc whose quarters round the corners, and see-through frame parts for
# the typing fields. Drawn four times over and scaled down, so the edges are smooth.
#   laptop_ui.py   -> gamedata\textures\ui\shelter\laptop_*.dds, os_*.dds
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "shelter"))
SS = 4  # supersampling
ACCENT = (46, 196, 170)
FONTS = "C:\\Windows\\Fonts\\"


def font(name, size):
    try:
        return ImageFont.truetype(FONTS + name, size)
    except OSError:
        return ImageFont.truetype("arial.ttf", size)


def save(img, name):
    path = os.path.join(OUT, name + ".dds")
    img.save(path)
    print(path, img.size)


def drawn(size, draw_fn, name):
    """draw_fn(draw, s) on a size x size canvas SS times larger (s: the scale), then scaled down"""
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(big), SS * size / 64.0, big)
    save(big.resize((size, size), Image.LANCZOS), name)


os.makedirs(OUT, exist_ok=True)

# a white to tint: the surfaces, lines, highlights; a white disc: its quarters round the corners of boxes
save(Image.new("RGBA", (8, 8), (255, 255, 255, 255)), "laptop_white")
drawn(64, lambda d, s, im: d.ellipse([0, 0, 64 * s - 1, 64 * s - 1], fill=(255, 255, 255, 255)), "os_corner")

# the wallpaper: a deep slate night with soft glows of the accent and of violet, a fine grain against banding
W, H = 1024, 576
rng = np.random.default_rng(7)
y, x = np.mgrid[0:H, 0:W].astype(np.float64)
base = np.zeros((H, W, 3))
top, bottom = np.array([14, 18, 26]), np.array([8, 10, 14])
base += top + (bottom - top) * (y / H)[..., None]
for cx, cy, r, col, k in ((0.18, 0.85, 0.55, (30, 140, 130), 0.55), (0.82, 0.18, 0.5, (70, 60, 140), 0.45),
                          (0.6, 0.75, 0.35, (20, 90, 110), 0.35)):
    d2 = ((x / W - cx) * 1.6) ** 2 + (y / H - cy) ** 2
    base += np.array(col) * k * np.exp(-d2 / (r * r * 0.35))[..., None]
# a few sweeping light curves
for a, b, c, col in ((0.0009, 0.55, 0.0, (46, 196, 170)), (0.0011, 0.62, 1.2, (120, 110, 220))):
    curve = H * b + 90 * np.sin(x * a * 6 + c)
    base += np.array(col) * 0.12 * np.exp(-((y - curve) / 26) ** 2)[..., None]
base += rng.normal(0, 1.2, (H, W, 1))
wp = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
save(wp, "laptop_wallpaper")

# the system's sign in the wallpaper's middle (kept square on a wide screen): a thin trefoil of the Zone in a ring, the
# system's name under it
LW, LH = 400, 300
big = Image.new("RGBA", (LW * SS, LH * SS), (0, 0, 0, 0))
d = ImageDraw.Draw(big)
cx, cy, rad = LW * SS // 2, 110 * SS, 80 * SS
faint = (220, 235, 235, 70)
d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=faint, width=3 * SS)
for k in range(3):
    a0 = math.radians(90 + k * 120)
    pts = [(cx + math.cos(a0 + math.radians(t)) * 18 * SS, cy - math.sin(a0 + math.radians(t)) * 18 * SS) for t in (-30, 30)]
    for t in range(30, -31, -3):
        pts.append((cx + math.cos(a0 + math.radians(t)) * (rad - 16 * SS), cy - math.sin(a0 + math.radians(t)) * (rad - 16 * SS)))
    d.polygon(pts, fill=(220, 235, 235, 40))
d.ellipse([cx - 10 * SS, cy - 10 * SS, cx + 10 * SS, cy + 10 * SS], fill=(220, 235, 235, 70))
f = font("segoeuil.ttf", 46 * SS)
title = "Химик OS"
d.text((cx - d.textlength(title, font=f) / 2, cy + rad + 22 * SS), title, font=f, fill=(230, 240, 240, 90))
save(big.resize((LW, LH), Image.LANCZOS), "laptop_logo")


# the programs' icons, 64x64: a rounded tile with a gradient, a white sign on it
def tile(d, s, im, c0, c1):
    t = Image.new("RGBA", im.size, (0, 0, 0, 0))
    g = np.zeros((im.size[1], im.size[0], 4), np.uint8)
    yy = np.linspace(0, 1, im.size[1])[:, None]
    for i in range(3):
        g[..., i] = (c0[i] + (c1[i] - c0[i]) * yy).astype(np.uint8)
    g[..., 3] = 255
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([4 * s, 4 * s, 60 * s, 60 * s], radius=14 * s, fill=255)
    t = Image.fromarray(g, "RGBA")
    im.paste(t, (0, 0), mask)
    hl = Image.new("L", im.size, 0)  # a soft light on its upper half
    ImageDraw.Draw(hl).rounded_rectangle([4 * s, 4 * s, 60 * s, 32 * s], radius=14 * s, fill=28)
    im.paste((255, 255, 255, 255), (0, 0), hl)


WHITE = (255, 255, 255, 255)


def plan_icon(d, s, im):
    tile(d, s, im, (64, 150, 255), (32, 92, 210))
    d.rounded_rectangle([16 * s, 16 * s, 48 * s, 48 * s], radius=3 * s, outline=WHITE, width=int(3 * s))
    d.line([(16 * s, 30 * s), (34 * s, 30 * s)], fill=WHITE, width=int(3 * s))
    d.line([(34 * s, 16 * s), (34 * s, 40 * s)], fill=WHITE, width=int(3 * s))
    d.line([(26 * s, 30 * s), (26 * s, 48 * s)], fill=WHITE, width=int(3 * s))


def bar_icon(d, s, im):
    tile(d, s, im, (255, 176, 64), (226, 112, 30))
    d.rounded_rectangle([18 * s, 22 * s, 40 * s, 48 * s], radius=4 * s, fill=WHITE)  # a mug
    d.arc([34 * s, 26 * s, 48 * s, 42 * s], 270, 90, fill=WHITE, width=int(4 * s))  # its handle
    for k, cx in enumerate((21, 28, 35)):  # the foam
        d.ellipse([(cx - 5) * s, (16 + (k % 2) * 2) * s, (cx + 5) * s, (26 + (k % 2) * 2) * s], fill=WHITE)
    for cx in (24, 29, 34):
        d.line([(cx * s, 30 * s), (cx * s, 44 * s)], fill=(236, 150, 50, 255), width=int(2 * s))


def synth_icon(d, s, im):
    tile(d, s, im, (60, 214, 180), (22, 150, 132))
    d.rounded_rectangle([27 * s, 14 * s, 37 * s, 28 * s], radius=1 * s, fill=WHITE)  # a flask's neck
    d.polygon([(27 * s, 26 * s), (37 * s, 26 * s), (49 * s, 48 * s), (15 * s, 48 * s)], fill=WHITE)  # its body
    d.rounded_rectangle([14 * s, 44 * s, 50 * s, 50 * s], radius=3 * s, fill=WHITE)
    d.polygon([(20 * s, 38 * s), (44 * s, 38 * s), (48 * s, 46 * s), (16 * s, 46 * s)], fill=(30, 170, 150, 255))
    d.ellipse([29 * s, 33 * s, 35 * s, 39 * s], fill=(200, 255, 240, 255))  # a bubble
    d.rounded_rectangle([25 * s, 11 * s, 39 * s, 15 * s], radius=2 * s, fill=WHITE)


def clean_icon(d, s, im):
    tile(d, s, im, (170, 120, 255), (110, 70, 220))
    d.line([(44 * s, 14 * s), (30 * s, 34 * s)], fill=WHITE, width=int(4 * s))  # a broom's handle
    d.polygon([(22 * s, 32 * s), (36 * s, 40 * s), (30 * s, 50 * s), (14 * s, 46 * s)], fill=WHITE)  # its head
    for cx, cy, r in ((46, 40, 4), (40, 48, 2.5), (50, 30, 2)):  # sparkles
        d.polygon([((cx - r) * s, cy * s), (cx * s, (cy - r * 1.8) * s), ((cx + r) * s, cy * s), (cx * s, (cy + r * 1.8) * s)], fill=WHITE)


def map_icon(d, s, im):
    tile(d, s, im, (110, 200, 90), (60, 150, 60))
    d.polygon([(14 * s, 20 * s), (26 * s, 15 * s), (38 * s, 20 * s), (50 * s, 15 * s), (50 * s, 44 * s), (38 * s, 49 * s),
               (26 * s, 44 * s), (14 * s, 49 * s)], outline=WHITE, width=int(3 * s))
    d.ellipse([33 * s, 24 * s, 43 * s, 34 * s], fill=WHITE)


def raid_icon(d, s, im):
    tile(d, s, im, (236, 92, 76), (170, 40, 40))
    d.ellipse([17 * s, 17 * s, 47 * s, 47 * s], outline=WHITE, width=int(3 * s))  # a sight's ring
    for a, b in (((32, 11), (32, 22)), ((32, 42), (32, 53)), ((11, 32), (22, 32)), ((42, 32), (53, 32))):  # its ticks
        d.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=WHITE, width=int(3 * s))
    d.ellipse([29 * s, 29 * s, 35 * s, 35 * s], fill=WHITE)


for name, fn in (("plan", plan_icon), ("bar", bar_icon), ("synth", synth_icon), ("clean", clean_icon), ("map", map_icon),
                 ("raid", raid_icon)):
    drawn(64, fn, "laptop_icon_" + name)


# the plan's marks, 32x32: a round badge with a sign
def badge(col, sign=None):
    def fn(d, s, im):
        d.ellipse([3 * s, 3 * s, 61 * s, 61 * s], fill=(16, 18, 22, 255))
        d.ellipse([8 * s, 8 * s, 56 * s, 56 * s], fill=col + (255,))
        if sign:
            sign(d, s)
    return fn


DARK = (16, 18, 22, 255)
marks = {
    "generator": badge((250, 200, 60), lambda d, s: d.polygon(
        [(36 * s, 14 * s), (22 * s, 36 * s), (31 * s, 36 * s), (27 * s, 50 * s), (42 * s, 28 * s), (33 * s, 28 * s)], fill=DARK)),
    "laptop": badge((110, 180, 255), lambda d, s: (d.rounded_rectangle([20 * s, 22 * s, 44 * s, 38 * s], radius=2 * s, fill=DARK),
                                                   d.rectangle([16 * s, 40 * s, 48 * s, 44 * s], fill=DARK))),
    "stash": badge((210, 150, 90), lambda d, s: (d.rectangle([19 * s, 24 * s, 45 * s, 44 * s], fill=DARK),
                                                 d.rectangle([19 * s, 20 * s, 45 * s, 26 * s], fill=DARK))),
    "chamber": badge(ACCENT, lambda d, s: (d.rectangle([28 * s, 16 * s, 36 * s, 28 * s], fill=DARK),
                                           d.polygon([(28 * s, 26 * s), (36 * s, 26 * s), (46 * s, 46 * s), (18 * s, 46 * s)], fill=DARK))),
    "me": badge((100, 220, 120)),
    "friend": badge((110, 170, 255)),
    "raid_note": badge((236, 92, 76), lambda d, s: (d.rounded_rectangle([28 * s, 15 * s, 36 * s, 38 * s], radius=3 * s, fill=DARK),
                                                    d.ellipse([28 * s, 42 * s, 36 * s, 50 * s], fill=DARK))),
}
for name, fn in marks.items():
    drawn(32, fn, "laptop_mark_" + name)

# the system's glyphs, white to tint (Segoe Fluent Icons): close, power, search; the start button's sign
def glyph(ch, name, size=32):
    icons = font("SegoeIcons.ttf", int(size * SS * 0.72))

    def fn(d, s, im):
        bb = d.textbbox((0, 0), ch, font=icons)
        d.text(((im.size[0] - (bb[2] - bb[0])) / 2 - bb[0], (im.size[1] - (bb[3] - bb[1])) / 2 - bb[1]), ch, font=icons, fill=WHITE)
    drawn(size, fn, name)


glyph("\ue8bb", "os_close")
glyph("\ue7e8", "os_power")
glyph("\ue721", "os_search")


def start_sign(d, s, im):  # the system's sign: the trefoil in a ring
    c, r = 32 * s, 26 * s
    d.ellipse([c - r, c - r, c + r, c + r], outline=WHITE, width=int(4 * s))
    for k in range(3):
        a0 = math.radians(90 + k * 120)
        pts = [(c + math.cos(a0 + math.radians(t)) * 6 * s, c - math.sin(a0 + math.radians(t)) * 6 * s) for t in (-30, 30)]
        pts += [(c + math.cos(a0 + math.radians(t)) * 19 * s, c - math.sin(a0 + math.radians(t)) * 19 * s) for t in range(30, -31, -5)]
        d.polygon(pts, fill=WHITE)


drawn(64, start_sign, "os_start")

# the parts of a see-through frame for the typing fields (ui_shelter_laptop.xml "edit": what's under it is the script's)
for part in ("back", "b", "e"):
    save(Image.new("RGBA", (4, 4), (0, 0, 0, 0)), "laptop_clear_" + part)
