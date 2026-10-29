# The laptop's desktop, an old OS on the Chemist's laptop (docs/coop/shelter.md, "План развития", phase 1): its
# wallpaper, the shortcuts' icons, the map's marks and a white for the windows' parts (tinted in the UI).
#   laptop_ui.py   -> gamedata\textures\ui\shelter\laptop_*.dds
import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "shelter"))


def font(size, bold=False):
    for name in (("tahomabd.ttf" if bold else "tahoma.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def save(img, name):
    path = os.path.join(OUT, name + ".dds")
    img.save(path)
    print(path, img.size)


os.makedirs(OUT, exist_ok=True)

# a white to tint: the windows' faces, frames, the taskbar, highlights
save(Image.new("RGBA", (8, 8), (255, 255, 255, 255)), "laptop_white")

# the wallpaper: a dark teal fall-off (stretched to the screen), and apart the shelter's sign and name for its middle
# (kept square on a wide screen)
W, H = 1024, 768
wp = Image.new("RGBA", (W, H))
px = wp.load()
for y in range(H):
    for x in range(W):
        r = math.hypot((x - W / 2) / W, (y - H / 2) / H)
        k = max(0.0, 1.0 - r * 1.4)
        px[x, y] = (int(10 + 18 * k), int(34 + 40 * k), int(38 + 42 * k), 255)
save(wp, "laptop_wallpaper")

LW, LH = 400, 360
logo = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
d = ImageDraw.Draw(logo)
cx, cy, rad = LW // 2, 130, 120
faint = (70, 120, 124, 255)
d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=faint, width=6)
for k in range(3):  # a trefoil of the Zone, its blades
    a0 = math.radians(90 + k * 120)
    pts = [(cx, cy)]
    for s_ in range(-30, 31, 3):
        a = a0 + math.radians(s_)
        pts.append((cx + math.cos(a) * (rad - 22), cy - math.sin(a) * (rad - 22)))
    d.polygon(pts, fill=(52, 96, 100, 255))
d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(18, 50, 54, 255), outline=faint, width=4)
title = "У Б Е Ж И Щ Е"
f = font(40, True)
d.text((cx - d.textlength(title, font=f) / 2, cy + rad + 24), title, font=f, fill=faint)
sub = "Химик OS 98"
f2 = font(18)
d.text((cx - d.textlength(sub, font=f2) / 2, cy + rad + 76), sub, font=f2, fill=(56, 100, 104, 255))
save(logo, "laptop_logo")


# the shortcuts' icons, 64x64
def icon(draw_fn, name):
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(im))
    save(im, "laptop_icon_" + name)


def plan_icon(d):
    d.rectangle([6, 8, 58, 56], fill=(30, 80, 150, 255), outline=(10, 30, 70, 255), width=2)
    for v in range(12, 56, 8):
        d.line([(8, v), (56, v)], fill=(60, 110, 180, 255))
        d.line([(v, 10), (v, 54)], fill=(60, 110, 180, 255))
    for box in ((12, 14, 28, 30), (32, 14, 52, 26), (12, 34, 34, 50), (38, 30, 52, 50)):
        d.rectangle(box, outline=(220, 240, 255, 255), width=2)


def map_icon(d):
    d.polygon([(6, 14), (22, 8), (42, 14), (58, 8), (58, 52), (42, 58), (22, 52), (6, 58)], fill=(214, 196, 140, 255),
              outline=(90, 70, 40, 255))
    d.line([(22, 8), (22, 52)], fill=(150, 130, 90, 255), width=2)
    d.line([(42, 14), (42, 58)], fill=(150, 130, 90, 255), width=2)
    d.line([(10, 40), (20, 30), (30, 36), (44, 22), (54, 26)], fill=(110, 140, 80, 255), width=3)
    d.ellipse([34, 26, 46, 38], fill=(200, 40, 30, 255), outline=(90, 10, 10, 255))


def clean_icon(d):
    d.line([(46, 6), (24, 40)], fill=(130, 84, 40, 255), width=5)
    d.polygon([(16, 36), (32, 46), (24, 60), (6, 54)], fill=(220, 180, 70, 255), outline=(120, 90, 30, 255))
    for k in range(4):
        d.line([(10 + k * 5, 50 + k), (8 + k * 5, 58)], fill=(150, 110, 40, 255), width=2)
    d.ellipse([40, 44, 58, 58], fill=(140, 150, 160, 255), outline=(70, 80, 90, 255))  # a bucket's top


icon(plan_icon, "plan")
icon(map_icon, "map")
icon(clean_icon, "clean")


# the plan's marks, 16x16: the shelter's things and the players
def mark(draw_fn, name):
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(im))
    save(im, "laptop_mark_" + name)


mark(lambda d: (d.ellipse([1, 1, 14, 14], fill=(250, 210, 60, 255), outline=(60, 40, 0, 255)),
                d.polygon([(9, 3), (5, 9), (8, 9), (6, 13), (11, 7), (8, 7)], fill=(60, 40, 0, 255))), "generator")
mark(lambda d: (d.rectangle([2, 3, 13, 10], fill=(120, 200, 255, 255), outline=(20, 50, 80, 255)),
                d.rectangle([0, 11, 15, 13], fill=(160, 170, 180, 255))), "laptop")
mark(lambda d: (d.rectangle([1, 4, 14, 13], fill=(170, 120, 60, 255), outline=(70, 40, 10, 255)),
                d.line([(1, 8), (14, 8)], fill=(70, 40, 10, 255))), "stash")
mark(lambda d: (d.polygon([(6, 1), (10, 1), (10, 6), (14, 14), (2, 14), (6, 6)], fill=(110, 230, 160, 255),
                          outline=(20, 80, 50, 255))), "chamber")
mark(lambda d: d.ellipse([2, 2, 13, 13], fill=(90, 230, 90, 255), outline=(10, 60, 10, 255), width=2), "me")
mark(lambda d: d.ellipse([2, 2, 13, 13], fill=(90, 170, 250, 255), outline=(10, 40, 90, 255), width=2), "friend")
