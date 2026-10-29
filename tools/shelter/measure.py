# Measures the bunker's openings (level.cform raycasts) and the HF door / wall models (.ogf bounding boxes).
#   measure.py <level dir> <HF gamedata dir>
import math
import os
import struct
import sys

import numpy as np

level_dir, hf = sys.argv[1], sys.argv[2]


# ---- models: OGF_HEADER (chunk 1): u8 version, u8 type, u16 shader, Fbox bb, Fsphere bs
def ogf_box(path):
    data = open(path, 'rb').read()
    pos = 0
    while pos + 8 <= len(data):
        cid, size = struct.unpack_from('<II', data, pos)
        if cid & 0x7fffffff == 1:
            mn = struct.unpack_from('<3f', data, pos + 8 + 4)
            mx = struct.unpack_from('<3f', data, pos + 8 + 16)
            return [mx[i] - mn[i] for i in range(3)]
        pos += 8 + size
    return None


print('== models (width x, height y, depth z, metres)')
for rel in ['doors/door_wood_100x190', 'doors/door_wood_115x215', 'doors/door_wood_145x220', 'doors/door_metal_150x250',
            'doors/door_old_176x300', 'dynamics/Decor/wall', 'dynamics/Decor/wall02', 'dynamics/Decor/wall_metal',
            'dynamics/Decor/wall02_metal', 'dynamics/Decor/wall_doorway', 'dynamics/Decor/wall_doorway_metal']:
    b = ogf_box(os.path.join(hf, 'meshes', rel + '.ogf'))
    print(f'  {rel:32s} ' + ('x'.join(f'{v:.2f}' for v in b) if b else '?'))

# ---- level collision: hdrCFORM { u32 version, vertcount, facecount; Fbox aabb } + verts + faces (3 x u32, u32 dummy)
data = open(os.path.join(level_dir, 'level.cform'), 'rb').read()
version, vc, fc = struct.unpack_from('<III', data, 0)
off = 12 + 24
verts = np.frombuffer(data, dtype='<f4', count=vc * 3, offset=off).reshape(vc, 3).astype(np.float64)
off += vc * 12
faces = np.frombuffer(data, dtype='<u4', count=fc * 4, offset=off).reshape(fc, 4)[:, :3]
A, B, C = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
E1, E2 = B - A, C - A
print(f'== level.cform v{version}: {vc} vertices, {fc} faces')


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


def opening(name, x, y, z, dx, dz, ahead=4.0):
    d = np.array([dx, 0.0, dz]); d /= np.linalg.norm(d)
    side = np.array([-d[2], 0.0, d[0]])
    best = None
    for i in range(0, int(ahead / 0.1) + 1):
        o = np.array([x, y + 1.0, z]) + d * (i * 0.1)
        l, r = ray(o, side), ray(o, -side)
        up, down = ray(o, [0, 1, 0]), ray(o, [0, -1, 0])
        w, h = l + r, up + down
        if best is None or w < best[0] - 0.05:
            centre = o + side * (l - r) / 2
            best = (w, h, i * 0.1, centre, down)
    w, h, at, c, down = best
    print(f'  {name}: narrowest {w:.2f} m wide x {h:.2f} m high, {at:.1f} m ahead; '
          f'centre {c[0]:.2f}, {c[1] - 1.0:.2f} (floor ~{c[1] - down:.2f}), {c[2]:.2f}; facing {d[0]:.2f}, {d[2]:.2f}')


print('== openings')
opening('2 (stairs down)', -2.92, 3.00, -17.09, -0.013, -0.919)
opening('3 (obstacle)', 2.26, 3.13, -0.18, 0.043, 0.994)
opening('4 (corridor end)', 2.33, 3.48, 31.89, 0.009, 0.946)
opening('1 (entrance)', -6.99, 3.28, -27.09, 0.978, -0.124)

# ---- the left stairs from the lower hall: floor cells (0..4 m) next to stair cells, west of x = -10
ai = open(os.path.join(level_dir, 'level.ai'), 'rb').read()
_, count, size, size_y = struct.unpack_from('<IIff', ai, 0)
minx, miny, minz, maxx, maxy, maxz = struct.unpack_from('<6f', ai, 16)
row = int(math.floor((maxz - minz) / size + 1e-6 + 1.5))
cells = {}
for i in range(count):
    p = ai[56 + i * 23 + 18: 56 + i * 23 + 23]
    xz = p[0] | (p[1] << 8) | (p[2] << 16)
    cells[(xz // row, xz % row)] = miny + struct.unpack_from('<H', p, 3)[0] / 65535 * size_y
edge = []
for (cx, cz), y in cells.items():
    if not (-1 <= y <= 6):
        continue
    wx, wz = minx + cx * size, minz + cz * size
    if wx > -10 or not (-14 < wz < 0):
        continue
    for nx, nz in ((cx - 1, cz), (cx + 1, cz), (cx, cz - 1), (cx, cz + 1)):
        ny = cells.get((nx, nz))
        if ny is not None and not (-1 <= ny <= 6):
            edge.append((wx, y, wz, minx + nx * size - wx, minz + nz * size - wz))
if edge:
    ex = sum(e[0] for e in edge) / len(edge); ey = sum(e[1] for e in edge) / len(edge); ez = sum(e[2] for e in edge) / len(edge)
    ddx = sum(e[3] for e in edge); ddz = sum(e[4] for e in edge)
    print(f'  left stairs: {len(edge)} floor cells meet the stairs around {ex:.2f}, {ey:.2f}, {ez:.2f}, towards {ddx:.1f}, {ddz:.1f}')
    opening('6 (left stairs)', ex - ddx / math.hypot(ddx, ddz) * 2.0, ey, ez - ddz / math.hypot(ddx, ddz) * 2.0, ddx, ddz)
else:
    print('  left stairs: not found')
