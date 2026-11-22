r"""Spectrum-X HUD rig, shared by build_hud.py, check_hud.py and preview_hud.py (Blender 4.5 + blender-xray).

What it holds:
  - the hands (wpn_hand_01.ogf) and their base pose: right arm = the PM's idle frame 0 (seen through the PM's HUD
    offsets), left arm = the Veles' idle frame 0 (through the detector's offsets), both moved to our hud section's
    offsets (the PM's);
  - the probe (on lead_gun, where the PM sits) and the tablet (on l_hand, where the Veles sits), from the bakes;
  - pose building: two-bone IK for each arm (shoulder fixed, elbow on the base pose's side), the hand put exactly
    where an animation wants it, fingers kept relative to the hand with per-bone local rotations (the grips);
  - numpy skinning of the hands mesh (the same linear blend the engine does), BVH helpers to measure how deep a point
    is inside the probe / tablet / hands.
Spaces: "arm" = the hands armature, "cam" = HUD camera space in Blender axes (x right, y forward, z up):
cam = OURS @ arm. X-Ray bone frame of a pose matrix M: M @ K."""
import bpy, os, math
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
from xr_space import offset_b
from io_scene_xray.formats.motions.const import MATRIX_BONE, MATRIX_BONE_INVERTED

PM_HANDS = ((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15))          # [wpn_pm_hud] hands_position / orientation
DET_HANDS = ((0.05, -0.1895, -0.1), (2.0, 2.0, 0.0))           # [detector_base_hud]
PM_ITEM = ((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))   # [wpn_pm_hud] item_*
DET_ITEM = ((-0.078949, 0.039172, -0.019197), (320.606964, -194.089020, -186.572464))  # [detector_advanced_hud]
PROBE_SCALE = 0.20        # Tripo units -> metres: probe 20 cm long
TABLET_SCALE = 0.20       # tablet 14 cm tall
TABLET_SHIFT_X = 0.030    # in the Veles frame: toward the fingers, the thumb rests on the left bumper
# the screen plane on the glass, tablet's own coords (x down, y right, z out of the glass): x0, x1, y0, y1, z
SCREEN = (-0.383, 0.042, -0.171, 0.171, 0.0394 + 0.0012)
# button tops, tablet's own coords (found on the high-poly's height map, as tablet_decal.py does)
BUTTONS = {"menu": (0.1099, -0.1424, 0.0576), "back": (0.1568, -0.1036, 0.0599), "up": (0.1003, 0.0, 0.0587),
           "left": (0.1306, -0.0406, 0.0597), "right": (0.1306, 0.0404, 0.0596), "down": (0.1630, 0.0, 0.0605)}

K = MATRIX_BONE_INVERTED.to_4x4()      # pose_bone.matrix @ K = X-Ray bone frame (Blender axes)
KI = MATRIX_BONE.to_4x4()
OFF_R = offset_b(*PM_HANDS); OFF_L = offset_b(*DET_HANDS); OURS = OFF_R
ITEM_OFF = offset_b(*PM_ITEM); DET_OFF = offset_b(*DET_ITEM)
CR = OURS.inverted() @ OFF_R; CL = OURS.inverted() @ OFF_L

is_left = lambda n: n.startswith("l_") or n.startswith("bip01_l_")
is_right = lambda n: n.startswith("r_") or n.startswith("bip01_r_") or n == "lead_gun"
FINGERS = {s: [[("bip01_%s_finger%d" % (s, f)) + ("%d" % j if j else "") for j in (0, 1, 2)] for f in (1, 2, 3, 4)]
           for s in "lr"}
for s in "lr":
    FINGERS[s].insert(0, ["%s_finger0" % s, "%s_finger01" % s, "%s_finger02" % s])   # the thumb first


def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]


def load_low(blend, name):
    with bpy.data.libraries.load(blend) as (src, dst):
        dst.objects = ["LOW"]
    o = dst.objects[0]; o.name = name; bpy.context.scene.collection.objects.link(o)
    o.data = o.data.copy(); o.data.name = name
    return o


