# Takes static visuals out of a compiled level without recompiling it:
#  - the "level" file: each visual's OGF_HEADER bounds are moved far under the level, so the renderer culls it
#    (static visuals are culled by these bounds: dxRender_Visual::Load, CRender::add_Static);
#  - level.cform: the collision triangles whose three corners are all the visual's vertices are dropped.
# Always works from the untouched originals in <orig dir>.
#   strip.py <orig dir> <out dir> <visual,...>
import os
import struct
import sys

import numpy as np

from levelgeom import Geom
from levelvis import level

orig, out, ids = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(',')]
d, shaders, visuals = level(orig)
g = Geom(orig + '/level.geom')
lvl = bytearray(d)

cf = open(orig + '/level.cform', 'rb').read()
version, vc, fc = struct.unpack_from('<III', cf, 0)
cverts = np.frombuffer(cf, '<f4', vc * 3, 36).reshape(vc, 3).astype(np.float64)
cfaces = np.frombuffer(cf, '<u4', fc * 4, 36 + vc * 12).reshape(fc, 4)
ckey = [tuple(k) for k in np.round(cverts * 200).astype(np.int64)]    # 5 mm
drop = np.zeros(fc, bool)
FAR = (0.0, -10000.0, 0.0)

for i in ids:
    v = visuals[i]
    T = g.triangles(d, v)
    vk = set(map(tuple, np.round(T.reshape(-1, 3) * 200).astype(np.int64)))
    mine = np.array([ckey[a] in vk and ckey[b] in vk and ckey[c] in vk for a, b, c, _ in cfaces])
    tri = cverts[cfaces[mine][:, :3]]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2 if len(tri) else np.zeros(0)
    print(f'{i:4d} {shaders[v["shader"]]:55s} collision triangles {int(mine.sum()):5d}, largest {area.max() if len(area) else 0:.2f} m2')
    drop |= mine
    # bounds: box (min, max) and sphere (centre, radius) after the 4-byte version/type/shader
    struct.pack_into('<6f4f', lvl, v['header'] + 4, *FAR, *FAR, *FAR, 0.001)

os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'level'), 'wb').write(lvl)
keep = cfaces[~drop]
hdr = bytearray(cf[:36])
struct.pack_into('<I', hdr, 8, len(keep))
open(os.path.join(out, 'level.cform'), 'wb').write(bytes(hdr) + cf[36:36 + vc * 12] + keep.tobytes())
print(f'collision: {fc} -> {len(keep)} triangles')
