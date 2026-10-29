# Generates a rubble mound that closes a bunker opening: an .ogf rigid skeleton laid out like
# dynamics\large_trash\aes_zabor (children: type 4 meshes with one slide window; bones: names + IK data),
# a heightfield slope of broken concrete with chunks in it, and box bones for collision.
# Local frame: origin on the floor at the opening's face, +z into the opening, +x to the right of it.
#   mound.py <level dir> <out.ogf> [seed]
import math
import struct
import sys

import numpy as np

level_dir, out = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(int(sys.argv[3]) if len(sys.argv) > 3 else 7)

# ---- point 2: a 1.80 x 2.76 doorway, 0.80 deep, in the hall's south wall; the hall's west wall at local x 2.19,
# a box on the wall at x -2.1 .. -1.5 (slice_2.png)
ORIGIN = np.array([-2.911, 2.95, -16.43])     # world: hall floor at the wall, doorway centre
FORWARD = np.array([0.0, 0.0, -1.0])           # world: into the doorway
DOOR_HALF, DOOR_TOP, DOOR_DEPTH = 0.90, 2.76, 0.80
WEST_X = 2.19

# The pile stands in the doorway and leans out of it steeply, so it takes little of the hall.
TOP = 2.80           # crest, a little into the lintel
CREST_Z = 0.30       # the crest's line inside the doorway
CREST_HALF = 0.70
K = 1.9              # slope all round, 62 degrees
CELL_X, CELL_Z = 0.40, 0.35    # collision columns
GAP = 0.04           # collision boxes keep clear of the level: nothing pushes them before they freeze

FORWARD /= np.linalg.norm(FORWARD)
RIGHT = np.array([FORWARD[2], 0.0, -FORWARD[0]])


# ---- heightfield
waves = [(rng.uniform(0, 2 * math.pi), 2 * math.pi / rng.uniform(0.4, 1.5), rng.uniform(0, 2 * math.pi),
          rng.uniform(0.01, 0.03)) for _ in range(12)]
bumps = [(rng.uniform(-2.2, 2.2), rng.uniform(-1.4, 0.3), rng.uniform(0.15, 0.4), rng.uniform(-0.08, 0.14)) for _ in range(30)]


def base_height(x, z):
    return TOP - K * np.hypot(np.maximum(np.abs(x) - CREST_HALF, 0.0), np.maximum(CREST_Z - z, 0.0))


def height(x, z):
    h = base_height(x, z)
    for ang, k, ph, amp in waves:
        h = h + amp * np.sin(k * (x * math.cos(ang) + z * math.sin(ang)) + ph)
    for bx, bz, r, a in bumps:
        h = h + a * np.exp(-((x - bx) ** 2 + (z - bz) ** 2) / (r * r))
    return h


class Mesh:
    def __init__(self, texture):
        self.texture = texture
        self.P, self.N, self.UV, self.I = [], [], [], []

    def add(self, P, N, UV, I):
        base = sum(len(p) for p in self.P)
        self.P.append(np.asarray(P, float)); self.N.append(np.asarray(N, float)); self.UV.append(np.asarray(UV, float))
        self.I.append(np.asarray(I, np.int64) + base)

    def arrays(self):
        return np.concatenate(self.P), np.concatenate(self.N), np.concatenate(self.UV), np.concatenate(self.I)


THETA = math.atan(K)
SLOPE_DIR = np.array([0.0, math.sin(THETA), math.cos(THETA)])