def mesh_arrays(obj):
    v = np.array([x.co[:] for x in obj.data.vertices], dtype=np.float64)
    tris = []
    for p in obj.data.polygons:
        vs = list(p.vertices)
        for i in range(1, len(vs) - 1):
            tris.append((vs[0], vs[i], vs[i + 1]))
    return v, np.array(tris, dtype=np.int64)


def bvh_of(verts, tris):
    return BVHTree.FromPolygons([Vector(x) for x in verts], [tuple(t) for t in tris], all_triangles=True)


_RAYS = (Vector((0.577, 0.577, 0.577)), Vector((-0.6, 0.3, -0.742)).normalized())


def _odd(bvh, p, d):
    n, o = 0, p.copy()
    for _ in range(16):
        loc, nrm, idx, dist = bvh.ray_cast(o, d)
        if loc is None:
            break
        n += 1; o = loc + d * 1e-5
    return n % 2 == 1


def depths(bvh, pts, reach=0.05):
    """per point: > 0 = depth inside the mesh, 0 = outside or farther than reach. Inside = the nearest face's
    normal says so and two rays cross the surface an odd number of times (the meshes are closed)."""
    out = np.zeros(len(pts))
    for i, p in enumerate(pts):
        p = Vector(p)
        loc, n, idx, d = bvh.find_nearest(p, reach)
        if loc is not None and (p - loc).dot(n) < 0 and _odd(bvh, p, _RAYS[0]) and _odd(bvh, p, _RAYS[1]):
            out[i] = d
    return out


def apply_m(M, pts):
    A = np.array(M, dtype=np.float64)
    return pts @ A[:3, :3].T + A[:3, 3]


