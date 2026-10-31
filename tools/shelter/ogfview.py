"""Reads a .ogf (version 4) and draws it offline: meshes, sizes, physics flags, a two-view thumbnail."""
import os
import struct

import numpy as np
from PIL import Image


def chunks(buf):
    pos, out = 0, []
    while pos + 8 <= len(buf):
        cid, size = struct.unpack_from("<II", buf, pos)
        cid &= 0x7fffffff  # the compressed flag is never set in a model
        out.append((cid, buf[pos + 8:pos + 8 + size]))
        pos += 8 + size
    return out


def _sz(buf, pos=0):
    end = buf.index(b"\0", pos)
    return buf[pos:end].decode("cp1251", "replace"), end + 1


# bytes per vertex -> offsets of (position, normal, uv)
LAYOUT = {60: (0, 12, 48), 64: (4, 16, 56), 70: (6, 18, 62), 76: (8, 20, 68)}


def read_mesh(body):
    c = dict(chunks(body))
    if 3 not in c or 4 not in c:
        return None
    tex, shader = "", ""
    if 2 in c:
        tex, p = _sz(c[2])
        shader, _ = _sz(c[2], p)
    vh = c[3]
    _, count = struct.unpack_from("<II", vh, 0)
    if not count:
        return None
    size = (len(vh) - 8) // count
    if size not in LAYOUT:
        return None
    op, on, ou = LAYOUT[size]
    raw = np.frombuffer(vh, dtype=np.uint8, offset=8, count=count * size).reshape(count, size)

    def field(off, n):
        return np.frombuffer(raw[:, off:off + 4 * n].tobytes(), dtype="<f4").reshape(count, n).astype(np.float64)

    P, N, UV = field(op, 3), field(on, 3), field(ou, 2)
    n_idx = struct.unpack_from("<I", c[4], 0)[0]
    I = np.frombuffer(c[4], dtype="<u2", offset=4, count=n_idx)
    if 6 in c and len(c[6]) >= 28:  # the most detailed window of a progressive mesh
        offs, tris, _ = struct.unpack_from("<iHH", c[6], 20)
        I = I[offs:offs + tris * 3]
    return {"tex": tex, "shader": shader, "P": P, "N": N, "UV": UV, "I": I.reshape(-1, 3).astype(np.int64)}


def read_ogf(path):
    data = open(path, "rb").read()
    top = chunks(data)
    c = dict(top)
    meshes = []
    if 9 in c:
        for _, body in chunks(c[9]):
            m = read_mesh(body)
            if m:
                meshes.append(m)
    else:
        m = read_mesh(data)
        if m:
            meshes.append(m)
    bones = 0
    if 13 in c and len(c[13]) >= 4:
        bones = struct.unpack_from("<I", c[13], 0)[0]
    info = {"meshes": meshes, "bones": bones, "physics": 16 in c and len(c[16]) > 0,
            "motions": 14 in c or 15 in c or 19 in c, "type": data[8 + 1] if len(data) > 9 else -1}
    if 18 in c:  # kept empty
        pass
    if meshes:
        allP = np.concatenate([m["P"] for m in meshes])
        info["size"] = (allP.max(0) - allP.min(0)).round(3).tolist()
        info["tris"] = int(sum(len(m["I"]) for m in meshes))
    else:
        info["size"], info["tris"] = [0, 0, 0], 0
    return info


_tex_cache = {}


def load_texture(name, roots):
    key = name.lower()
    if key in _tex_cache:
        return _tex_cache[key]
    arr = None
    rel = key.replace("\\", "/") + ".dds"
    for root in roots:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            try:
                img = Image.open(path).convert("RGBA")
                img.thumbnail((512, 512))
                arr = np.asarray(img, dtype=np.float32) / 255
            except Exception:
                arr = None
            break
    _tex_cache[key] = arr
    return arr