ground = Mesh('crete\\crete_beton_lom')
STEP = 0.06
xs = np.arange(-2.8, 2.8 + 1e-6, STEP)
zs = np.arange(-1.8, 0.7 + 1e-6, STEP)
X, Z = np.meshgrid(xs, zs, indexing='ij')
H = height(X, Z)
H = np.where(H > 0, H, -0.06)
dhdx, dhdz = np.gradient(H, STEP, STEP)
N = np.stack([-dhdx, np.ones_like(H), -dhdz], -1)
N /= np.linalg.norm(N, axis=-1, keepdims=True)
P = np.stack([X, H, Z], -1)
UV = np.stack([X / 2.0, (P @ SLOPE_DIR) / 2.0], -1)
nx, nz = X.shape
idx = np.arange(nx * nz).reshape(nx, nz)
tris = []
for i in range(nx - 1):
    for j in range(nz - 1):
        a, b, c, d = idx[i, j], idx[i, j + 1], idx[i + 1, j], idx[i + 1, j + 1]
        if max(H[i, j], H[i, j + 1], H[i + 1, j], H[i + 1, j + 1]) <= 0:
            continue    # flat under the floor
        tris += [(a, b, c), (c, b, d)]
ground.add(P.reshape(-1, 3), N.reshape(-1, 3), UV.reshape(-1, 2), tris)
# the back, seen only from behind the doorway: a wall down to the floor
back = [(x, H[i, -1]) for i, x in enumerate(xs) if H[i, -1] > 0]
zb = zs[-1]
for (x0, h0), (x1, h1) in zip(back, back[1:]):
    ground.add([(x0, h0, zb), (x1, h1, zb), (x0, -0.06, zb), (x1, -0.06, zb)], [(0, 0, 1)] * 4,
               [(x0 / 2, h0 / 2), (x1 / 2, h1 / 2), (x0 / 2, 0), (x1 / 2, 0)], [(0, 2, 1), (1, 2, 3)])


# ---- chunks of concrete half buried in the slope
def rot(yaw, pitch, roll):
    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return ry @ rx @ rz


chunks = Mesh('crete\\crete_debris_01')
QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def add_chunk(centre, size, R):
    corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)], float) * size / 2
    corners *= rng.uniform(0.65, 1.15, corners.shape)
    corners = corners @ R.T + centre
    off = rng.uniform(0, 1, 2)
    for q in QUADS:
        for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            p = corners[list(t)]
            n = np.cross(p[1] - p[0], p[2] - p[0])
            if np.dot(n, p.mean(0) - centre) < 0:
                p = p[[0, 2, 1]]; n = -n
            n /= np.linalg.norm(n)
            a = np.cross(n, [0, 1, 0] if abs(n[1]) < 0.9 else [1, 0, 0]); a /= np.linalg.norm(a)
            b = np.cross(n, a)
            chunks.add(p, [n] * 3, [(np.dot(v, a) / 1.2 + off[0], np.dot(v, b) / 1.2 + off[1]) for v in p], [(0, 1, 2)])


def place(count, sizes, flat, tilt):
    done = 0
    while done < count:
        x, z = rng.uniform(-2.4, 2.1), rng.uniform(-1.4, 0.2)
        h = height(x, z)
        if h < 0.15:
            continue
        size = np.array([rng.uniform(*sizes), rng.uniform(*sizes), rng.uniform(*sizes)])
        if flat:
            size[1] = rng.uniform(0.22, 0.32)
        pitch = (-THETA if tilt else 0.0) + rng.uniform(-0.5, 0.5)
        R = rot(rng.uniform(-0.6, 0.6) if tilt else rng.uniform(0, 2 * math.pi), pitch, rng.uniform(-0.5, 0.5))
        add_chunk(np.array([x, h - size[1] * rng.uniform(0.2, 0.45), z]), size, R)
        done += 1


place(28, (0.15, 0.4), False, False)
place(8, (0.4, 0.7), False, False)
place(2, (0.7, 1.1), True, True)

# ---- collision: a block in the doorway (the root bone) and columns under the pile, each a little under its
# surface; columns that would touch the level are left out, they'd be pushed before the freeze
def to_world(p):
    return ORIGIN + p[..., 0:1] * RIGHT + p[..., 1:2] * np.array([0, 1.0, 0]) + p[..., 2:3] * FORWARD


