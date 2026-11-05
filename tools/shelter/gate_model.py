# The hermetic gate across the lower tunnel (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Ярусы и лифт"): GRA's gate raid_meshes\labx1_germo stretched
# to the tunnel's whole section (7.2 m wide, 4.8 m high), its edges in the rock; one box for the collision. Its texture is
# copied as it is (metal\metal_germo).
#   gate_model.py   -> gamedata\meshes\dynamics\shelter\tunnel_gate.ogf, gamedata\textures\metal\metal_germo.*
import os
import shutil
import struct

import numpy as np

import ogf

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
GRA = r"X:\GRA2.5\MO2\mods\[Основа] GRA\gamedata"
WIDTH = 7.8  # the model's, over the tunnel's walls
BOX = (np.array([0.0, 2.6, 0.0]), np.array([3.45, 2.3, 0.2]), 500.0)  # inside the rock's reach, or physics would push it


def chunks(buf):
    pos, out = 0, {}
    while pos + 8 <= len(buf):
        cid, size = struct.unpack_from("<II", buf, pos)
        out.setdefault(cid & 0x7fffffff, []).append(buf[pos + 8:pos + 8 + size])
        pos += 8 + size
    return out


def read_mesh(path):
    """the model's one mesh: positions, normals, uv, triangles, by the size of its vertices"""
    children = chunks(chunks(open(path, "rb").read())[9][0])
    body = chunks(next(iter(children.values()))[0])
    data = body[3][0]
    count = struct.unpack_from("<I", data, 4)[0]
    size = (len(data) - 8) // count
    op, on, ou = {60: (0, 12, 48), 64: (4, 16, 56), 70: (6, 18, 62), 76: (8, 20, 68)}[size]
    raw = np.frombuffer(data, dtype=np.uint8, offset=8).reshape(count, size)

    def field(off, n):
        return np.frombuffer(raw[:, off:off + 4 * n].tobytes(), dtype="<f4").reshape(count, n).astype(float)

    idx = body[4][0]
    I = np.frombuffer(idx, dtype="<u2", offset=4, count=struct.unpack_from("<I", idx, 0)[0]).reshape(-1, 3).astype(np.int64)
    return field(op, 3), field(on, 3), field(ou, 2), I


P, N, UV, I = read_mesh(os.path.join(GRA, "meshes", "dynamics", "raid_meshes", "labx1_germo.ogf"))
P[:, 0] -= (P[:, 0].min() + P[:, 0].max()) / 2
scale = WIDTH / (P[:, 0].max() - P[:, 0].min())
P[:, :2] *= scale  # the width and the height; its depth stays
out = os.path.join(GAMEDATA, "meshes", "dynamics", "shelter", "tunnel_gate.ogf")
print(ogf.write(out, [("metal\\metal_germo", P, N, UV, I)], [BOX], "shelter tunnel gate", "objects\\small_box"), "bytes",
      (P.max(0) - P.min(0)).round(2))
dest = os.path.join(GAMEDATA, "textures", "metal")
os.makedirs(dest, exist_ok=True)
for name in ("metal_germo.dds", "metal_germo.thm"):
    shutil.copy2(os.path.join(GRA, "textures", "metal", name), dest)
