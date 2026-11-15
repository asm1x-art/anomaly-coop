"""The actor's body posed by its animations, and where the engine puts the gun in its hands (CWeapon::UpdateXForm,
the co-op puppet's hand_xform: the same maths)."""
import os
import sys

import numpy as np

import xr

HERE = os.path.dirname(os.path.abspath(__file__))
BODY = 'actors/stalker_hero/stalker_hero_1.ogf'
ANIMS = 'actors/stalker_animation.omf'
# actor.ltx weapon_bone0/1/2: the gun goes from the right index finger towards the left one; every gun has
# hand_dependence = 1, where weapon_bone2 (the right index finger's second joint) takes the left one's place
HAND_R, HAND_L, HAND_R2 = 'bip01_r_finger1', 'bip01_l_finger1', 'bip01_r_finger11'


class Meshes:
    """a gamedata mesh path -> the file the game loads: the weapon pack's (tools/gra, its mods in MO2) over vanilla's
    unpacked meshes"""

    def __init__(self, vanilla):
        self.vanilla = vanilla
        self._pack = None

    def pack(self):
        if self._pack is None:
            sys.path.insert(0, os.path.join(HERE, '..', 'gra'))
            try:
                import build_pack
                self._pack = {k: v[1] for k, v in build_pack.manifest().items() if k.startswith('meshes/')}
            except (ImportError, AssertionError, OSError) as e:
                print(f'(no weapon pack meshes: {e})', file=sys.stderr)
                self._pack = {}
        return self._pack

    def find(self, vis):
        rel = 'meshes/' + vis.lower().replace('\\', '/').strip()
        if not rel.endswith('.ogf'):
            rel += '.ogf'
        if rel in self.pack():
            return self.pack()[rel], 'pack'
        p = os.path.join(self.vanilla, *rel.split('/'))
        return (p, 'van') if os.path.exists(p) else (None, None)


class Rig:
    def __init__(self, meshes):
        body, _ = meshes.find(BODY)
        anims = os.path.join(meshes.vanilla, *('meshes/' + ANIMS).split('/'))
        self.B = xr.load_bones(body)
        self.body_path = body
        self.idx = {b[0]: i for i, b in enumerate(self.B)}
        _, parts, self.defs = xr.omf_params(anims)
        self.part_of = {}
        for pi, (pn, bl) in enumerate(parts):
            for bn in bl:
                self.part_of[self.idx[bn.lower()]] = pi
        self.M = xr.load_motions(anims, lambda n: n.startswith(('norm_', 'cr_', 'cl_')))

    def pose(self, torso, legs, ft=0.25, fl=0.25):
        """model-space bone matrices: the torso motion at phase ft (0..1) on the upper body, the legs one at fl"""
        mt, ml = self.M[torso], self.M[legs]; W = [None] * len(self.B)
        for i, b in enumerate(self.B):
            m = mt if self.part_of.get(i, 0) >= 1 else ml
            f = int((ft if m is mt else fl) * (m.length - 1))
            R, T = m.bones[i]
            L = xr.qmat(R[min(f, len(R) - 1)], T[min(f, len(T) - 1)])
            W[i] = L if b[1] == '' else L @ W[self.idx[b[1]]]
        return W

    def hold(self, W, one_hand=True):
        """the engine's hold frame: origin at the right index finger, z towards the left hand bone, y up off the finger"""
        mR = W[self.idx[HAND_R]]; mL = W[self.idx[HAND_R2 if one_hand else HAND_L]]
        D = mL[3, :3] - mR[3, :3]; D /= np.linalg.norm(D)
        R = np.cross(mR[1, :3], D); N = np.cross(D, R); N /= np.linalg.norm(N)
        X = np.eye(4); X[0, :3] = R; X[1, :3] = N; X[2, :3] = D; X[3, :3] = mR[3, :3]
        return X

    def palm(self, W, side):
        w = W[self.idx[f'bip01_{side}_hand']][3, :3]
        f = (W[self.idx[f'bip01_{side}_finger1']][3, :3] + W[self.idx[f'bip01_{side}_finger2']][3, :3]) / 2
        return (w + f) / 2


def vec(v):
    """an ltx vector; anything unreadable (missing, a macro) counts as 0, 0, 0"""
    try:
        x = [float(t) for t in (v or '').replace(' ', ',').split(',') if t != ''][:3]
        return x if len(x) == 3 else [0, 0, 0]
    except ValueError:
        return [0, 0, 0]


def offset(pos, ori):
    """the section's position/orientation as the engine builds it (setHPB of degrees, then translate_over)"""
    O = xr.hpb(*np.radians(vec(ori))); O[3, :3] = vec(pos)
    return O