data = open(level_dir + '/level.cform', 'rb').read()
_, vc, fc = struct.unpack_from('<III', data, 0)
verts = np.frombuffer(data, dtype='<f4', count=vc * 3, offset=36).reshape(vc, 3).astype(np.float64)
faces = np.frombuffer(data, dtype='<u4', count=fc * 4, offset=36 + vc * 12).reshape(fc, 4)[:, :3]
T = verts[faces]
T = T[np.linalg.norm(T.mean(1) - ORIGIN, axis=1) < 12]
basis = np.stack([RIGHT, [0, 1.0, 0], FORWARD])     # rows: local axes in world


def touches(c, Rb, half):
    """Level triangles inside the box (SAT, triangle vs box)."""
    axes = Rb @ basis                                  # box axes in world
    v = (T - to_world(c)) @ axes.T                     # triangles in box space
    e = [v[:, 1] - v[:, 0], v[:, 2] - v[:, 1], v[:, 0] - v[:, 2]]
    sep = np.zeros(len(v), bool)
    for k in range(3):                                 # the box's faces
        sep |= (v[:, :, k].min(1) > half[k]) | (v[:, :, k].max(1) < -half[k])
    n = np.cross(e[0], e[1])                           # the triangle's plane
    sep |= np.abs(np.einsum('ij,ij->i', n, v[:, 0])) > np.abs(n) @ half
    for ei in e:                                       # edge cross products
        for k in range(3):
            ax = np.cross(np.eye(3)[k], ei)
            p = np.einsum('tvj,tj->tv', v, ax)
            r = np.abs(ax) @ half
            sep |= (p.min(1) > r) | (p.max(1) < -r)
    return int((~sep).sum())


boxes, dropped = [], 0


def box_aligned(name, x0, x1, y0, y1, z0, z1):
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    half = np.array([(x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2])
    if touches(c, np.eye(3), half):
        return False
    boxes.append((name, c, np.eye(3), half))
    return True


assert box_aligned('link', -DOOR_HALF + 0.06, DOOR_HALF - 0.06, 0.10, DOOR_TOP - GAP, GAP, DOOR_DEPTH - GAP), 'the doorway block touches the level'
z1 = -GAP
while True:
    z0 = z1 - CELL_Z
    for x0 in np.arange(-2.4, WEST_X - GAP, CELL_X):
        x1 = min(x0 + CELL_X, WEST_X - GAP)
        h = float(base_height((x0 + x1) / 2, (z0 + z1) / 2)) - 0.05
        if h >= 0.3 and not box_aligned(f'col{len(boxes)}', x0, x1, GAP, h, z0, z1):
            dropped += 1
    if base_height(0.0, z0) < 0.3:
        break
    z1 = z0
assert len(boxes) <= 64, len(boxes)
print(f'collision: doorway block + {len(boxes) - 1} columns, {dropped} left out touching the level')


# ---- write the .ogf
def chunk(cid, payload):
    return struct.pack('<II', cid, len(payload)) + payload


def sz(s):
    return s.encode('cp1251') + b'\0'


def tangents(P, N, UV, I):
    Tn, Bn = np.zeros_like(P), np.zeros_like(P)
    p0, p1, p2 = P[I[:, 0]], P[I[:, 1]], P[I[:, 2]]
    t0, t1, t2 = UV[I[:, 0]], UV[I[:, 1]], UV[I[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = t1 - t0, t2 - t0
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(det) > 1e-12, 1.0 / np.where(np.abs(det) > 1e-12, det, 1), 0)[:, None]
    du = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    dv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for k in range(3):
        np.add.at(Tn, I[:, k], du); np.add.at(Bn, I[:, k], dv)
    Tn -= N * np.einsum('ij,ij->i', Tn, N)[:, None]
    Tn /= np.maximum(np.linalg.norm(Tn, axis=1, keepdims=True), 1e-9)
    Bn -= N * np.einsum('ij,ij->i', Bn, N)[:, None]
    Bn /= np.maximum(np.linalg.norm(Bn, axis=1, keepdims=True), 1e-9)
    return Tn, Bn


def bounds(P):
    lo, hi = P.min(0), P.max(0)
    c = (lo + hi) / 2
    return struct.pack('<6f', *lo, *hi) + struct.pack('<4f', *c, float(np.linalg.norm(P - c, axis=1).max()))


def child(mesh):
    P, N, UV, I = mesh.arrays()
    geo = np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]])
    flip = np.einsum('ij,ij->i', geo, N[I[:, 0]]) < 0
    I[flip] = I[flip][:, [0, 2, 1]]
    assert len(P) < 65536 and len(I) < 65536, (len(P), len(I))
    Tn, Bn = tangents(P, N, UV, I)
    v = np.zeros(len(P), dtype=[('p', '<f4', 3), ('n', '<f4', 3), ('t', '<f4', 3), ('b', '<f4', 3), ('uv', '<f4', 2), ('m', '<u4')])
    v['p'], v['n'], v['t'], v['b'], v['uv'], v['m'] = P, N, Tn, Bn, UV, 0
    body = chunk(1, struct.pack('<BBH', 4, 4, 0) + bounds(P))
    body += chunk(2, sz(mesh.texture) + sz('models\\model'))
    body += chunk(3, struct.pack('<II', 1, len(P)) + v.tobytes())
    body += chunk(4, struct.pack('<I', I.size) + I.astype('<u2').tobytes())
    body += chunk(6, b'\0' * 16 + struct.pack('<IIHH', 1, 0, len(I), len(P)))
    print(f'mesh {mesh.texture}: {len(P)} vertices, {len(I)} triangles, {int(flip.sum())} flipped')
    return body, P


