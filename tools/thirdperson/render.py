"""Pictures of the actor's body in a hold with a gun's world model placed as the engine places it (flat shaded,
orthographic, painter's algorithm: enough to see a gun under or apart from the hands)."""
import math

import numpy as np
from PIL import Image, ImageDraw

import rig as rigmod
import xr
from fit import ADDON_BONES

BODY_COLOR, GUN_COLOR = (150, 160, 150), (200, 90, 60)


def view(az, el=12):
    """a camera around the body: az degrees from its front towards its right side, el degrees from above"""
    a = math.radians(az); e = math.radians(el)
    f = np.array([-math.sin(a) * math.cos(e), -math.sin(e), -math.cos(a) * math.cos(e)])
    r = np.cross([0, 1, 0], f); r /= np.linalg.norm(r); u = np.cross(f, r)
    return f'az {az}', tuple(r), tuple(u)


RIGHT = ('from the right side', (0, 0, 1), (0, 1, 0))  # the model's +x is its right
LEFT = ('from the left side', (0, 0, -1), (0, 1, 0))
ABOVE = ('from above', (-1, 0, 0), (0, 0, 1))


class Painter:
    def __init__(self, rig, meshes):
        self.rig, self.meshes = rig, meshes
        self.body = xr.load_skin(rig.body_path)
        self.bind = []
        for b in rig.B:
            x, y, z = b[2]; L = xr.hpb(-y, -x, -z); L[3, :3] = b[3]
            self.bind.append(L if b[1] == '' else L @ self.bind[rig.idx[b[1]]])
        self.bind_inv = np.array([np.linalg.inv(m) for m in self.bind])

    def skin(self, W):
        X = np.einsum('bij,bjk->bik', self.bind_inv, np.array(W)); res = []
        for P, bn, w, tri in self.body:
            P4 = np.c_[P, np.ones(len(P))]; V = np.zeros((len(P), 3))
            for k in range(4):
                V += w[:, k:k + 1] * np.einsum('ni,nij->nj', P4, X[bn[:, k]])[:, :3]
            res.append((V, tri))
        return res

    def gun(self, vis):
        p, _ = self.meshes.find(vis)
        hide = [i for i, n in enumerate(xr.bone_names(p)) if n in ADDON_BONES]
        return [(P, tri[~np.isin(bn[tri[:, 0], 0], hide)]) for P, bn, w, tri in xr.load_skin(p)]

    def shot(self, torso, legs, vis, pos, ori, views, size=420, span=0.8, ft=0.25, fl=0.25):
        """the body and the gun, centred between the palms; span: metres across the picture"""
        W = self.rig.pose(torso, legs, ft, fl)
        ms = [(V, tri, BODY_COLOR) for V, tri in self.skin(W)]
        if vis:
            T = rigmod.offset(pos, ori) @ self.rig.hold(W)
            for P, tri in self.gun(vis):
                ms.append(((np.c_[P, np.ones(len(P))] @ T)[:, :3], tri, GUN_COLOR))
        c = (self.rig.palm(W, 'l') + self.rig.palm(W, 'r')) / 2
        return draw(ms, views, c, size, span)


def draw(meshes, views, center, size, span):
    img = Image.new('RGB', (size * len(views), size), (235, 235, 235))
    for vi, v in enumerate(views):
        img.paste(draw_one(meshes, v, center, size, span), (vi * size, 0))
    return img


def draw_one(meshes, view_, center, size, span):
    img = Image.new('RGB', (size, size), (235, 235, 235)); dr = ImageDraw.Draw(img)
    light = np.array([0.3, 0.8, 0.5]); light /= np.linalg.norm(light)
    for vi, (name, right, up) in enumerate([view_]):
        right = np.array(right, float); up = np.array(up, float); fwd = np.cross(right, up)
        polys = []
        for V, tri, col in meshes:
            if not len(tri):
                continue
            Pc = V - np.array(center); x = Pc @ right; y = Pc @ up; z = Pc @ fwd
            a, b, c = V[tri[:, 0]], V[tri[:, 1]], V[tri[:, 2]]
            n = np.cross(b - a, c - a); ln = np.linalg.norm(n, axis=1); ln[ln == 0] = 1; n /= ln[:, None]
            sh = 0.45 + 0.55 * np.abs(n @ light)
            zz = z[tri].mean(axis=1)
            for t in range(len(tri)):
                polys.append((zz[t], [(x[i], y[i]) for i in tri[t]], tuple(int(cc * sh[t]) for cc in col)))
        polys.sort(key=lambda p: -p[0])  # far first
        s = size / span
        for _, pts, col in polys:
            dr.polygon([(vi * size + size / 2 + px * s, size / 2 - py * s) for px, py in pts], fill=col)
        dr.text((vi * size + 6, 4), name, fill=(0, 0, 0))
    return img