def view(meshes, roots, yaw, size, pitch=-0.42):
    """an orthographic 3/4 view, z-buffered, lit from the camera's upper left"""
    cy, sy, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    R = Rx @ Ry
    allP = np.concatenate([m["P"] for m in meshes])
    centre = (allP.min(0) + allP.max(0)) / 2
    Q = (allP - centre) @ R.T
    half = float(np.abs(Q[:, :2]).max()) or 1.0
    scale = (size / 2 - 3) / half
    col = np.empty((size, size, 3), dtype=np.float32)
    col[:] = (0.13, 0.14, 0.16)
    depth = np.full((size, size), np.inf, dtype=np.float32)
    light = np.array([-0.45, 0.6, -0.66])
    for m in meshes:
        tex = load_texture(m["tex"], roots) if m["tex"] else None
        q = (m["P"] - centre) @ R.T
        n = m["N"] @ R.T
        sx = size / 2 + q[:, 0] * scale
        sy_ = size / 2 - q[:, 1] * scale
        z = q[:, 2]
        I = m["I"]
        for a, b, c in I:
            ax, ay, bx, by, cx, cy2 = sx[a], sy_[a], sx[b], sy_[b], sx[c], sy_[c]
            x0, x1 = int(max(min(ax, bx, cx), 0)), int(min(max(ax, bx, cx) + 1, size - 1))
            y0, y1 = int(max(min(ay, by, cy2), 0)), int(min(max(ay, by, cy2) + 1, size - 1))
            if x1 < x0 or y1 < y0:
                continue
            det = (by - cy2) * (ax - cx) + (cx - bx) * (ay - cy2)
            if abs(det) < 1e-9:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((by - cy2) * (xs - cx) + (cx - bx) * (ys - cy2)) / det
            w1 = ((cy2 - ay) * (xs - cx) + (ax - cx) * (ys - cy2)) / det
            w2 = 1 - w0 - w1
            inside = (w0 >= -0.01) & (w1 >= -0.01) & (w2 >= -0.01)
            if not inside.any():
                continue
            zz = w0 * z[a] + w1 * z[b] + w2 * z[c]
            sub = depth[y0:y1 + 1, x0:x1 + 1]
            mask = inside & (zz < sub)
            if not mask.any():
                continue
            nn = (w0[..., None] * n[a] + w1[..., None] * n[b] + w2[..., None] * n[c])[mask]
            nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-6)
            # the vertex normals face outward: the camera looks along +z, so -z faces it
            shade = 0.42 + 0.68 * np.abs(nn @ light)
            if tex is not None:
                h, w = tex.shape[:2]
                u = w0[mask] * m["UV"][a, 0] + w1[mask] * m["UV"][b, 0] + w2[mask] * m["UV"][c, 0]
                v = w0[mask] * m["UV"][a, 1] + w1[mask] * m["UV"][b, 1] + w2[mask] * m["UV"][c, 1]
                texel = tex[(v * h).astype(np.int64) % h, (u * w).astype(np.int64) % w]
                keep = texel[:, 3] > 0.25 if "glass" not in m["shader"] else np.ones(len(texel), bool)
                rgb = texel[:, :3] * shade[:, None]
            else:
                keep = np.ones(mask.sum(), bool)
                rgb = np.array((0.75, 0.3, 0.75), dtype=np.float32) * shade[:, None]  # no texture found: magenta
            ys_m, xs_m = np.nonzero(mask)
            ys_m, xs_m = ys_m[keep] + y0, xs_m[keep] + x0
            col[ys_m, xs_m] = np.clip(rgb[keep], 0, 1)
            depth[ys_m, xs_m] = zz[mask][keep]
    return col


def thumbnail(info, roots, out, size=230):
    """two sides of it, drawn at twice the size and shrunk"""
    meshes = info["meshes"]
    big = size * 2
    front = view(meshes, roots, 0.6, big)
    back = view(meshes, roots, 0.6 + np.pi, big)
    gap = np.full((big, 4, 3), 0.05, dtype=np.float32)
    img = Image.fromarray((np.concatenate([front, gap, back], axis=1) * 255).astype(np.uint8))
    img = img.resize((size * 2 + 2, size), Image.LANCZOS)
    img.save(out, quality=82)
    missing = sorted({m["tex"] for m in meshes if m["tex"] and load_texture(m["tex"], roots) is None})
    return missing
