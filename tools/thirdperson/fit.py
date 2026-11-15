"""How well a gun's world model sits in the actor's hands: the distance from each palm to the nearest point of the
model, in the holds of the section's animation_slot (aim_0 aiming, aim_1 standing, aim_2 walking, aim_3 running)."""
import numpy as np

import rig as rigmod
import xr

HOLDS = {'aim_0': 'idle_0', 'aim_1': 'idle_0', 'aim_2': 'walk_fwd_0', 'aim_3': 'run_fwd_0'}
ADDON_BONES = ('wpn_scope', 'wpn_silencer', 'wpn_launcher')


class Fitter:
    def __init__(self, rig, meshes):
        self.rig, self.meshes = rig, meshes
        self._holds, self._verts = {}, {}

    def holds(self, slot, base='norm'):
        """{hold: (gun frame without the offset, left palm, right palm)}"""
        k = (slot, base)
        if k not in self._holds:
            out = {}
            for a, legs in HOLDS.items():
                t = f'{base}_torso_{slot}_{a}'
                if t in self.rig.M:
                    W = self.rig.pose(t, f'{base}_{legs}')
                    out[a] = (self.rig.hold(W), self.rig.palm(W, 'l'), self.rig.palm(W, 'r'))
            self._holds[k] = out
        return self._holds[k]

    def verts(self, vis):
        """the model's points without its addons (scope, silencer, launcher: often hidden)"""
        if vis not in self._verts:
            p, origin = self.meshes.find(vis)
            V = None
            if p:
                hide = [i for i, n in enumerate(xr.bone_names(p)) if n in ADDON_BONES]
                pts = [P[~np.isin(bn[:, 0], hide)] for P, bn, w, tri in xr.load_skin(p)]
                pts = [x for x in pts if len(x)]
                V = np.concatenate(pts) if pts else None
            self._verts[vis] = (V, origin)
        return self._verts[vis]

    def fit(self, vis, pos, ori, slot):
        """(mesh origin van|pack, {hold: (left gap, right gap, left support) in metres}) or None without a model"""
        V, origin = self.verts(vis)
        if V is None:
            return None
        return origin, measure(V, rigmod.offset(pos, ori), self.holds(int(slot)))


def measure(V, O, holds):
    V4 = np.c_[V, np.ones(len(V))]
    res = {}
    for a, (X, pl, pr) in holds.items():
        Wv = (V4 @ (O @ X))[:, :3]
        res[a] = (float(np.linalg.norm(Wv - pl, axis=1).min()), float(np.linalg.norm(Wv - pr, axis=1).min()),
                  support(V, O @ X, pl))
    return res


def support(V, T, palm):
    """how high the gun's underside is above the left palm (metres, in the gun's own up): the lowest point of the
    model within 2.5 cm along the barrel and 4 cm sideways of the palm. Vanilla's guns in their own holds: 4-6 cm (the
    palm's centre lies inside the hand). None: no part of the gun over the palm (the hand holds the air)"""
    q = (np.append(palm, 1) @ np.linalg.inv(T))[:3]
    near = V[(np.abs(V[:, 2] - q[2]) < 0.025) & (np.abs(V[:, 0] - q[0]) < 0.04)]
    return float(near[:, 1].min() - q[1]) if len(near) else None


def gaps(res):
    """the section's gaps for the verdict: the better of standing and aiming, left and right"""
    gl = min(res[a][0] for a in ('aim_0', 'aim_1') if a in res)
    gr = min(res[a][1] for a in ('aim_0', 'aim_1') if a in res)
    return gl, gr


SUPPORT = 0.048  # vanilla's rifles (slot 2): median 4.8 cm, 80% within 3.8-6.8
SUPPORT_SLOTS = ('2', '3', '9')  # holds with the left hand under a fore-end (8: on the magazine, 1: on the right hand)


def bad(res, slot):
    """why the gun is off the hands, or '': right palm > 5 cm from the gun; (two-handed holds) left palm > 7 cm; (left
    hand under a fore-end) no part of the gun over the left palm, or the fore-end > 8 cm above it. A low support
    (< 2 cm, the palm in the gun) is often a fore grip, a torch or a drum under the fore-end: look at a picture"""
    gl, gr = gaps(res)
    h = res['aim_1'][2] if 'aim_1' in res else None
    if gr > 0.05:
        return 'right hand off'
    if str(slot) == '1':
        return ''
    if gl > 0.07:
        return 'left hand off'
    if str(slot) in SUPPORT_SLOTS:
        if h is None:
            return 'left hand holds air'
        if h > 0.08:
            return 'left hand under the gun'
    return ''
