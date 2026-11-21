r"""Flat before | after sheet of the reworked textures: vanilla (as the game shows it, stretched to the same size),
the new one, the new bump's normal (as a usual RGB normal map) and a close-up crop of both, with names and sizes.
  python tools/artifact_textures/sheet.py --out X:\artifact-fx\textures_pilot\textures_flat.png
"""
import argparse
import configparser
import os
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--src", default=r"X:\yantar-tools\work\gamedata\textures")
ap.add_argument("--new", default=os.path.join(ROOT, "gamedata", "textures"))
ap.add_argument("--out", required=True)
ap.add_argument("--cell", type=int, default=420)
a = ap.parse_args()


def info(p):
    h = open(p, "rb").read(128)
    height, width = struct.unpack_from("<II", h, 12)
    return "%dx%d %s mips %d" % (width, height, h[84:88].decode(), struct.unpack_from("<I", h, 28)[0])


def load(p):
    im = Image.open(p)
    im.load()
    return im.convert("RGBA")


def on_checker(im, size, resample):
    im = im.resize((size, size), resample)
    bg = Image.new("RGBA", im.size, (90, 90, 90, 255))
    d = ImageDraw.Draw(bg)
    for y in range(0, size, 16):
        for x in range(0, size, 16):
            if (x + y) // 16 % 2:
                d.rectangle([x, y, x + 15, y + 15], fill=(60, 60, 60, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


font = ImageFont.truetype("arial.ttf", 22)
small = ImageFont.truetype("arial.ttf", 16)
ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
ini.optionxform = str
ini.read(os.path.join(HERE, "textures.ini"), encoding="utf-8")
C = a.cell
cols = ["before (vanilla)", "after", "after: bump normal", "close-up before", "close-up after"]
rows = ini.sections()
W, H = C * len(cols) + 10 * (len(cols) + 1), 40 + len(rows) * (C + 70)
sheet = Image.new("RGB", (W, H), (24, 24, 28))
d = ImageDraw.Draw(sheet)
for i, c in enumerate(cols):
    d.text((10 + i * (C + 10), 8), c, font=font, fill=(230, 230, 230))
for r, name in enumerate(rows):
    rel = name.replace("\\", os.sep)
    y = 40 + r * (C + 70)
    old_p, new_p = os.path.join(a.src, rel + ".dds"), os.path.join(a.new, rel + ".dds")
    old, new = load(old_p), load(new_p)
    cells = [on_checker(old, C, Image.NEAREST), on_checker(new, C, Image.LANCZOS)]
    bump_p = os.path.join(a.new, rel + "_bump.dds")
    if os.path.exists(bump_p):
        b = np.asarray(load(bump_p))
        cells.append(Image.fromarray(np.dstack([b[..., 3], b[..., 2], b[..., 1]])).resize((C, C), Image.LANCZOS))
    else:
        cells.append(Image.new("RGB", (C, C), (40, 40, 44)))
    # a quarter of the texture, the same area from both
    q = lambda im: im.crop((0, 0, im.width // 4, im.height // 4))
    cells += [on_checker(q(old), C, Image.NEAREST), on_checker(q(new), C, Image.LANCZOS)]
    for i, im in enumerate(cells):
        sheet.paste(im, (10 + i * (C + 10), y + 52))
    users = ini[name].get("users", "")
    d.text((10, y + 6), "%s   %s  ->  %s" % (name, info(old_p), info(new_p)), font=font, fill=(255, 210, 120))
    d.text((10, y + 32), "used by: " + users, font=small, fill=(180, 180, 190))
os.makedirs(os.path.dirname(a.out), exist_ok=True)
sheet.save(a.out)
print(a.out)
