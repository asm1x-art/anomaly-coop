# The stone a synthesis chamber makes of a load that's no recipe (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Алхимия"): a lump of fused
# concrete-grey matter, about 15 cm, its model and its inventory icon (a 50 px cell, drawn from the model).
#   synth_stone.py   -> gamedata\meshes\dynamics\shelter\synth_stone.ogf, gamedata\textures\ui\shelter\synth_stone.dds
import os

import numpy as np
from PIL import Image

import ogf

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
MODEL = os.path.join(GAME, "meshes", "dynamics", "shelter", "synth_stone.ogf")
ICON = os.path.join(GAME, "textures", "ui", "shelter", "synth_stone.dds")

RADIUS = 0.075
SQUASH = 0.72  # its height to its width
TEXTURE = "crete\\crete_debris_01"
UV_SIZE = 0.35  # m of the stone over the texture's width
MASS = 1.4
rnd = np.random.default_rng(62)


def icosphere(levels):
    t = (1 + 5 ** 0.5) / 2
    P = [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t],
         [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]
    F = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6],
         [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10],
         [8, 6, 7], [9, 8, 1]]
    P = [np.array(p, float) / np.linalg.norm(p) for p in P]
    for _ in range(levels):
        mid, F2 = {}, []

        def m(a, b):
            k = (min(a, b), max(a, b))
            if k not in mid:
                v = P[a] + P[b]
                P.append(v / np.linalg.norm(v))
                mid[k] = len(P) - 1
            return mid[k]

        for a, b, c in F:
            ab, bc, ca = m(a, b), m(b, c), m(c, a)
            F2 += [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]]
        F = F2
    return np.array(P), np.array(F)


# the lump: a sphere pushed in and out by a few broad bumps and many small ones, squashed
D, F = icosphere(2)
r = np.ones(len(D))
for count, size, depth in ((6, 0.9, 0.3), (18, 0.45, 0.15), (40, 0.25, 0.07)):
    for _ in range(count):
        c = rnd.normal(size=3)
        c /= np.linalg.norm(c)
        r += rnd.uniform(-1, 1) * depth * np.exp(-((1 - D @ c) / (size * size)) * 2)
P = D * r[:, None] * RADIUS
P[:, 1] *= SQUASH
P[:, 1] -= P[:, 1].min()  # its origin under it
# smooth normals
N = np.zeros_like(P)
for a, b, c in F:
    n = np.cross(P[b] - P[a], P[c] - P[a])
    N[[a, b, c]] += n
N /= np.linalg.norm(N, axis=1)[:, None]

# a vertex per corner, the texture laid on each triangle along its face's main axis
fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
axis = np.abs(fn).argmax(1)
VP, VN, VUV = P[F].reshape(-1, 3), N[F].reshape(-1, 3), np.zeros((len(F) * 3, 2))
for i, ax in enumerate(axis):
    u, v = [k for k in range(3) if k != ax]
    VUV[i * 3:i * 3 + 3] = P[F[i]][:, [u, v]] / UV_SIZE + 0.5
I = np.arange(len(F) * 3).reshape(-1, 3)

lo, hi = P.min(0), P.max(0)
os.makedirs(os.path.dirname(MODEL), exist_ok=True)
size = ogf.write(MODEL, [(TEXTURE, VP, VN, VUV, I)], [((lo + hi) / 2, (hi - lo) / 2 * 0.9, MASS)], "shelter synth stone",
                 "objects\\concrete_box")
print(f"{MODEL}: {size} bytes, {(hi - lo) * 100} cm")

# the icon: the stone seen from the front and a little above, lit from the upper left, in a 50 px cell of a 64 px texture
CELL, TEX = 50, 64
yaw, pitch = np.radians(25), np.radians(-28)
Ry = np.array([[np.cos(yaw), 0, np.sin(yaw)], [0, 1, 0], [-np.sin(yaw), 0, np.cos(yaw)]])
Rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
R = Rx @ Ry
Q = (P - (lo + hi) / 2) @ R.T
NQ = N @ R.T
scale = (CELL - 6) / (Q[:, :2].max(0) - Q[:, :2].min(0)).max()
X = Q[:, 0] * scale
Y = -Q[:, 1] * scale
X += CELL / 2 - (X.min() + X.max()) / 2
Y += CELL / 2 - (Y.min() + Y.max()) / 2
Z = Q[:, 2]
light = np.array([-0.5, 0.6, -0.65])
light /= np.linalg.norm(light)
img = np.zeros((TEX, TEX, 4))
zbuf = np.full((TEX, TEX), np.inf)
speck = rnd.uniform(0.85, 1.12, size=(TEX, TEX))
for a, b, c in F:
    xs, ys = X[[a, b, c]], Y[[a, b, c]]
    x0, x1 = int(np.floor(xs.min())), int(np.ceil(xs.max()))
    y0, y1 = int(np.floor(ys.min())), int(np.ceil(ys.max()))
    den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
    if abs(den) < 1e-9:
        continue
    for py in range(max(0, y0), min(CELL, y1 + 1)):
        for px in range(max(0, x0), min(CELL, x1 + 1)):
            cx, cy = px + 0.5, py + 0.5
            w0 = ((ys[1] - ys[2]) * (cx - xs[2]) + (xs[2] - xs[1]) * (cy - ys[2])) / den
            w1 = ((ys[2] - ys[0]) * (cx - xs[2]) + (xs[0] - xs[2]) * (cy - ys[2])) / den
            w2 = 1 - w0 - w1
            if min(w0, w1, w2) < -1e-6:
                continue
            z = w0 * Z[a] + w1 * Z[b] + w2 * Z[c]
            if z >= zbuf[py, px]:
                continue
            zbuf[py, px] = z
            n = w0 * NQ[a] + w1 * NQ[b] + w2 * NQ[c]
            n /= np.linalg.norm(n)
            lit = 0.28 + 0.72 * max(0.0, float(n @ light))
            base = np.array([104, 98, 90]) * lit * speck[py, px]
            img[py, px] = [*np.clip(base, 0, 255), 255]
os.makedirs(os.path.dirname(ICON), exist_ok=True)
Image.fromarray(img.astype(np.uint8), "RGBA").save(ICON)
print(ICON)
