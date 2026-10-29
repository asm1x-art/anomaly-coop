# Width / floor / ceiling profile along a direction through a bunker opening (level.cform raycasts).
#   profile.py <level dir> <x> <y> <z> <dx> <dz> [from] [to]
import struct
import sys

import numpy as np

level_dir = sys.argv[1]
x, y, z, dx, dz = map(float, sys.argv[2:7])
t0 = float(sys.argv[7]) if len(sys.argv) > 7 else -4.0
t1 = float(sys.argv[8]) if len(sys.argv) > 8 else 4.0
STEP = float(sys.argv[9]) if len(sys.argv) > 9 else 0.25

data = open(level_dir + '/level.cform', 'rb').read()
version, vc, fc = struct.unpack_from('<III', data, 0)
off = 12 + 24
verts = np.frombuffer(data, dtype='<f4', count=vc * 3, offset=off).reshape(vc, 3).astype(np.float64)
off += vc * 12
faces = np.frombuffer(data, dtype='<u4', count=fc * 4, offset=off).reshape(fc, 4)[:, :3]
A, B, C = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
E1, E2 = B - A, C - A


def ray(o, d, far=30.0):
    d = np.asarray(d, float) / np.linalg.norm(d)
    p = np.cross(d, E2)
    det = np.einsum('ij,ij->i', E1, p)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
    t_ = np.asarray(o, float) - A
    u = np.einsum('ij,ij->i', t_, p) * inv
    q = np.cross(t_, E1)
    v = (q @ d) * inv
    t = np.einsum('ij,ij->i', E2, q) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-4) & (t < far)
    return float(t[hit].min()) if hit.any() else far


d = np.array([dx, 0.0, dz]); d /= np.linalg.norm(d)
side = np.array([-d[2], 0.0, d[0]])
print(f'dir {d[0]:.3f},{d[2]:.3f}  side(left) {side[0]:.3f},{side[2]:.3f}')
for i in range(int(round((t1 - t0) / STEP)) + 1):
    t = t0 + i * STEP
    o = np.array([x, y + 1.0, z]) + d * t
    l, r = ray(o, side), ray(o, -side)
    up, down = ray(o, [0, 1, 0]), ray(o, [0, -1, 0])
    print(f'{t:+5.2f}: left {l:5.2f} right {r:5.2f} width {l + r:5.2f}  floor {o[1] - down:6.2f} ceiling {o[1] + up:6.2f}')
