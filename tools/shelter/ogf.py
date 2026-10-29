# A rigid dynamic model (.ogf) as tools\shelter\mound.py writes one (laid out like dynamics\large_trash\aes_zabor):
# children of type 4 meshes with one slide window each, a bone per collision box (the first one the root), each with a
# box shape, a mass and a material for the physics.
import struct

import numpy as np


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
        np.add.at(Tn, I[:, k], du)
        np.add.at(Bn, I[:, k], dv)
    Tn -= N * np.einsum('ij,ij->i', Tn, N)[:, None]
    Tn /= np.maximum(np.linalg.norm(Tn, axis=1, keepdims=True), 1e-9)
    Bn -= N * np.einsum('ij,ij->i', Bn, N)[:, None]
    Bn /= np.maximum(np.linalg.norm(Bn, axis=1, keepdims=True), 1e-9)
    return Tn, Bn


def bounds(P):
    lo, hi = P.min(0), P.max(0)
    c = (lo + hi) / 2
    return struct.pack('<6f', *lo, *hi) + struct.pack('<4f', *c, float(np.linalg.norm(P - c, axis=1).max()))


def child(texture, P, N, UV, I, shader='models\\model'):
    """a mesh: triangles turned to face along their vertices' normals"""
    I = I.copy()
    geo = np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]])
    flip = np.einsum('ij,ij->i', geo, N[I[:, 0]]) < 0
    I[flip] = I[flip][:, [0, 2, 1]]
    assert len(P) < 65536 and I.size < 65536, (len(P), I.size)
    Tn, Bn = tangents(P, N, UV, I)
    v = np.zeros(len(P), dtype=[('p', '<f4', 3), ('n', '<f4', 3), ('t', '<f4', 3), ('b', '<f4', 3), ('uv', '<f4', 2), ('m', '<u4')])
    v['p'], v['n'], v['t'], v['b'], v['uv'], v['m'] = P, N, Tn, Bn, UV, 0
    body = chunk(1, struct.pack('<BBH', 4, 4, 0) + bounds(P))
    body += chunk(2, sz(texture) + sz(shader))
    body += chunk(3, struct.pack('<II', 1, len(P)) + v.tobytes())
    body += chunk(4, struct.pack('<I', I.size) + I.astype('<u2').tobytes())
    body += chunk(6, b'\0' * 16 + struct.pack('<IIHH', 1, 0, len(I), len(P)))
    return body


def obb(R, c, half):
    return struct.pack('<9f', *R.reshape(-1)) + struct.pack('<3f', *c) + struct.pack('<3f', *half)


def write(path, meshes, boxes, desc, material):
    """meshes: (texture, P, N, UV, I); boxes: (centre, half sizes, mass), axis-aligned in the model's frame"""
    allP = np.concatenate([m[1] for m in meshes])
    names = b''.join(sz('root' if i == 0 else f'link{i}') + sz('' if i == 0 else 'root') + obb(np.eye(3), c, h)
                     for i, (c, h, m) in enumerate(boxes))
    ik = b''
    for c, h, mass in boxes:
        shape = struct.pack('<HH', 1, 0) + obb(np.eye(3), c, h) + struct.pack('<4f', *c, float(np.linalg.norm(h)))
        shape += struct.pack('<8f', *c, 0, 1, 0, float(2 * h[1]), float(max(h[0], h[2])))
        joint = struct.pack('<I', 0) + struct.pack('<4f', 0, 0, 1, 1) * 3 + struct.pack('<ffIfff', 1, 1, 0, 0, 0, 0)
        ik += struct.pack('<I', 1) + sz(material) + shape + joint
        ik += struct.pack('<6f', 0, 0, 0, 0, 0, 0) + struct.pack('<f', mass) + struct.pack('<3f', *c)
    ogf = chunk(1, struct.pack('<BBH', 4, 10, 0) + bounds(allP))
    ogf += chunk(18, sz(desc) + sz('') + struct.pack('<I', 0) + sz('') + struct.pack('<I', 0) + sz('') + struct.pack('<I', 0))
    ogf += chunk(9, b''.join(chunk(i, child(*m)) for i, m in enumerate(meshes)))
    ogf += chunk(13, struct.pack('<I', len(boxes)) + names)
    ogf += chunk(16, ik)
    open(path, 'wb').write(ogf)
    return len(ogf)
