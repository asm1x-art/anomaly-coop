"""X-Ray file formats the checker reads: OGF (meshes, skeletons) and OMF (animations)."""
import struct

import numpy as np


def chunks(data):
    p = 0; out = {}
    while p + 8 <= len(data):
        cid, size = struct.unpack_from('<II', data, p); p += 8
        out[cid & 0x7fffffff] = data[p:p + size]; p += size
    return out


def rz(d, p):
    """a zero-terminated string at p: (text, position after it)"""
    e = d.index(b'\0', p)
    return d[p:e].decode('cp1251'), e + 1


# ---------------------------------------------------------------- skeleton (OGF chunks 13, 16)
def load_bones(path):
    """[[name, parent, bind rotation (xyz), bind position], ...] in the model's order"""
    c = chunks(open(path, 'rb').read())
    d = c[13]; n, = struct.unpack_from('<I', d, 0); p = 4; bones = []
    for i in range(n):
        name, p = rz(d, p); par, p = rz(d, p); p += 60
        bones.append([name.lower(), par.lower()])
    d = c[16]; p = 0
    for i in range(n):
        ver, = struct.unpack_from('<I', d, p); p += 4
        _, p = rz(d, p)  # material
        p += 112  # shape
        p += 4 + 48 + 8 + 4 + 8  # joint: type, limits, spring, damping, flags, break force/torque
        if ver > 0:
            p += 4
        rot = struct.unpack_from('<3f', d, p); p += 12
        pos = struct.unpack_from('<3f', d, p); p += 12
        p += 16
        bones[i] += [rot, pos]
    return bones


def bone_names(path):
    c = chunks(open(path, 'rb').read())
    if 13 not in c:
        return []
    d = c[13]; n, = struct.unpack_from('<I', d, 0); p = 4; names = []
    for i in range(n):
        a, p = rz(d, p); _, p = rz(d, p); p += 60
        names.append(a.lower())
    return names


# ---------------------------------------------------------------- animations (OMF chunks 14, 15)
def omf_params(path):
    """(version, [(part name, [bone names])], {motion: dict(flags, part, ...)})"""
    d = chunks(open(path, 'rb').read())[15]
    p = 0; ver, = struct.unpack_from('<H', d, p); p += 2
    npart, = struct.unpack_from('<H', d, p); p += 2
    parts = []
    for i in range(npart):
        name, p = rz(d, p); cnt, = struct.unpack_from('<H', d, p); p += 2; bones = []
        for j in range(cnt):
            if ver == 1:
                b, = struct.unpack_from('<I', d, p); p += 4
            elif ver == 2:
                b, p = rz(d, p)
            else:
                b, p = rz(d, p); p += 4
            bones.append(b)
        parts.append((name, bones))
    nm, = struct.unpack_from('<H', d, p); p += 2; defs = {}
    for i in range(nm):
        name, p = rz(d, p); flags, = struct.unpack_from('<I', d, p); p += 4
        bop, mid = struct.unpack_from('<HH', d, p); p += 4
        speed, power, accrue, falloff = struct.unpack_from('<4f', d, p); p += 16
        if ver >= 4:
            nmarks, = struct.unpack_from('<I', d, p); p += 4
            for k in range(nmarks):
                p = d.index(b'\n', p) + 1
                cnt, = struct.unpack_from('<I', d, p); p += 4 + cnt * 8
        defs[name.lower()] = dict(flags=flags, part=bop, mid=mid, speed=speed)
    return ver, parts, defs


class Motion:
    pass


def load_motions(path, want=None):
    """{name: Motion(length, bones=[(rotations[k,4], translations[k,3])])} for the motions want(name) accepts"""
    mc = chunks(chunks(open(path, 'rb').read())[14]); out = {}
    for cid, d in mc.items():
        if cid == 0:
            continue
        name, p = rz(d, 0); name = name.lower()
        if want and not want(name):
            continue
        length, = struct.unpack_from('<I', d, p); p += 4
        bones = []
        while p < len(d):
            fl = d[p]; p += 1
            if fl & 2:
                R = np.frombuffer(d, '<i2', 4, p).reshape(1, 4) / 32767.0; p += 8
            else:
                p += 4; R = np.frombuffer(d, '<i2', 4 * length, p).reshape(length, 4) / 32767.0; p += 8 * length
            if fl & 1:
                p += 4
                if fl & 4:
                    T = np.frombuffer(d, '<i2', 3 * length, p).reshape(length, 3).astype(float); p += 6 * length
                else:
                    T = np.frombuffer(d, 'i1', 3 * length, p).reshape(length, 3).astype(float); p += 3 * length
                size = np.array(struct.unpack_from('<3f', d, p)); p += 12
                init = np.array(struct.unpack_from('<3f', d, p)); p += 12
                T = T * size + init
            else:
                T = np.array(struct.unpack_from('<3f', d, p)).reshape(1, 3); p += 12
            bones.append((R, T))
        m = Motion(); m.length = length; m.bones = bones; out[name] = m
    return out


