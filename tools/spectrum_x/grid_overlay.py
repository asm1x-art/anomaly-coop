"""Draw a labelled 0.05 grid over an ortho render made by ortho_grid.py (ortho_scale 1.1, centre 0).
python grid_overlay.py in.png out.png <h-axis label> <v-axis label> [hsign vsign]"""
import sys
from PIL import Image, ImageDraw
im = Image.open(sys.argv[1]).convert("RGB"); W, H = im.size
hs = float(sys.argv[5]) if len(sys.argv) > 5 else 1; vs = float(sys.argv[6]) if len(sys.argv) > 6 else 1
dr = ImageDraw.Draw(im); s = W / 1.1
for i in range(-11, 12):
    v = i * 0.05; x = W / 2 + v * s; y = H / 2 - v * s
    c = (255, 60, 60) if i % 2 == 0 else (90, 90, 90)
    dr.line([(x, 0), (x, H)], fill=c, width=1); dr.line([(0, y), (W, y)], fill=c, width=1)
    if i % 2 == 0:
        dr.text((x + 2, 2), "%s%+.1f" % (sys.argv[3], v * hs), fill=(255, 255, 0))
        dr.text((2, y + 2), "%s%+.1f" % (sys.argv[4], v * vs), fill=(255, 255, 0))
im.save(sys.argv[2])
