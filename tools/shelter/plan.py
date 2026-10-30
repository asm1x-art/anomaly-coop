# The shelter's floor plan for the laptop (docs/coop/shelter.md, "План развития", phase 1): bunker_a1's walls cut a
# metre over the floor wherever it is (the entrance and the corridor ~3.3, the lower hall ~2.95, the water hall
# ~1.45), drawn as a dark blueprint (the laptop's colours) into a UI texture; where the world lies on it goes to
# configs\scripts\shelter\plan.ltx.
# Furniture and clutter are left out (the walls are the collision's tall faces).
#   plan.py <level dir>   -> gamedata\textures\ui\shelter\plan_main.dds, gamedata\configs\scripts\shelter\plan.ltx
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
X0, X1, Z0, Z1 = -10.0, 26.0, -32.0, 34.0  # the main floor's part the shelter has
S = 16  # px per metre
CELL = 0.25  # the floor raster's step (m)
CUTS = (2.45, 3.95, 4.3)  # a metre over each floor
WALL_SPAN = 1.0  # a face this tall at least is a wall, not a thing on the floor
BG, GRID, GRID5, WALL = (19, 21, 25, 255), (27, 30, 35, 255), (34, 38, 44, 255), (176, 214, 206, 255)

cf = open(os.path.join(sys.argv[1], "level.cform"), "rb").read()
_, vc, fc = struct.unpack_from("<III", cf, 0)
V = np.frombuffer(cf, "<f4", vc * 3, 36).reshape(vc, 3).astype(np.float64)
F = np.frombuffer(cf, "<u4", fc * 4, 36 + vc * 12).reshape(fc, 4)[:, :3].astype(np.int64)
T = V[F]
c = T.mean(1)
T = T[(c[:, 0] > X0 - 2) & (c[:, 0] < X1 + 2) & (c[:, 2] > Z0 - 2) & (c[:, 2] < Z1 + 2) & (c[:, 1] > -1) & (c[:, 1] < 9)]
N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)

# the floor under each cell: the highest upward face below 7.5 m
gw, gh = int((X1 - X0) / CELL) + 1, int((Z1 - Z0) / CELL) + 1
floor = np.full((gw, gh), np.nan)
for t in T[N[:, 1] > 0.7]:
    lo, hi = t.min(0), t.max(0)
    y = t[:, 1].mean()
    if y > 7.5:
        continue
    for i in range(max(int((lo[0] - X0) / CELL), 0), min(int((hi[0] - X0) / CELL), gw - 1) + 1):
        for j in range(max(int((lo[2] - Z0) / CELL), 0), min(int((hi[2] - Z0) / CELL), gh - 1) + 1):
            if np.isnan(floor[i, j]) or y > floor[i, j]:
                floor[i, j] = y


def floor_near(x, z, r=3):
    i, j = int((x - X0) / CELL), int((z - Z0) / CELL)
    a = floor[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
    return a[~np.isnan(a)]


W, H = int((X1 - X0) * S), int((Z1 - Z0) * S)
img = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(img)


def px(x, z):
    return ((x - X0) * S, (Z1 - z) * S)  # north up


for gx in range(int(X0), int(X1) + 1):
    d.line([px(gx, Z0), px(gx, Z1)], fill=GRID5 if gx % 5 == 0 else GRID)
for gz in range(int(Z0), int(Z1) + 1):
    d.line([px(X0, gz), px(X1, gz)], fill=GRID5 if gz % 5 == 0 else GRID)

walls = T[(np.abs(N[:, 1]) < 0.5) & (T[:, :, 1].max(1) - T[:, :, 1].min(1) >= WALL_SPAN)]
for h in CUTS:
    for t in walls:
        ty = t[:, 1]
        if ty.min() > h or ty.max() < h:
            continue
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (ty[a] - h) * (ty[b] - h) < 0:
                pts.append(t[a] + (h - ty[a]) / (ty[b] - ty[a]) * (t[b] - t[a]))
        if len(pts) != 2:
            continue
        m = (pts[0] + pts[1]) / 2
        fl = floor_near(m[0], m[2])
        if len(fl) and np.any(np.abs(fl - (h - 1.0)) < 0.45):
            d.line([px(pts[0][0], pts[0][2]), px(pts[1][0], pts[1][2])], fill=WALL, width=2)

tex = os.path.join(GAMEDATA, "textures", "ui", "shelter", "plan_main.dds")
os.makedirs(os.path.dirname(tex), exist_ok=True)
img.save(tex)
ltx = os.path.join(GAMEDATA, "configs", "scripts", "shelter", "plan.ltx")
with open(ltx, "w", newline="\r\n") as f:
    f.write("; written by tools\\shelter\\plan.py: the main floor's plan texture and the world's box on it (x to the right,\n"
            "; z up)\n[plan_main]\ntexture = ui\\shelter\\plan_main\n")
    f.write(f"width = {W}\nheight = {H}\nx0 = {X0}\nx1 = {X1}\nz0 = {Z0}\nz1 = {Z1}\n")
print(tex, (W, H), ltx)
