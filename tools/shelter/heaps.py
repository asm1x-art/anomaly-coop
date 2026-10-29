# For the level's heap visuals: which collision (level.cform) triangles are theirs (all three corners on the
# visual's vertices), and whether there is a floor under them once those are gone; plus a plan picture of each.
#   heaps.py <level dir> <visual,...> <out prefix>
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

from levelgeom import Geom
from levelvis import level

level_dir, ids, prefix = sys.argv[1], [int(x) for x in sys.argv[2].split(',')], sys.argv[3]
d, shaders, visuals = level(level_dir)
g = Geom(level_dir + '/level.geom')

cf = open(level_dir + '/level.cform', 'rb').read()
_, vc, fc = struct.unpack_from('<III', cf, 0)
cverts = np.frombuffer(cf, '<f4', vc * 3, 36).reshape(vc, 3).astype(np.float64)
cfaces = np.frombuffer(cf, '<u4', fc * 4, 36 + vc * 12).reshape(fc, 4)
ckey = np.round(cverts * 200).astype(np.int64)        # 5 mm


def keys(p):
    k = np.round(p * 200).astype(np.int64)
    return set(map(tuple, k.reshape(-1, 3)))


def ray_down(T, o):
    """Distance down from each point in o to the triangles T (Moller-Trumbore, vectorised over triangles)."""
    A, B, C = T[:, 0], T[:, 1], T[:, 2]
    E1, E2 = B - A, C - A
    dvec = np.array([0, -1.0, 0])
    pv = np.cross(dvec, E2)
    det = np.einsum('ij,ij->i', E1, pv)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1 / np.where(ok, det, 1), 0)
    out = []
    for q in o:
        tv = q - A
        u = np.einsum('ij,ij->i', tv, pv) * inv
        qv = np.cross(tv, E1)
        v = (qv @ dvec) * inv
        t = np.einsum('ij,ij->i', E2, qv) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-4)
        out.append(t[hit].min() if hit.any() else np.inf)
    return np.array(out)


for i in ids:
    v = visuals[i]
    T = g.triangles(d, v)
    vk = keys(T)
    mine = np.array([all(tuple(ckey[c]) in vk for c in f[:3]) for f in cfaces])
    rest = cverts[cfaces[~mine][:, :3]]
    lo, hi = T.reshape(-1, 3).min(0) - 0.5, T.reshape(-1, 3).max(0) + 0.5
    near = rest[((rest.max(1) >= lo) & (rest.min(1) <= hi)).all(1)]
    # sample the heap's top surface: triangle centres, pushed a little up
    cent = T.mean(1)
    sample = cent[np.random.default_rng(1).choice(len(cent), min(300, len(cent)), replace=False)] + [0, 0.02, 0]
    drop = ray_down(near, sample)
    floor_ok = np.isfinite(drop) & (drop < 0.8)
    mats = sorted(set(int(m) & 0x3fff for m in cfaces[mine][:, 3])) if mine.any() else []
    print(f'{i:4d} {shaders[v["shader"]]:55s} {len(T):6d} tris; cform: {int(mine.sum())} triangles its own; '
          f'floor under {int(floor_ok.sum())}/{len(sample)} samples, drop median {np.median(drop[floor_ok]) if floor_ok.any() else -1:.2f} m')
    # plan: heap triangles coloured by height over the floor found under their centres
    K = 40
    W, H = int((hi[0] - lo[0]) * K) + 1, int((hi[2] - lo[2]) * K) + 1
    img = Image.new('RGB', (W, H), (20, 20, 24))
    dr = ImageDraw.Draw(img)
    for tri in near:
        if np.ptp(tri[:, 1]) < 0.05 and abs(tri[:, 1].mean() - lo[1] - 0.5) < 1.0:
            dr.polygon([((p[0] - lo[0]) * K, (hi[2] - p[2]) * K) for p in tri], fill=(55, 55, 70))
    ymin = T[..., 1].min()
    for tri in T:
        h = tri[:, 1].mean() - ymin
        c = int(min(255, 80 + h * 400))
        dr.polygon([((p[0] - lo[0]) * K, (hi[2] - p[2]) * K) for p in tri], fill=(c, c // 2, 40))
    img.save(f'{prefix}_{i}.png')
