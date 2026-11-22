"""Spectrum-X tablet prints (front and back), RGBA over the tablet's coords (BOX of tablet_dims.py): button glyphs,
the yellow radiation sign, the maker's marks. Run by make_tablet.py:  python tablet_prints.py <out_dir>"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tablet_dims import *
OUT = sys.argv[1]
from PIL import Image, ImageDraw, ImageFont
PW, PH = int((BOX[3] - BOX[2]) * PPM), int((BOX[1] - BOX[0]) * PPM)
FONT = r"C:\Windows\Fonts\bahnschrift.ttf"
INK = (206, 208, 204, 255); YEL = (236, 190, 30, 255); BLK = (16, 16, 15, 255)


def px(x, y):
    return ((y - BOX[2]) * PPM, (x - BOX[0]) * PPM)


def font(h_m, wt="bold"):
    f = ImageFont.truetype(FONT, int(h_m * PPM))
    try: f.set_variation_by_name(wt.capitalize() if wt != "semibold" else "SemiBold")
    except Exception: pass
    return f


def text(d, x, y, s, h_m, fill=INK, wt="bold", anchor="mm"):
    cx, cy = px(x, y); d.text((cx, cy), s, font=font(h_m, wt), fill=fill, anchor=anchor)


def rad_sign(d, x, y, size):
    """clean yellow triangle, black rim and trefoil"""
    cx, cy = px(x, y); S = size * PPM
    tri = lambda k: [(cx + S * k * math.cos(math.radians(90 + i * 120)), cy - S * k * math.sin(math.radians(90 + i * 120)) + S * 0.12) for i in range(3)]
    d.polygon(tri(1.0), fill=BLK); d.polygon(tri(0.84), fill=YEL)
    ty = cy + S * 0.16; R1, R0 = S * 0.34, S * 0.075
    for th in (30, 150, 270):          # blades centred at these angles (counter-clockwise from +x; PIL turns clockwise)
        d.pieslice((cx - R1, ty - R1, cx + R1, ty + R1), start=-(th + 30), end=-(th - 30), fill=BLK)
    d.ellipse((cx - R0 * 1.8, ty - R0 * 1.8, cx + R0 * 1.8, ty + R0 * 1.8), fill=YEL)
    d.ellipse((cx - R0, ty - R0, cx + R0, ty + R0), fill=BLK)


front = Image.new("RGBA", (PW, PH), (0, 0, 0, 0)); d = ImageDraw.Draw(front)
for nm, s in (("p1", "P1"), ("p2", "P2")):
    x, y, _ = BUTTONS[nm]; text(d, x, y, s, 0.0052)
for nm in ("plus", "minus"):           # drawn as bars (the font has no minus sign)
    x, y, _ = BUTTONS[nm]; cx, cy = px(x, y); L = 0.0023 * PPM; lw = int(0.0007 * PPM)
    d.line((cx - L, cy, cx + L, cy), fill=INK, width=lw)
    if nm == "plus": d.line((cx, cy - L, cx, cy + L), fill=INK, width=lw)
# power glyph: an open ring and a bar
x, y, _ = BUTTONS["power"]; cx, cy = px(x, y); R = 0.0026 * PPM; lw = int(0.0006 * PPM)
d.arc((cx - R, cy - R, cx + R, cy + R), start=-50, end=230, fill=INK, width=lw)
d.line((cx, cy - R * 1.25, cx, cy - R * 0.15), fill=INK, width=lw)
# small marks on the bezels: a power LED ring, the row labels, the maker's marks, the sign
text(d, -0.0515, -0.058, "AEGIS", 0.0036, wt="bold", anchor="lm")
text(d, -0.0515, -0.0435, "BIO", 0.0036, wt="light", anchor="lm")
text(d, BTN_X[1] + 0.0105, -BTN_Y, "PROFILE", 0.0019, wt="semibold")
text(d, BTN_X[1] + 0.0105, BTN_Y, "LEVEL", 0.0019, wt="semibold")
rad_sign(d, 0.0497, -0.040, 0.0062)
text(d, 0.0505, -0.023, "SPECTRUM-X", 0.0043, wt="bold", anchor="lm")
text(d, 0.0505, 0.022, "GAMMA \u00b7 PSI \u00b7 ANOMALOUS", 0.0021, wt="semibold", anchor="lm")
text(d, -0.0515, 0.030, "AG-SX 2.1", 0.0024, wt="semibold", anchor="lm")
cx, cy = px(-0.0515, 0.058); R = 0.0011 * PPM
d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=(60, 160, 90, 255))
back = Image.new("RGBA", (PW, PH), (0, 0, 0, 0)); d = ImageDraw.Draw(back)
# the back: drawn as seen from behind (make_tablet.py mirrors its y when it lays it on)
plate = [px(-0.020, -0.040), px(0.020, 0.040)]
d.rounded_rectangle((plate[0][0], plate[0][1], plate[1][0], plate[1][1]), radius=0.002 * PPM, fill=(40, 41, 44, 255), outline=(120, 122, 124, 255), width=int(0.0003 * PPM))
text(d, -0.012, 0.0, "AEGIS-BIO  RESEARCH INSTRUMENTS", 0.0030)
text(d, -0.004, 0.0, "SPECTRUM-X  FIELD SPECTROMETER", 0.0030, wt="semibold")
text(d, 0.004, 0.0, "S/N  AX-0471-K   7.4 V   IP67", 0.0024, wt="light")
rad_sign(d, 0.013, -0.028, 0.0045)
text(d, 0.0135, 0.006, "DO NOT OPEN IN THE FIELD", 0.0022, wt="semibold")
front.save(os.path.join(OUT, "print_front.png")); back.save(os.path.join(OUT, "print_back.png")); print("prints", front.size)


