# The co-op wheel (gamedata/scripts/coop_wheel.script, configs/ui/ui_coop_wheel.xml) in the modern dark style of our
# other windows (gamedata/scripts/ui_shelter_style.script): its round backing, the buttons' discs in their four states
# and a light line icon for each action. Drawn four times over and scaled down, so the edges are smooth. Our own
# drawings, no assets of other games.
#   python tools\coop\wheel_ui.py   -> gamedata\textures\ui\coop\wheel_*.dds
import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "coop"))
SS = 4  # supersampling
ACCENT = (46, 196, 170)
INK = (226, 236, 236, 255)  # the icons' lines


def save(img, name):
    path = os.path.join(OUT, name + ".dds")
    img.save(path)
    print(path, img.size)


def canvas(w, h):
    return Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))


def down(big, w, h):
    return big.resize((w, h), Image.LANCZOS)


# --------------------------------------------------------------------------------------------------
# the wheel's backing: a dark glassy disc with a thin accent ring, a lighter middle for the hint

def backing():
    w, h = 440, 420
    big = canvas(w, h)
    d = ImageDraw.Draw(big)
    cx, cy = w * SS / 2, h * SS / 2
    r = 206 * SS
    glow = canvas(w, h)
    ImageDraw.Draw(glow).ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACCENT + (90,), width=10 * SS)
    big.alpha_composite(glow.filter(ImageFilter.GaussianBlur(8 * SS)))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(13, 17, 24, 225), outline=ACCENT + (150,), width=2 * SS)
    ri = 84 * SS
    d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=(20, 26, 35, 235), outline=(255, 255, 255, 38), width=2 * SS)
    save(down(big, w, h), "wheel_bg")


# the name plate under the wheel
def plate():
    w, h = 341, 60
    big = canvas(w, h)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle([SS, SS, (w - 1) * SS, (h - 1) * SS], radius=14 * SS, fill=(13, 17, 24, 225),
                        outline=ACCENT + (130,), width=2 * SS)
    save(down(big, w, h), "wheel_plate")


# a button's disc: e enabled, h under the cursor, t pressed, d disabled
def discs():
    size = 100
    states = {
        "e": dict(fill=(24, 31, 42, 240), ring=(255, 255, 255, 46), width=2, glow=None),
        "h": dict(fill=(28, 46, 52, 245), ring=ACCENT + (255,), width=3, glow=ACCENT + (150,)),
        "t": dict(fill=(30, 92, 84, 250), ring=ACCENT + (255,), width=3, glow=ACCENT + (190,)),
        "d": dict(fill=(18, 20, 25, 150), ring=(255, 255, 255, 20), width=2, glow=None),
    }
    for state, st in states.items():
        big = canvas(size, size)
        c = size * SS / 2
        r = 44 * SS
        if st["glow"]:
            g = canvas(size, size)
            ImageDraw.Draw(g).ellipse([c - r, c - r, c + r, c + r], outline=st["glow"], width=8 * SS)
            big.alpha_composite(g.filter(ImageFilter.GaussianBlur(4 * SS)))
        ImageDraw.Draw(big).ellipse([c - r, c - r, c + r, c + r], fill=st["fill"], outline=st["ring"],
                                    width=st["width"] * SS)
        save(down(big, size, size), "wheel_btn_" + state)


# --------------------------------------------------------------------------------------------------
# icons: drawn on a 64 grid (s = the scale), light lines on clear

def icon(name, fn, size=64):
    big = canvas(size, size)
    fn(ImageDraw.Draw(big), SS * size / 64.0)
    save(down(big, size, size), "wheel_" + name)


def P(s, *xy):
    return [(x * s, y * s) for x, y in zip(xy[0::2], xy[1::2])]


def line(d, s, *xy, w=4):
    d.line(P(s, *xy), fill=INK, width=int(w * s), joint="curve")
    for x, y in zip(xy[0::2], xy[1::2]):  # round ends
        rr = w * s / 2
        d.ellipse([x * s - rr, y * s - rr, x * s + rr, y * s + rr], fill=INK)


def arrow_head(d, s, x, y, dx, w=4):
    # a filled head pointing along dx (+1 right, -1 left)
    d.polygon(P(s, x, y - 7, x + 9 * dx, y, x, y + 7), fill=INK)


# trade: two arrows passing each other
def trade(d, s):
    line(d, s, 10, 22, 44, 22)
    arrow_head(d, s, 44, 22, 1)
    line(d, s, 54, 42, 20, 42)
    arrow_head(d, s, 20, 42, -1)


def person(d, s, x, y, k=1.0):
    r = 7 * k
    d.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], outline=INK, width=int(4 * s))
    d.arc([(x - 13 * k) * s, (y + 10 * k) * s, (x + 13 * k) * s, (y + 36 * k) * s], 180, 360, fill=INK,
          width=int(4 * s))


# the group: someone with a plus (invite) or a minus (leave, put out)
def group_add(d, s):
    person(d, s, 26, 20)
    line(d, s, 50, 28, 50, 44)
    line(d, s, 42, 36, 58, 36)


def group_remove(d, s):
    person(d, s, 26, 20)
    line(d, s, 42, 36, 58, 36)


# notes: a sheet with a folded corner and lines
def notes(d, s):
    d.line(P(s, 16, 8, 40, 8, 50, 18, 50, 56, 16, 56, 16, 8), fill=INK, width=int(4 * s), joint="curve")
    d.line(P(s, 40, 8, 40, 18, 50, 18), fill=INK, width=int(3 * s))
    for y in (28, 37, 46):
        line(d, s, 23, y, 43, y, w=3)


# routes: two map pins joined by a dashed path
def pin(d, s, x, y):
    r = 8
    d.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], outline=INK, width=int(4 * s))
    d.polygon(P(s, x - 7, y + 4, x + 7, y + 4, x, y + 15), fill=INK)
    d.ellipse([(x - 2.5) * s, (y - 2.5) * s, (x + 2.5) * s, (y + 2.5) * s], fill=INK)


def routes(d, s):
    pin(d, s, 16, 14)
    pin(d, s, 48, 34)
    pts = [(16, 32), (20, 44), (30, 50), (40, 52), (48, 52)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        line(d, s, x0, y0, mx, my, w=3)


# the story: an open book with a star over it
def story(d, s):
    d.line(P(s, 32, 26, 22, 20, 8, 20, 8, 52, 22, 52, 32, 58, 42, 52, 56, 52, 56, 20, 42, 20, 32, 26, 32, 58),
           fill=INK, width=int(4 * s), joint="curve")
    cx, cy, ro, ri = 32, 9, 8, 3.4
    pts = []
    for k in range(10):
        a = math.radians(90 + k * 36)
        r = ro if k % 2 == 0 else ri
        pts += [cx + math.cos(a) * r, cy - math.sin(a) * r]
    d.polygon(P(s, *pts), fill=ACCENT + (255,))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    backing()
    plate()
    discs()
    icon("trade", trade)
    icon("group_add", group_add)
    icon("group_remove", group_remove)
    icon("notes", notes)
    icon("routes", routes)
    icon("story", story)
