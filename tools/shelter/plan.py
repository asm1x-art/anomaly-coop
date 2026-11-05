# The shelter's floor plans for the laptop (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "План развития", phase 1): bunker_a1's walls cut a metre
# over the floor wherever it is, one texture a floor, drawn as a dark blueprint (the laptop's colours); where the world lies
# on each goes to configs\scripts\shelter\plan.ltx.
# Furniture and clutter are left out (the walls are the collision's tall faces).
#   plan.py <level dir>   -> gamedata\textures\ui\shelter\plan_<floor>.dds, gamedata\configs\scripts\shelter\plan.ltx
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
CELL = 0.25  # the floor raster's step (m)
WALL_SPAN = 1.0  # a face this tall at least is a wall, not a thing on the floor
BG, GRID, GRID5, WALL = (19, 21, 25, 255), (27, 30, 35, 255), (34, 38, 44, 255), (176, 214, 206, 255)
# each floor: the world's box, px per metre, the height it lies in, its cuts (a metre over each floor there): the middle
# floor has the entrance and the corridor ~3.3, the lower hall ~2.95, the water hall ~1.45
FLOORS = {
    "top": dict(box=(-6.0, 16.0, 6.0, 40.0), s=16, y=(17.0, 25.0), cuts=(20.2, 20.4)),
    "main": dict(box=(-10.0, 26.0, -32.0, 34.0), s=16, y=(-1.0, 9.0), cuts=(2.45, 3.95, 4.3)),
    "low": dict(box=(-104.0, 4.0, -16.0, 40.0), s=8, y=(-26.0, -10.0), cuts=(-20.6, -20.2, -19.8, -19.4, -19.0, -18.6, -18.2)),  # its floor rises westward
}

cf = open(os.path.join(sys.argv[1], "level.cform"), "rb").read()
_, vc, fc = struct.unpack_from("<III", cf, 0)
V = np.frombuffer(cf, "<f4", vc * 3, 36).reshape(vc, 3).astype(np.float64)
F = np.frombuffer(cf, "<u4", fc * 4, 36 + vc * 12).reshape(fc, 4)[:, :3].astype(np.int64)
ALL = V[F]


def draw(name, box, s, y, cuts):
    X0, X1, Z0, Z1 = box
    c = ALL.mean(1)
    T = ALL[(c[:, 0] > X0 - 2) & (c[:, 0] < X1 + 2) & (c[:, 2] > Z0 - 2) & (c[:, 2] < Z1 + 2) & (c[:, 1] > y[0]) & (c[:, 1] < y[1])]
    N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)

    # the floor under each cell: the highest upward face low enough to be a floor
    gw, gh = int((X1 - X0) / CELL) + 1, int((Z1 - Z0) / CELL) + 1
    floor = np.full((gw, gh), np.nan)
    ceiling_from = max(cuts) + 3.2
    for t in T[N[:, 1] > 0.7]:
        lo, hi = t.min(0), t.max(0)
        h = t[:, 1].mean()
        if h > ceiling_from:
            continue
        for i in range(max(int((lo[0] - X0) / CELL), 0), min(int((hi[0] - X0) / CELL), gw - 1) + 1):
            for j in range(max(int((lo[2] - Z0) / CELL), 0), min(int((hi[2] - Z0) / CELL), gh - 1) + 1):
                if np.isnan(floor[i, j]) or h > floor[i, j]:
                    floor[i, j] = h

    def floor_near(x, z, r=3):
        i, j = int((x - X0) / CELL), int((z - Z0) / CELL)
        a = floor[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
        return a[~np.isnan(a)]

    W, H = int((X1 - X0) * s), int((Z1 - Z0) * s)
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)

    def px(x, z):
        return ((x - X0) * s, (Z1 - z) * s)  # north up

    for gx in range(int(X0), int(X1) + 1):
        d.line([px(gx, Z0), px(gx, Z1)], fill=GRID5 if gx % 5 == 0 else GRID)
    for gz in range(int(Z0), int(Z1) + 1):
        d.line([px(X0, gz), px(X1, gz)], fill=GRID5 if gz % 5 == 0 else GRID)

    walls = T[(np.abs(N[:, 1]) < 0.5) & (T[:, :, 1].max(1) - T[:, :, 1].min(1) >= WALL_SPAN)]
    for h in cuts:
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

    tex = os.path.join(GAMEDATA, "textures", "ui", "shelter", f"plan_{name}.dds")
    os.makedirs(os.path.dirname(tex), exist_ok=True)
    img.save(tex)
    print(tex, (W, H))
    return f"[plan_{name}]\ntexture = ui\\shelter\\plan_{name}\nwidth = {W}\nheight = {H}\nx0 = {X0}\nx1 = {X1}\nz0 = {Z0}\nz1 = {Z1}\n"


parts = [draw(name, **f) for name, f in FLOORS.items()]
ltx = os.path.join(GAMEDATA, "configs", "scripts", "shelter", "plan.ltx")
with open(ltx, "w", newline="\r\n") as f:
    f.write("; written by tools\\shelter\\plan.py: each floor's plan texture and the world's box on it (x to the right, z up)\n")
    f.write("\n".join(parts))
print(ltx)