class Rig:
    def __init__(self, G, A):
        self.G, self.A = G, A
        scn = bpy.context.scene
        self.H = next(o for o in imp_ogf(G + r"\anomaly_weapons\hands\wpn_hand_01.ogf") if o.type == "ARMATURE")
        H = self.H; H.name = "hands"
        for o in list(bpy.data.objects):
            if o.type == "MESH" and o.parent == H:
                o.name = "hands_mesh"; self.hands_mesh = o
        bpy.context.view_layer.objects.active = H
        for f, parts in (("wpn_hand_pm_hud_animation.omf", True), ("dev_hand_detector_2_hud_animation.omf", False)):
            bpy.ops.xray_import.omf(directory=G + r"\anomaly_weapons\hud_hands_animation", files=[{"name": f}],
                                    import_motions=True, import_bone_parts=parts, add_to_motion_list=False)
        H.animation_data_create()
        self.BONES = [pb.name for pb in H.pose.bones]
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in H.data.bones}
        self.children = {b.name: [c.name for c in b.children] for b in H.data.bones}
        self.rest = {b.name: b.matrix_local.copy() for b in H.data.bones}
        r = self.sample("pm_idle", 0.0); l = self.sample("d2_idle", 0.0)
        self.base = {b: (CL @ l[b]) if is_left(b) else (CR @ r[b]) for b in self.BONES}
        for a in list(bpy.data.actions):
            if a.users == 0 or a.name.startswith(("pm_", "d2_")):
                pass
        H.animation_data.action = None
        self._skin_setup()
        self._items()

    # ------------------------------------------------------------------ vanilla poses
    def sample(self, act, frame):
        H, scn = self.H, bpy.context.scene
        H.animation_data.action = bpy.data.actions[act]
        if hasattr(H.animation_data, "action_slot") and bpy.data.actions[act].slots:
            H.animation_data.action_slot = bpy.data.actions[act].slots[0]
        fi = int(math.floor(frame)); scn.frame_set(fi, subframe=frame - fi)
        return {pb.name: pb.matrix.copy() for pb in H.pose.bones}

    # ------------------------------------------------------------------ skinning (numpy, as the engine)
    def _skin_setup(self):
        o = self.hands_mesh
        self.hv, self.htris = mesh_arrays(o)
        to_arm = self.H.matrix_world.inverted() @ o.matrix_world
        self.hv = apply_m(to_arm, self.hv)
        gname = {g.index: g.name for g in o.vertex_groups}
        self.skin_bones = [b for b in self.BONES]
        bi = {b: i for i, b in enumerate(self.skin_bones)}
        n = len(o.data.vertices); W = np.zeros((n, len(self.skin_bones)))
        for v in o.data.vertices:
            for g in v.groups:
                b = gname.get(g.group)
                if b in bi: W[v.index, bi[b]] += g.weight
        s = W.sum(1, keepdims=True); s[s == 0] = 1; W /= s
        self.W = W
        self.dom = np.array([self.skin_bones[i] for i in W.argmax(1)])
        self.vside = np.array(["l" if is_left(b) else "r" for b in self.dom])
        self.rest_inv = np.stack([np.array(self.rest[b].inverted(), dtype=np.float64) for b in self.skin_bones])

    def skin(self, pose):
        """hands mesh vertices in arm space for a pose {bone: arm matrix}"""
        P = np.stack([np.array(pose[b], dtype=np.float64) for b in self.skin_bones]) @ self.rest_inv   # (B,4,4)
        hv = np.c_[self.hv, np.ones(len(self.hv))]
        used = np.where(self.W.sum(0) > 0)[0]
        out = np.zeros((len(self.hv), 3))
        for bi in used:
            w = self.W[:, bi]; m = w > 0
            out[m] += w[m, None] * (hv[m] @ P[bi].T)[:, :3]
        return out

    # ------------------------------------------------------------------ the device in hand space
    def _items(self):
        G, A = self.G, self.A
        pm_objs = imp_ogf(G + r"\anomaly_weapons\wpn_pm\wpn_pm_hud.ogf")
        self.pm_objs = pm_objs
        self.pm_arm = next(o for o in pm_objs if o.type == "ARMATURE")
        pm_v = np.array([v.co[:] for o in pm_objs if o.type == "MESH" and o.name.endswith("00") for v in o.data.vertices])
        band = pm_v[(pm_v[:, 2] < -0.02) & (pm_v[:, 2] > -0.06)]
        pm_grip = Vector(band.mean(0)); pm_grip.z = -0.005
        self.grip_item = pm_grip.copy()
        self.probe = load_low(os.path.join(A, "bake", "pistol_blender", "pistol_bake.blend"), "probe")
        self.tablet = load_low(os.path.join(A, "bake", "tablet_blender", "tablet_bake.blend"), "tablet")
        pv = np.array([v.co[:] for v in self.probe.data.vertices])
        gb = pv[(pv[:, 2] < -0.10) & (pv[:, 2] > -0.20) & (pv[:, 1] > -0.05)]
        pg = Vector((gb[:, 0].mean(), gb[:, 1].mean(), -0.05))
        R180 = Matrix.Rotation(math.pi, 4, "Z")
        self.P_probe = Matrix.Translation(pm_grip) @ R180 @ Matrix.Scale(PROBE_SCALE, 4) @ Matrix.Translation(-pg)
        self.probe.data.transform(self.P_probe); self.probe.matrix_world = Matrix.Identity(4)
        # cable plug of the probe (end of the strain relief) and its direction, item space
        self.plug_p = self.P_probe @ Vector((0.0, 0.37, 0.325)); self.plug_d = (R180 @ Vector((0, 1, 0))).normalized()
        self.lens_item = self.P_probe @ Vector((0.0, -0.5, 0.29))
        tv = np.array([v.co[:] for v in self.tablet.data.vertices])
        A_rot = Matrix(((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
        self.tab_c = ((tv[:, 0].min() + tv[:, 0].max()) / 2, (tv[:, 1].min() + tv[:, 1].max()) / 2, tv[:, 2].min())
        cx, cy, zb = self.tab_c
        self.A_tab = Matrix.Translation(Vector((TABLET_SHIFT_X, 0.0, 0.004))) @ A_rot @ Matrix.Scale(TABLET_SCALE, 4) @ Matrix.Translation(Vector((-cx, -cy, -zb)))
        con = tv[(tv[:, 0] > 0.255) & (np.abs(tv[:, 1]) < 0.06)]
        self.conn_t = Vector((0.29, con[:, 1].mean(), con[:, 2].mean())) if len(con) else Vector((0.29, 0, 0))
        # collision meshes: probe in item space, tablet in "detector space" (A_tab applied)
        self.pv_item, self.ptris = mesh_arrays(self.probe)
        tv_raw, self.ttris = mesh_arrays(self.tablet)
        self.tv_det = apply_m(self.A_tab, tv_raw)
        self.tv_raw = tv_raw
        self.probe_bvh = bvh_of(self.pv_item, self.ptris)
        self.tablet_bvh = bvh_of(self.tv_det, self.ttris)

    def shift_probe(self, off):
        """move the probe in item space (the grip into the palm, not through it)"""
        T = Matrix.Translation(Vector(off))
        self.P_probe = T @ self.P_probe; self.probe.data.transform(T)
        self.plug_p = T @ self.plug_p; self.lens_item = T @ self.lens_item; self.grip_item = T @ self.grip_item
        self.pv_item = apply_m(T, self.pv_item); self.probe_bvh = bvh_of(self.pv_item, self.ptris)

    def shift_tablet(self, off):
        """move the tablet in detector space"""
        self.A_tab = Matrix.Translation(Vector(off)) @ self.A_tab
        self.tv_det = apply_m(self.A_tab, self.tv_raw); self.tablet_bvh = bvh_of(self.tv_det, self.ttris)

    def fit_device(self, side, bones, span=0.012, step=0.002, tol=0.0008):
        """the smallest move of the device (a grid in its own frame) that leaves the vertices of bones (the palm) no
        deeper than tol in it; returns the move"""
        pose = self.pose_of(fingers={})
        hv = self.skin(pose)
        pts0 = apply_m(self.device_frame(side, pose).inverted(), hv[np.isin(self.dom, bones)])
        bvh = self.device_bvh(side)
        best = None
        g = np.arange(-span, span + 1e-9, step)
        for dx in g:
            for dy in g:
                for dz in g:
                    off = np.array((dx, dy, dz)); n = np.linalg.norm(off)
                    if best is not None and n >= best[0]:
                        continue
                    d = depths(bvh, pts0 - off).max()
                    if d <= tol:
                        best = (n, off)
        if best is None:
            return None
        return tuple(best[1])

    # frames of the two devices for a pose (arm space)
    def item_arm(self, pose):
        return pose["lead_gun"] @ K @ ITEM_OFF

    def det_arm(self, pose):
        return pose["l_hand"] @ K @ DET_OFF

    def tab_point(self, p_raw):
        """a point in the tablet's own (Tripo) coords -> detector space"""
        return self.A_tab @ Vector(p_raw)

    # ------------------------------------------------------------------ pose building
    def with_hand(self, pose, side, hand_arm, pole=None):
        """two-bone IK: the arm's hand to hand_arm (arm space), shoulder fixed; children kept relative"""
        B = self.base
        ua, fa, hd, tw = "%s_upperarm" % side, "%s_forearm" % side, "%s_hand" % side, "%s_forearm_twist" % side
        S = B[ua].to_translation(); E0 = B[fa].to_translation(); W0 = B[hd].to_translation()
        L1, L2 = (E0 - S).length, (W0 - E0).length
        W = hand_arm.to_translation()
        d = (W - S).length
        if d > (L1 + L2) * 0.999:
            W = S + (W - S).normalized() * (L1 + L2) * 0.999; d = (W - S).length
            self.clamped = getattr(self, "clamped", 0) + 1
        u = (W - S).normalized()
        if pole is None:
            axis0 = (W0 - S).normalized()
            pole = (E0 - S) - axis0 * (E0 - S).dot(axis0)
        v = (pole - u * pole.dot(u)).normalized()
        a = (L1 * L1 - L2 * L2 + d * d) / (2 * d)
        h = math.sqrt(max(L1 * L1 - a * a, 0.0))
        E = S + u * a + v * h

        def frame(dvec, n):
            dvec = dvec.normalized(); n = (n - dvec * n.dot(dvec)).normalized()
            return Matrix((dvec, n, dvec.cross(n))).transposed()
        n0 = (E0 - S).cross(W0 - E0); n1 = (E - S).cross(W - E)
        if n1.length < 1e-6: n1 = n0
        R_ua = frame(E - S, n1) @ frame(E0 - S, n0).transposed()
        R_fa = frame(W - E, n1) @ frame(W0 - E0, n0).transposed()
        out = dict(pose)
        out[ua] = Matrix.Translation(S) @ R_ua.to_4x4() @ Matrix.Translation(-S) @ B[ua]
        out[fa] = Matrix.Translation(E) @ R_fa.to_4x4() @ Matrix.Translation(-E0) @ B[fa]
        hand = hand_arm.copy(); hand.translation = W
        out[hd] = hand
        # the twist bone takes half of the hand's roll about the forearm
        rel0 = (B[fa].inverted() @ B[hd]).to_quaternion(); rel1 = (out[fa].inverted() @ hand).to_quaternion()
        dq = rel1 @ rel0.inverted()
        ax = (B[fa].inverted() @ W0).normalized()
        q_tw = Quaternion((dq.w, *(ax * Vector(dq[1:]).dot(ax)))).normalized()
        ang = 2 * math.atan2(Vector(q_tw[1:]).dot(ax), q_tw.w)
        tl = B[fa].inverted() @ B[tw]
        out[tw] = out[fa] @ Matrix.Rotation(ang * 0.5, 4, ax) @ tl
        self._carry(out, hd)
        if side == "r":
            out["lead_gun"] = hand @ B[hd].inverted() @ B["lead_gun"]
        return out

    def _carry(self, out, root):
        """children of root kept as in the base pose (then the grips' local rotations, if any)"""
        B = self.base
        for c in self.children[root]:
            out[c] = out[root] @ B[root].inverted() @ B[c] @ self.local_rot.get(c, Matrix.Identity(4))
            self._carry(out, c)

    local_rot = {}

    def basis_of(self, pose):
        """arm-space pose matrices -> pose_bone.matrix_basis"""
        res = {}
        for pb in self.H.pose.bones:
            b = pb.bone
            if b.parent:
                rest_rel = b.parent.matrix_local.inverted() @ b.matrix_local
                res[pb.name] = rest_rel.inverted() @ pose[b.parent.name].inverted() @ pose[pb.name]
            else:
                res[pb.name] = b.matrix_local.inverted() @ pose[pb.name]
        return res

    def show(self, pose):
        """put a pose on the armature (for renders) and the devices where they go"""
        self.H.animation_data.action = None
        bas = self.basis_of(pose)
        for pb in self.H.pose.bones:
            pb.matrix_basis = bas[pb.name]
        self.H.matrix_world = OURS
        self.probe.matrix_world = OURS @ self.item_arm(pose)
        self.tablet.matrix_world = OURS @ self.det_arm(pose) @ self.A_tab
        bpy.context.view_layer.update()

    # ------------------------------------------------------------------ grips
    def device_frame(self, side, pose):
        return self.det_arm(pose) if side == "l" else self.item_arm(pose)

    def device_bvh(self, side):
        return self.tablet_bvh if side == "l" else self.probe_bvh

    def finger_depth(self, side, bones, fingers, other=None):
        """deepest point of the vertices of bones inside the hand's own device (and other: [(bvh, frame_fn)])"""
        pose = self.pose_of(fingers=fingers)
        hv = self.skin(pose)
        m = np.isin(self.dom, bones)
        if not m.any():
            return 0.0
        pts = apply_m(self.device_frame(side, pose).inverted(), hv[m])
        d = depths(self.device_bvh(side), pts).max()
        return d

    def curl_axes(self, side, chain, toward):
        """per joint of a finger: the flexion axis in the bone's own frame. Fingers 1-4 bend about the hand's knuckle
        line (index to little finger), the thumb about the normal of the plane of its bone and the point toward;
        the sign makes a positive angle move the tip toward the device (the palm's side)."""
        B = self.base; axes = []
        lat = (B["bip01_%s_finger1" % side].to_translation() - B["bip01_%s_finger4" % side].to_translation()).normalized()
        tip = lambda i: B[chain[-1]].to_translation()
        for i, b in enumerate(chain):
            J = B[b].to_translation()
            nxt = B[chain[i + 1]].to_translation() if i + 1 < len(chain) else J + (J - B[chain[i - 1]].to_translation())
            s = (nxt - J).normalized()
            if b.endswith(("finger0", "finger01", "finger02")):
                n = toward - J; n = (n - s * n.dot(s)).normalized()
                a = s.cross(n).normalized()
            else:
                a = (lat - s * lat.dot(s)).normalized()
                # +angle must move the segment's end toward the device
                end = J + s * 0.03
                moved = J + Quaternion(a, 0.2) @ (end - J)
                if (toward - moved).length > (toward - end).length:
                    a = -a
            axes.append(B[b].to_3x3().inverted() @ a)
        return axes

    def solve_curl(self, side, chain, fingers, toward, tol=0.0012, lim=((-40, 85), (-40, 100), (-40, 80)), free=25,
                   close=True):
        """a finger: first opened, tip to root, until each bone's own vertices are out of the device (no deeper than
        tol), then closed, root to tip, as far as each joint goes before the rest of the finger touches; a joint that
        meets nothing up to its limit is left at `free` degrees more (a relaxed curl)"""
        axes = self.curl_axes(side, chain, toward)
        ang = {b: 0 for b in chain}

        def rot(f, b, deg):
            f = dict(f); f[b] = fingers.get(b, Matrix.Identity(4)) @ Matrix.Rotation(math.radians(deg), 4, axes[chain.index(b)])
            return f

        def cur(over=None):
            f = dict(fingers)
            for b in chain:
                f = rot(f, b, (over or {}).get(b, ang[b]))
            return f
        for k in range(0, -lim[0][0] + 1, 2):       # open: the whole finger flatter until it is out
            for i, b in enumerate(chain):
                ang[b] = max(-k, lim[min(i, 2)][0])
            if self.finger_depth(side, chain, cur()) <= tol:
                break
        for i, b in enumerate(chain if close else []):     # close
            hi = lim[min(i, 2)][1]; start = ang[b]; best = None
            for deg in range(start + 2, hi + 1, 2):
                if self.finger_depth(side, chain[i:], cur({b: deg})) > tol:
                    best = deg - 2; break
            ang[b] = best if best is not None else min(start + free, hi)
        self.grip_log.append(" ".join("%s %+d" % (b, ang[b]) for b in chain))
        return cur()

    grip_log = []

    def tip_local(self, bone):
        """the vertex of a finger's last bone farthest from its head, in that bone's frame (base pose)"""
        B = self.base
        hv = self.skin(self.pose_of(fingers={}))[self.dom == bone]
        head = np.array(B[bone].to_translation())
        k = np.argmax(np.linalg.norm(hv - head, axis=1))
        return B[bone].inverted() @ Vector(hv[k])

    def chain_to(self, side, fingers, joints, eff_bone, eff_local, target_dev, iters=40, step=6.0):
        """CCD: joints turned (each about its head, as a local rotation) until eff_local of eff_bone reaches a point
        given in the device's frame (detector / item space)"""
        fingers = dict(fingers)
        for _ in range(iters):
            for b in reversed(joints):
                pose = self.pose_of(fingers=fingers)
                T = self.device_frame(side, pose) @ Vector(target_dev)
                P = pose[eff_bone] @ Vector(eff_local)
                J = pose[b].to_translation()
                v1, v2 = (P - J), (T - J)
                if v1.length < 1e-6 or v2.length < 1e-6: continue
                r = v1.rotation_difference(v2)
                r = Quaternion(r.axis, min(r.angle, math.radians(step)))
                wr = pose[b].to_3x3().normalized()
                fingers[b] = fingers.get(b, Matrix.Identity(4)) @ (wr.inverted() @ r.to_matrix() @ wr).to_4x4()
        pose = self.pose_of(fingers=fingers)
        err = (pose[eff_bone] @ Vector(eff_local) - self.device_frame(side, pose) @ Vector(target_dev)).length
        self.grip_log.append("%s -> err %.1f mm" % (eff_bone, err * 1000))
        return fingers

    def pose_of(self, r_hand=None, l_hand=None, fingers=None):
        """the base pose with each hand moved to an arm-space matrix (None: as in the base) and finger rotations"""
        saved = self.local_rot
        if fingers is not None:
            self.local_rot = fingers
        p = dict(self.base)
        p = self.with_hand(p, "r", r_hand if r_hand is not None else self.base["r_hand"])
        p = self.with_hand(p, "l", l_hand if l_hand is not None else self.base["l_hand"])
        self.local_rot = saved
        return p


def setup_grips(R, log=print):
    """fit the devices into the hands, then the grips: the left hand's fingers on the tablet's back, the thumb on
    the front left bumper beside the menu button (rest) or on it (press); the right hand round the probe's grip.
    Returns (fingers at rest, fingers with the thumb pressing)."""
    offp = R.fit_device("r", ["r_hand", "bip01_r_finger2", "bip01_r_finger3", "bip01_r_finger4"], span=0.016)
    R.shift_probe(offp or (0, 0, 0))
    offt = R.fit_device("l", ["l_hand"])
    R.shift_tablet(offt or (0, 0, 0))
    log("FIT probe %s tablet %s" % (offp, offt))
    b0 = R.pose_of(fingers={})
    tc = R.det_arm(b0) @ R.tab_point((-0.05, 0, 0.0))
    pg = R.item_arm(b0) @ R.grip_item
    f = {}
    for ch in FINGERS["l"][1:]:
        f = R.solve_curl("l", ch, f, tc)
    th = FINGERS["l"][0]
    tip = R.tip_local(th[2])
    f = R.chain_to("l", f, th[:2], th[2], Vector((0, 0, 0)), R.tab_point((0.12, -0.30, 0.04)))
    rest = R.chain_to("l", f, th[1:], th[2], tip, R.tab_point((0.11, -0.215, 0.125)))
    rest = R.solve_curl("l", th, rest, tc, close=False)
    mx, my, mz = BUTTONS["menu"]
    # the pad on the menu button: the nail's tip goes a little past it along the thumb (to the right on the panel),
    # then the whole press is lifted off the panel (along the glass' normal) until the thumb is not in it
    for k in range(16):
        lift = 0.005 * k
        # the last joint over the left bumper's front (so the thumb comes over it, not through it), then the tip
        press = R.chain_to("l", rest, th[:2], th[2], Vector((0, 0, 0)), R.tab_point((mx + 0.005, -0.245, 0.13 + lift)))
        press = R.chain_to("l", press, th[2:], th[2], tip, R.tab_point((mx + 0.005, my + 0.03, mz + 0.02 + lift)))
        if R.finger_depth("l", th, press) <= 0.0015:
            break
    R.grip_log.append("press lifted %.1f mm" % (k * 0.005 * TABLET_SCALE * 1000))
    for ch in FINGERS["r"]:
        rest = R.solve_curl("r", ch, rest, pg)
        press = dict(press); press.update({b: rest[b] for b in ch if b in rest})
    for b in rest:
        if b not in press: press[b] = rest[b]
    log("GRIP " + " | ".join(R.grip_log))
    return rest, press
