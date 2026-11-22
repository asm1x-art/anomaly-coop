"""X-Ray <-> Blender helpers for the HUD scene (blender-xray conventions).
X-Ray model space (x right, y up, z forward, left-handed) -> Blender (x, z, y)."""
import math
from mathutils import Matrix, Vector

S = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))   # swaps y/z, its own inverse


def hpb(h, p, b):
    """Fmatrix::setHPB (radians), X-Ray space, as a column-vector Matrix (columns = i, j, k)."""
    sh, ch, sp, cp, sb, cb = math.sin(h), math.cos(h), math.sin(p), math.cos(p), math.sin(b), math.cos(b)
    cc, cs, sc, ss = ch * cb, ch * sb, sh * cb, sh * sb
    i = (cc - sp * ss, -cp * sb, sp * cs + sc)
    j = (sp * sc + cs, cp * cb, ss - sp * cc)
    k = (-cp * sh, sp, cp * ch)
    m = Matrix.Identity(4)
    for r in range(3):
        m[r][0], m[r][1], m[r][2] = i[r], j[r], k[r]
    return m


def offset_b(pos, rot_deg):
    """hud offset (pos, HPB degrees as in the .ltx) -> Blender matrix."""
    m = hpb(*[math.radians(a) for a in rot_deg])
    m.translation = Vector(pos)
    return S @ m @ S