def obb(Rb, c, half):
    return struct.pack('<9f', *Rb.reshape(-1)) + struct.pack('<3f', *c) + struct.pack('<3f', *half)


children, allP = [], []
for m in (ground, chunks):
    body, P = child(m)
    children.append(body); allP.append(P)
allP = np.concatenate(allP)

names = b''.join(sz(n) + sz('' if i == 0 else 'link') + obb(R, c, h) for i, (n, c, R, h) in enumerate(boxes))
ik = b''
for i, (n, c, R, h) in enumerate(boxes):
    shape = struct.pack('<HH', 1, 0) + obb(R, c, h) + struct.pack('<4f', *c, float(np.linalg.norm(h)))
    shape += struct.pack('<8f', *c, 0, 1, 0, float(2 * h[1]), float(max(h[0], h[2])))
    joint = struct.pack('<I', 0) + struct.pack('<4f', 0, 0, 1, 1) * 3 + struct.pack('<ffIfff', 1, 1, 0, 0, 0, 0)
    ik += struct.pack('<I', 1) + sz('objects\\concrete_box') + shape + joint
    ik += struct.pack('<6f', 0, 0, 0, 0, 0, 0) + struct.pack('<f', 1000.0 if i == 0 else 100.0) + struct.pack('<3f', *c)

ogf = chunk(1, struct.pack('<BBH', 4, 10, 0) + bounds(allP))
ogf += chunk(18, sz('shelter mound') + sz('') + struct.pack('<I', 0) + sz('') + struct.pack('<I', 0) + sz('') + struct.pack('<I', 0))
ogf += chunk(9, b''.join(chunk(i, body) for i, body in enumerate(children)))
ogf += chunk(13, struct.pack('<I', len(boxes)) + names)
ogf += chunk(16, ik)
open(out, 'wb').write(ogf)
print(f'{out}: {len(ogf)} bytes')
print(f'spawn at {ORIGIN[0]:.3f}, {ORIGIN[1]:.3f}, {ORIGIN[2]:.3f}, forward {FORWARD[0]:.4f}, {FORWARD[2]:.4f}')
