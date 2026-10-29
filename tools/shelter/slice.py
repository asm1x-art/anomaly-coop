# Plan view of the level's collision around an opening: wall cuts at a few heights above its floor, drawn in the
# opening's local frame (+z into the opening, +x to the right), plus floor heights on a grid.
#   slice.py <level dir> <x> <y> <z> <fx> <fz> <out.png>
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

level_dir = sys.argv[1]
ox, oy, oz, fx, fz = map(float, sys.argv[2:7])
out = sys.argv[7]
O = np.array([ox, oy, oz])
F = np.array([fx, 0.0, fz]); F /= np.linalg.norm(F)
R = np.array([F[2], 0.0, -F[0]])

data = open(level_dir + '/level.cform', 'rb').read()
_, vc, fc = struct.unpack_from('<III', data, 0)
verts = np.frombuffer(data, dtype='<f4', count=vc * 3, offset=36).reshape(vc, 3).astype(np.float64)
faces = np.frombuffer(data, dtype='<u4', count=fc * 4, offset=36 + vc * 12).reshape(fc, 4)[:, :3]
T = verts[faces]
T = T[np.linalg.norm(T.mean(1) - O, axis=1) < 15]
L = np.stack([(T - O) @ R, T[..., 1] - O[1], (T - O) @ F], -1)   # local x, y, z

K, X0, X1, Z0, Z1 = 80, -5.0, 5.0, -5.0, 2.0
img = Image.new('RGB', (int((X1 - X0) * K), int((Z1 - Z0) * K)), (20, 20, 24))
d = ImageDraw.Draw(img)


def px(x, z):
    return (x - X0) * K, (Z1 - z) * K


for g in np.arange(np.ceil(X0), X1 + 0.01, 0.5):
    d.line([px(g, Z0), px(g, Z1)], fill=(45, 45, 50) if g % 1 else (70, 70, 80))
for g in np.arange(np.ceil(Z0), Z1 + 0.01, 0.5):
    d.line([px(X0, g), px(X1, g)], fill=(45, 45, 50) if g % 1 else (70, 70, 80))
d.line([px(0, Z0), px(0, Z1)], fill=(90, 90, 140))
d.line([px(X0, 0), px(X1, 0)], fill=(90, 90, 140))

for h, colour in ((0.15, (255, 120, 80)), (1.0, (255, 230, 90)), (2.5, (110, 220, 255))):
    for tri in L:
        s = tri[:, 1] - h
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (s[a] > 0) != (s[b] > 0):
                t = s[a] / (s[a] - s[b])
                p = tri[a] + (tri[b] - tri[a]) * t
                pts.append((p[0], p[2]))
        if len(pts) == 2:
            d.line([px(*pts[0]), px(*pts[1])], fill=colour, width=2)
d.text((8, 8), 'cuts above the floor: red 0.15, yellow 1.0, blue 2.5 m; grid 0.5 m; +z into the opening', fill=(220, 220, 220))
img.save(out)
