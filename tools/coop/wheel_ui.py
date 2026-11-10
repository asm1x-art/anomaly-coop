# The co-op wheel's own art (gamedata/scripts/coop_wheel.script, configs/ui/ui_coop_wheel.xml) in the look of the
# game's own companion wheel: the backing and the name plate are the game's textures (ui_hud2_wheel_ammo,
# ui_inGame2_message_box); drawn here are only the buttons' dark discs in their four states (amber when lit) and a
# white line icon for each action, tinted grey or amber by the script. Drawn four times over and scaled down, so the
# edges are smooth. Our own drawings, no assets of other games.
#   python tools\coop\wheel_ui.py   -> gamedata\textures\ui\coop\wheel_*.dds
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "coop"))
SS = 4  # supersampling
INK = (255, 255, 255, 255)  # the icons' lines: white, tinted in the game


def save(img, name):
    path = os.path.join(OUT, name + ".dds")
    img.save(path)  # plain RGBA, as our other UI art: Pillow's DXT5 leaves specks on the thin rings
    print(path, img.size)


# --------------------------------------------------------------------------------------------------
# a button's disc, 128 px (as many as on a 1080p screen): a 100 px disc in the middle, the rest for its glow.
# e enabled, h under the cursor, t pressed, d disabled

BTN = 128
DISC = 100


def radial(size, r, inner, outer):
    # a disc of radius r filled from inner (at 50%, 40%) to outer at its edge, RGBA 0..255
    n = size * SS
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    c = n / 2
    rr = r * SS
    t = np.clip(np.hypot(x - c, y - (c - 0.1 * 2 * rr)) / (rr * 1.1), 0, 1)[..., None]
    col = np.array(inner, np.float32) * (1 - t) + np.array(outer, np.float32) * t
    inside = (np.hypot(x - c, y - c) <= rr)[..., None]
    return Image.fromarray(np.where(inside, col, 0).astype(np.uint8), "RGBA")


def disc(name, inner, outer, ring, glow=None, glow_r=0):
    big = Image.new("RGBA", (BTN * SS, BTN * SS), (0, 0, 0, 0))
    c = BTN * SS / 2
    r = DISC / 2 * SS
    # a soft shadow under it
    sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([c - r, c - r + 2 * SS, c + r, c + r + 2 * SS], fill=(0, 0, 0, 150))
    big.alpha_composite(sh.filter(ImageFilter.GaussianBlur(3 * SS)))
    if glow:
        g = Image.new("RGBA", big.size, (0, 0, 0, 0))
        ImageDraw.Draw(g).ellipse([c - r - 2 * SS, c - r - 2 * SS, c + r + 2 * SS, c + r + 2 * SS], fill=glow)
        big.alpha_composite(g.filter(ImageFilter.GaussianBlur(glow_r * SS)))
    big.alpha_composite(radial(BTN, DISC / 2, inner, outer))
    hl = Image.new("RGBA", big.size, (0, 0, 0, 0))  # a soft light on its top edge
    ImageDraw.Draw(hl).arc([c - r + 3 * SS, c - r + 3 * SS, c + r - 3 * SS, c + r - 3 * SS], 205, 335,
                           fill=(255, 255, 255, 40), width=2 * SS)
    big.alpha_composite(hl.filter(ImageFilter.GaussianBlur(1 * SS)))
    d = ImageDraw.Draw(big)
    d.ellipse([c - r, c - r, c + r, c + r], outline=ring, width=2 * SS)
    save(big.resize((BTN, BTN), Image.LANCZOS), "wheel_btn_" + name)


def discs():
    disc("e", (70, 64, 58, 217), (18, 17, 16, 235), (74, 67, 62, 255))
    disc("h", (110, 84, 40, 230), (30, 24, 16, 240), (138, 106, 44, 255), (238, 155, 23, 110), 7)
    disc("t", (140, 104, 44, 240), (44, 33, 18, 245), (238, 155, 23, 255), (238, 155, 23, 150), 8)
    disc("d", (44, 41, 38, 150), (14, 13, 12, 170), (58, 54, 51, 160))


# --------------------------------------------------------------------------------------------------
# icons: line drawings on a 24 grid with round ends and joins, 1.6 wide, shown at 44 px on a 1080p screen