def qmat(q, t):
    """4x4 row-vector matrix (X-Ray's layout: v @ M) of a quaternion (x, y, z, w) and a translation"""
    x, y, z, w = q
    xx, yy, zz, xy, xz, yz, wx, wy, wz = x * x, y * y, z * z, x * y, x * z, y * z, w * x, w * y, w * z
    m = np.eye(4)
    m[0, :3] = [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)]
    m[1, :3] = [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)]
    m[2, :3] = [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)]
    m[3, :3] = t
    return m


def hpb(h, p, b):
    """Fmatrix::setHPB (radians), row-vector layout"""
    ch, cp, cb = np.cos(h), np.cos(p), np.cos(b); sh, sp, sb = np.sin(h), np.sin(p), np.sin(b)
    cc, cs, sc, ss = ch * cb, ch * sb, sh * cb, sh * sb
    m = np.eye(4)
    m[0, :3] = [cc - sp * ss, -cp * sb, sp * cs + sc]
    m[1, :3] = [sp * sc + cs, cp * cb, ss - sp * cc]
    m[2, :3] = [-cp * sh, sp, cp * ch]
    return m


# ---------------------------------------------------------------- geometry (OGF chunks 3, 4, 9)
VERTEX_FORMATS = {0x12071980: 1, 0x240e3300: 2, 0x36154c80: 3, 0x481c6600: 4, 1: 1, 2: 2, 3: 3, 4: 4}
VERTEX_SIZE = {1: 60, 2: 64, 3: 70, 4: 76}


def load_skin(path):
    """[(positions[n,3], bones[n,4], weights[n,4], triangles[m,3])] of every skinned part"""
    out = []

    def one(cc):
        if 3 in cc and 4 in cc:
            d = cc[3]; fmt, n = struct.unpack_from('<II', d, 0); L = VERTEX_FORMATS.get(fmt)
            if fmt == 0x112:  # rigid (D3DFVF_XYZ|NORMAL|TEX1): no bones
                a = np.frombuffer(d, np.uint8, n * 32, 8).reshape(n, 32)
                P = a[:, 0:12].copy().view('<f4').reshape(n, 3)
                w = np.zeros((n, 4)); w[:, 0] = 1
                d = cc[4]; ni, = struct.unpack_from('<I', d, 0)
                out.append((P.astype(float), np.zeros((n, 4), int), w, np.frombuffer(d, '<u2', ni, 4).reshape(-1, 3).astype(int)))
            elif L:
                a = np.frombuffer(d, np.uint8, n * VERTEX_SIZE[L], 8).reshape(n, VERTEX_SIZE[L])
                bn = np.zeros((n, 4), int); w = np.zeros((n, 4))
                if L == 1:
                    P = a[:, 0:12].copy().view('<f4').reshape(n, 3); bn[:, 0] = a[:, 56:60].copy().view('<u4').reshape(n); w[:, 0] = 1
                else:
                    off = 2 * L; P = a[:, off:off + 12].copy().view('<f4').reshape(n, 3)
                    bn[:, :L] = a[:, 0:off].copy().view('<u2').reshape(n, L)
                    ww = a[:, off + 48:off + 48 + 4 * (L - 1)].copy().view('<f4').reshape(n, L - 1)
                    if L == 2:
                        w[:, 0] = 1 - ww[:, 0]; w[:, 1] = ww[:, 0]
                    else:
                        w[:, :L - 1] = ww; w[:, L - 1] = 1 - ww.sum(axis=1)
                d = cc[4]; ni, = struct.unpack_from('<I', d, 0)
                tri = np.frombuffer(d, '<u2', ni, 4).reshape(-1, 3).astype(int)
                out.append((P.astype(float), bn, w, tri))
        if 9 in cc:
            for cid, d in sorted(chunks(cc[9]).items()):
                one(chunks(d))

    one(chunks(open(path, 'rb').read()))
    return out
