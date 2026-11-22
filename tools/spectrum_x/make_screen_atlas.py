r"""Spectrum-X device screen atlas: the glyphs and shapes the 3D screen (ui_spectrum_x.script) is drawn with.
  python tools/spectrum_x/make_screen_atlas.py [--tools H:\stalker-test\tools-ext] [--png <preview.png>]
The screen hangs on the tablet bone through the engine's custom_ui_func (CHudItem's script 3D UI). A text window
(CGameFont) is not drawn there: fonts are put out later in screen space. So every letter is a textured static, cut
out of this atlas by its texture rect.

Writes:
  gamedata/textures/ui/ui_spectrum_x_screen.dds   1024 x 1024 B8G8R8A8 (no compression: crisp edges), full mips;
                                                  white on transparent, the script tints each part
  gamedata/configs/misc/spectrum_x_glyphs.ltx     each glyph's advance (cp1251 32..255), read by the script
Layout (pixels):
  glyphs   cells of 64 x 64, 16 a row, cp1251 code 32 at the top left, rows 0..13 (y 0..895); the pen sits PAD px
           into the cell, the baseline at BASE px from its top
  shapes   64 x 64 at y 896 and 960 (SHAPES below), 128 x 128 at y 896, x 512.. (BIG below)
Font: Bahnschrift SemiBold (Windows), a DIN-like instrument face with Cyrillic."""
import argparse, os, shutil, subprocess, sys, math
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--tools", default=r"H:\stalker-test\tools-ext")
ap.add_argument("--font", default=r"C:\Windows\Fonts\bahnschrift.ttf")
ap.add_argument("--work", default=r"X:\coop\assets\spectrum-x\hud\tex")
ap.add_argument("--png", default=None, help="also save a preview png here")
a = ap.parse_args()
TEXCONV = os.path.join(a.tools, "texconv", "texconv.exe")

SIZE, CELL, PAD, BASE, FONT_PX = 1024, 64, 6, 48, 46
SS = 4   # shapes are drawn this much bigger, then scaled down (smooth edges)
SHAPES = ["solid", "disc", "ring", "diamond", "tri_up", "tri_down", "target", "chevron",      # y 896
          "glow", "battery", "speaker", "speaker_off", "plus", "box", "bar_v", "dot_small"]   # y 960
BIG = ["radar", "cone"]                                                                      # 128 x 128, y 896, x 512..

img = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
font = ImageFont.truetype(a.font, FONT_PX)
font.set_variation_by_name(b"SemiBold")
asc, desc = font.getmetrics()
adv = []
for code in range(32, 256):
    i = code - 32; cx, cy = (i % 16) * CELL, (i // 16) * CELL
    try:
        ch = bytes([code]).decode("cp1251")
    except UnicodeDecodeError:
        adv.append(0.0); continue
    if code in (0x98, 0xAD) or not ch.isprintable():
        adv.append(0.0 if code != 0xA0 else font.getlength(" ") / CELL); continue
    cell = Image.new("L", (CELL, CELL), 0)
    ImageDraw.Draw(cell).text((PAD, BASE), ch, font=font, fill=255, anchor="ls")
    img.paste(Image.new("RGBA", (CELL, CELL), (255, 255, 255, 255)), (cx, cy), cell)
    adv.append(font.getlength(ch) / CELL)


def shape(name, n):
    """one shape, n px square, as an L mask"""
    S = n * SS; m = Image.new("L", (S, S), 0); d = ImageDraw.Draw(m); c = S / 2; u = S / 64
    if name == "solid":
        d.rectangle([0, 0, S, S], fill=255)
    elif name == "disc":
        d.ellipse([u * 2, u * 2, S - u * 2, S - u * 2], fill=255)
    elif name == "ring":
        d.ellipse([u * 4, u * 4, S - u * 4, S - u * 4], outline=255, width=int(u * 7))
    elif name == "diamond":
        d.polygon([(c, u * 3), (S - u * 3, c), (c, S - u * 3), (u * 3, c)], fill=255)
    elif name == "tri_up":
        d.polygon([(c, u * 6), (S - u * 5, S - u * 10), (u * 5, S - u * 10)], fill=255)
    elif name == "tri_down":
        d.polygon([(u * 5, u * 10), (S - u * 5, u * 10), (c, S - u * 6)], fill=255)
    elif name == "target":
        d.ellipse([u * 4, u * 4, S - u * 4, S - u * 4], outline=255, width=int(u * 6))
        d.ellipse([c - u * 11, c - u * 11, c + u * 11, c + u * 11], fill=255)
    elif name == "chevron":
        d.polygon([(c, u * 4), (S - u * 8, S - u * 6), (c, S - u * 20), (u * 8, S - u * 6)], fill=255)
    elif name == "glow":
        for r in range(int(c), 0, -SS):
            v = int(255 * (1 - r / c) ** 2)
            d.ellipse([c - r, c - r, c + r, c + r], fill=v)
    elif name == "battery":
        d.rounded_rectangle([u * 4, u * 18, S - u * 12, S - u * 18], radius=u * 5, outline=255, width=int(u * 5))
        d.rectangle([S - u * 12, u * 26, S - u * 5, S - u * 26], fill=255)
    elif name in ("speaker", "speaker_off"):
        d.polygon([(u * 6, u * 24), (u * 18, u * 24), (u * 32, u * 10), (u * 32, S - u * 10), (u * 18, S - u * 24),
                   (u * 6, S - u * 24)], fill=255)
        if name == "speaker":
            for r in (14, 24):
                d.arc([u * 32 - u * r, c - u * r, u * 32 + u * r, c + u * r], -45, 45, fill=255, width=int(u * 5))
        else:
            d.line([(u * 40, u * 22), (u * 58, S - u * 22)], fill=255, width=int(u * 6))
            d.line([(u * 58, u * 22), (u * 40, S - u * 22)], fill=255, width=int(u * 6))
    elif name == "plus":
        d.rectangle([c - u * 4, u * 8, c + u * 4, S - u * 8], fill=255)
        d.rectangle([u * 8, c - u * 4, S - u * 8, c + u * 4], fill=255)
    elif name == "box":
        d.rectangle([u * 6, u * 6, S - u * 6, S - u * 6], outline=255, width=int(u * 6))
    elif name == "bar_v":
        d.rectangle([c - u * 3, 0, c + u * 3, S], fill=255)
    elif name == "dot_small":
        d.ellipse([c - u * 9, c - u * 9, c + u * 9, c + u * 9], fill=255)
    elif name == "radar":   # rings at 1/3, 2/3 and the edge, a faint cross and ticks every 30 degrees
        w = int(u * 1.6)
        for k, alpha in ((1.0, 255), (2 / 3, 150), (1 / 3, 150)):
            r = (c - u * 2) * k
            d.ellipse([c - r, c - r, c + r, c + r], outline=alpha, width=w)
        d.line([(c, u * 2), (c, S - u * 2)], fill=70, width=w); d.line([(u * 2, c), (S - u * 2, c)], fill=70, width=w)
        for deg in range(0, 360, 30):
            t = math.radians(deg); r0, r1 = c - u * 2, c - u * 6
            d.line([(c + r0 * math.sin(t), c - r0 * math.cos(t)), (c + r1 * math.sin(t), c - r1 * math.cos(t))], fill=255, width=w)
    elif name == "cone":    # the view: a 70 degree wedge up from the centre, fading out
        steps = 48
        for s in range(steps, 0, -1):
            r = (c - u * 2) * s / steps
            d.pieslice([c - r, c - r, c + r, c + r], -90 - 35, -90 + 35, fill=int(110 * (1 - s / steps) + 10))
    return m.resize((n, n), Image.LANCZOS)


for i, name in enumerate(SHAPES):
    x, y = (i % 8) * CELL, 896 + (i // 8) * CELL
    msk = shape(name, CELL)
    img.paste(Image.new("RGBA", (CELL, CELL), (255, 255, 255, 255)), (x, y), msk)
for i, name in enumerate(BIG):
    x, y = 512 + i * 128, 896
    msk = shape(name, 128)
    img.paste(Image.new("RGBA", (128, 128), (255, 255, 255, 255)), (x, y), msk)

os.makedirs(a.work, exist_ok=True)
png = os.path.join(a.work, "ui_spectrum_x_screen.png")
img.save(png)
if a.png:
    prev = Image.new("RGBA", img.size, (24, 26, 30, 255)); prev.alpha_composite(img); prev.save(a.png)
out_dir = os.path.join(ROOT, "gamedata", "textures", "ui")
r = subprocess.run([TEXCONV, "-nologo", "-y", "-dx9", "-m", "0", "-f", "B8G8R8A8_UNORM", "--ignore-srgb", "-o", a.work, png],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit("texconv failed:\n" + r.stdout + r.stderr)
shutil.move(os.path.join(a.work, "ui_spectrum_x_screen.dds"), os.path.join(out_dir, "ui_spectrum_x_screen.dds"))

ltx = os.path.join(ROOT, "gamedata", "configs", "misc", "spectrum_x_glyphs.ltx")
os.makedirs(os.path.dirname(ltx), exist_ok=True)
with open(ltx, "w", encoding="ascii", newline="\r\n") as f:
    f.write("; Spectrum-X screen font: written by tools/spectrum_x/make_screen_atlas.py, do not edit by hand.\n")
    f.write("; Atlas ui\\ui_spectrum_x_screen: cells of %d px, 16 a row from cp1251 code 32; pen %d px into a cell,\n" % (CELL, PAD))
    f.write("; baseline %d px down. adv = each code's advance (32..255) in cell heights.\n\n" % BASE)
    f.write("[spectrum_x_glyphs]\n")
    f.write("size = %d\ncell = %d\npad = %d\nbase = %d\n" % (SIZE, CELL, PAD, BASE))
    f.write("adv = %s\n" % ", ".join("%.3f" % v for v in adv))
    f.write("shapes = %s\n" % ", ".join(SHAPES))
    f.write("big = %s\n" % ", ".join(BIG))
print("atlas", png, "glyph metrics asc/desc", asc, desc)