ICON = 64
K = ICON * SS / 24.0
W = 1.6


def flat(pts):
    return [(x * K, y * K) for x, y in pts]


def stroke(d, pts, w=W):
    pts = flat(pts)
    if len(pts) > 1:
        d.line(pts, fill=INK, width=max(1, int(round(w * K))))
    rr = w * K / 2
    for x, y in pts:  # round joins and ends
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=INK)


def cubic(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, e = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
    return out


def arc(cx, cy, r, a0, a1, n=32):
    # degrees, y down; from a0 to a1
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def dashed(d, pts, on, off, w=W):
    # a polyline cut into dashes on long, off apart
    segs, cur, left, drawing = [], [pts[0]], on, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while seg - pos > left:
            pos += left
            p = (x0 + (x1 - x0) * pos / seg, y0 + (y1 - y0) * pos / seg)
            if drawing:
                cur.append(p)
                segs.append(cur)
            cur = [p]
            drawing = not drawing
            left = on if drawing else off
        left -= seg - pos
        if drawing:
            cur.append((x1, y1))
    if drawing and len(cur) > 1:
        segs.append(cur)
    for s in segs:
        stroke(d, s, w)


def trade(d):
    stroke(d, [(4, 8), (18, 8), (15, 5)])
    stroke(d, [(20, 16), (6, 16), (9, 19)])


def person(d):
    stroke(d, arc(9, 8, 3.5, 0, 360))
    stroke(d, cubic((2.5, 20), (3.3, 16.4), (5.9, 14.5), (9, 14.5)) + cubic((9, 14.5), (12.1, 14.5), (14.7, 16.4),
                                                                              (15.5, 20))[1:])


def group_add(d):
    person(d)
    stroke(d, [(16, 10), (22, 10)])
    stroke(d, [(19, 7), (19, 13)])


def group_remove(d):
    person(d)
    stroke(d, [(16, 10), (22, 10)])


def group_leave(d):
    stroke(d, [(14, 4), (6, 4), (6, 20), (14, 20)])
    stroke(d, [(11, 12), (21, 12)])
    stroke(d, [(18, 9), (21, 12), (18, 15)])


def notes(d):
    stroke(d, [(6, 3), (14, 3), (18, 7), (18, 21), (6, 21), (6, 3)])
    stroke(d, [(14, 3), (14, 7), (18, 7)])
    stroke(d, [(9, 12), (15, 12)])
    stroke(d, [(9, 15.5), (15, 15.5)])


def pin(d, x, y):
    # a map pin: a round head at (x, y + 3) with a point under it at (x, y + 8)
    head = arc(x, y + 3, 3, 180, 360)
    tip = cubic((x + 3, y + 3), (x + 3, y + 5.2), (x, y + 8), (x, y + 8)) + \
        cubic((x, y + 8), (x, y + 8), (x - 3, y + 5.2), (x - 3, y + 3))[1:]
    stroke(d, head + tip[1:])


def routes(d):
    pin(d, 6, 3.5)
    pin(d, 18, 12.5)
    dashed(d, [(6, 14), (6, 15.5)] + arc(9, 15.5, 3, 180, 90)[1:] + [(12, 18.5)], 1.5, 2)


def story(d):
    left = cubic((12, 6), (10, 4.5), (7, 4), (4, 4.5)) + [(4, 17.5)] + cubic((4, 17.5), (7, 17), (10, 17.5),
                                                                              (12, 19))
    right = cubic((12, 6), (14, 4.5), (17, 4), (20, 4.5)) + [(20, 17.5)] + cubic((20, 17.5), (17, 17), (14, 17.5),
                                                                                (12, 19))
    stroke(d, left)
    stroke(d, right)
    stroke(d, [(12, 6), (12, 19)])


def icon(name, fn):
    big = Image.new("RGBA", (ICON * SS, ICON * SS), (255, 255, 255, 0))
    fn(ImageDraw.Draw(big))
    save(big.resize((ICON, ICON), Image.LANCZOS), "wheel_" + name)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    discs()
    icon("trade", trade)
    icon("group_add", group_add)
    icon("group_remove", group_remove)
    icon("group_leave", group_leave)
    icon("notes", notes)
    icon("routes", routes)
    icon("story", story)
