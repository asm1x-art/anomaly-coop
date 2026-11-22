r"""Spectrum-X HUD rig, shared by build_hud.py, hud_anims.py and the pose previews (Blender 4.5 + blender-xray).

What it holds:
  - the hands (wpn_hand_01.ogf: the armature the animations are baked on) and their base pose: right arm = the PM's
    idle frame 0 (the probe-pistol's grip), left arm = the vanilla PDA's idle frame 0 (a landscape device held by its
    lower corners, thumbs on the side bezels; LEFT_GRIP), both moved to our hud section's offsets (the PM's);
  - the probe (on lead_gun, where the PM sits) and the landscape tablet (make_tablet.py), the tablet held in the left
    hand round its left side edge (SIDE_GRIP: palm round the edge, fingers on the back, thumb up the front bezel);
  - more hands meshes for collisions (HAND_SETS: the thick-sleeved exoskeleton arms too), so the grips clear both;
  - pose building: two-bone IK for each arm (shoulder fixed, elbow on the base pose's side), the hand put exactly
    where an animation wants it, fingers kept relative to the hand with per-bone local rotations (the grips);
    the right hand mirrored from the left about the tablet's middle (the two-handed hold);
  - the thumb laid out straight (thumb_aim / thumb_lay: anatomical axes from vanilla animations), moved onto a
    button by a small search with a cost on odd angles (thumb_place);
  - numpy skinning of the hands meshes (the engine's linear blend), BVH helpers to measure how deep a point is inside
    the probe / tablet.
Spaces: "arm" = the hands armature, "cam" = HUD camera space in Blender axes (x right, y forward, z up):
cam = OURS @ arm. X-Ray bone frame of a pose matrix M: M @ K. "det" = the tablet's frame in the left hand (the PDA's
frame: x up the screen, y to the left, z out of the glass); A_tab: tablet coords -> det."""
import bpy, os, math, json
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
from xr_space import offset_b
from io_scene_xray.formats.motions.const import MATRIX_BONE, MATRIX_BONE_INVERTED

ASSETS = r"X:\coop\assets\spectrum-x"
PM_HANDS = ((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15))          # [wpn_pm_hud] hands_position / orientation
# the left hand's base grip: a vanilla device held in both hands, the tablet put in that device's frame.
# The PDA's (landscape, held by its lower corners): its arm, fingers and thumb are the starting point; where the hand
# sits on the tablet is SIDE_GRIP below.
# (The binoculars' grip, turned a quarter, was tried too: forearms come in level from the sides like holding
# binoculars, and the thumb has to hook its last joint ~70 degrees to reach the bezel.)
LEFT_GRIP = dict(omf="wpn_hand_pda_hud_animation.omf", act="hands_idle",
                 hands=((-0.005, -0.11, 0.1), (0.0, 0.0, 0.0)), item=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
                 # tablet coords -> the PDA's frame (Blender axes): down -> -x, right -> -y, out of the glass -> +z
                 axes=((-1, 0, 0), (0, -1, 0), (0, 0, 1)))
PM_ITEM = ((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))   # [wpn_pm_hud] item_*
PROBE_SCALE = 0.20        # Tripo units -> metres: probe 20 cm long
TABLET_DIR = os.path.join(ASSETS, "bake", "tablet_v2")
TABLET_SCALE = 1.0        # the tablet is modelled in metres
# the one-hand grip, as one holds a book by its cover: the palm round the left side edge about mid-height, the four
# fingers flat on the back pointing right and alpha degrees up, the thumb straight up the front left bezel. The hand's
# own axes (wrist -> middle knuckle, the knuckle line, the palm's side) are measured on the base pose and turned onto
# these; palm = where the palm's centre goes (tablet coords: x down, y right, z out of the glass; the back is z = 0);
# wrap = degrees the palm is turned from the back toward the side edge (about the tablet's x).
# (The PDA's own hold, the tablet put where the PDA sits, was tried first: it holds the lower corner, the fingers
# curl under the bottom edge and the thumb only reaches a button by the corner bumper.)
SIDE_GRIP = dict(alpha=60.0, wrap=30.0, palm=(0.015, -0.100, -0.018))
# the thumb laid out straight up the bezel (thumb_aim): its root knuckle at mcp_y, lift over the bezel's front, the
# phalanges up with lean (toward the screen per unit up), the last joint bent flex degrees. Found by a search: the
# straightest thumb that clears the edge with the palm round it (the thumb then lies along the bezel's outer half).
THUMB_LAY = dict(mcp_y=-0.104, lift=0.004, lean=0.45, flex=40.0)
SLIDE_TWO_HAND = 0.017       # two hands: they hold the tablet this much lower on its edges (the thumbs then lie on P1, +)
HAND_SETS = ("wpn_hand_01.ogf", "wpn_hand_exo.ogf")
LAYOUT = json.load(open(os.path.join(TABLET_DIR, "tablet_layout.json")))
SCREEN = tuple(LAYOUT["screen"])       # x0, x1, y0, y1, z in the tablet's coords (x down, y right, z out)
BUTTONS = {k: tuple(v) for k, v in LAYOUT["buttons"].items()}

K = MATRIX_BONE_INVERTED.to_4x4()      # pose_bone.matrix @ K = X-Ray bone frame (Blender axes)
KI = MATRIX_BONE.to_4x4()
OFF_R = offset_b(*PM_HANDS); OFF_P = offset_b(*LEFT_GRIP["hands"]); OURS = OFF_R
ITEM_OFF = offset_b(*PM_ITEM)
CR = OURS.inverted() @ OFF_R; CP = OURS.inverted() @ OFF_P

is_left = lambda n: n.startswith("l_") or n.startswith("bip01_l_")
is_right = lambda n: n.startswith("r_") or n.startswith("bip01_r_") or n == "lead_gun"
other = lambda n: n.replace("bip01_l_", "bip01_R_").replace("bip01_r_", "bip01_l_").replace("bip01_R_", "bip01_r_") \
    if n.startswith("bip01_") else ("r_" + n[2:] if n.startswith("l_") else "l_" + n[2:] if n.startswith("r_") else n)
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


class HandSet:
    """one hands model's mesh for skinning (its own bind pose, the shared bone names)"""
    def __init__(self, name, arm, meshes):
        vs, ts, n0 = [], [], 0
        gw = []
        for o in meshes:
            v, t = mesh_arrays(o)
            vs.append(apply_m(arm.matrix_world.inverted() @ o.matrix_world, v)); ts.append(t + n0); n0 += len(v)
            gname = {g.index: g.name for g in o.vertex_groups}
            gw += [[(gname[g.group], g.weight) for g in x.groups] for x in o.data.vertices]
        self.name = name; self.hv = np.vstack(vs); self.htris = np.vstack(ts)
        self.bones = [b.name for b in arm.data.bones]
        bi = {b: i for i, b in enumerate(self.bones)}
        W = np.zeros((len(self.hv), len(self.bones)))
        for i, gs in enumerate(gw):
            for b, w in gs:
                if b in bi: W[i, bi[b]] += w
        s = W.sum(1, keepdims=True); s[s == 0] = 1; self.W = W / s
        self.dom = np.array([self.bones[i] for i in self.W.argmax(1)])
        self.rest_inv = np.stack([np.array(b.matrix_local.inverted(), dtype=np.float64) for b in arm.data.bones])
        self.used = np.where(self.W.sum(0) > 0)[0]

    def skin(self, pose):
        P = np.stack([np.array(pose[b], dtype=np.float64) for b in self.bones]) @ self.rest_inv
        hv = np.c_[self.hv, np.ones(len(self.hv))]
        out = np.zeros((len(self.hv), 3))
        for bi in self.used:
            w = self.W[:, bi]; m = w > 0
            out[m] += w[m, None] * (hv[m] @ P[bi].T)[:, :3]
        return out


class Rig:
    def __init__(self, G, A, hand_sets=HAND_SETS):
        self.G, self.A = G, A
        objs = imp_ogf(G + "\\anomaly_weapons\\hands\\" + hand_sets[0])
        self.H = next(o for o in objs if o.type == "ARMATURE")
        H = self.H; H.name = "hands"
        meshes = [o for o in objs if o.type == "MESH"]
        for i, o in enumerate(meshes): o.name = "hands_mesh" + ("" if not i else str(i))
        self.hands_mesh = meshes[0]
        bpy.context.view_layer.objects.active = H
        acts = {}
        for f, parts in (("wpn_hand_pm_hud_animation.omf", True), ("wpn_hand_pda_hud_animation.omf", False),
                         ("dev_hand_detector_2_hud_animation.omf", False), ("dev_hand_binocular_hud_animation.omf", False)):
            if f in acts: continue
            a0 = set(bpy.data.actions)
            bpy.ops.xray_import.omf(directory=G + r"\anomaly_weapons\hud_hands_animation", files=[{"name": f}],
                                    import_motions=True, import_bone_parts=parts, add_to_motion_list=False)
            acts[f] = [a for a in bpy.data.actions if a not in a0]
        self.left_act = next(a.name for a in acts[LEFT_GRIP["omf"]] if a.name.split(".")[0] == LEFT_GRIP["act"])
        H.animation_data_create()
        self.BONES = [pb.name for pb in H.pose.bones]
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in H.data.bones}
        self.children = {b.name: [c.name for c in b.children] for b in H.data.bones}
        self.rest = {b.name: b.matrix_local.copy() for b in H.data.bones}
        r = self.sample("pm_idle", 0.0); l = self.sample(self.left_act, 0.0)
        self.base = {b: (CP @ l[b]) if is_left(b) else (CR @ r[b]) for b in self.BONES}
        # the tablet's frame in the left hand = the vanilla device's frame (it hangs on lead_gun with its item offset)
        self.L2T = self.base["l_hand"].inverted() @ CP @ l["lead_gun"] @ K @ offset_b(*LEFT_GRIP["item"])
        self._thumb_axes(acts)
        H.animation_data.action = None
        self.sets = [HandSet(hand_sets[0], H, meshes)]
        for hs in hand_sets[1:]:
            ob = imp_ogf(G + "\\anomaly_weapons\\hands\\" + hs)
            arm = next(o for o in ob if o.type == "ARMATURE")
            self.sets.append(HandSet(hs, arm, [o for o in ob if o.type == "MESH"]))
            for o in ob: bpy.data.objects.remove(o)
        s0 = self.sets[0]
        self.hv, self.htris, self.W, self.dom = s0.hv, s0.htris, s0.W, s0.dom
        self.vside = np.array(["l" if is_left(b) else "r" for b in self.dom])
        self._mirror_setup()
        self._items()
        self._pad = self.thumb_pad()

    # ------------------------------------------------------------------ vanilla poses
    def sample(self, act, frame):
        H, scn = self.H, bpy.context.scene
        H.animation_data.action = bpy.data.actions[act]
        if hasattr(H.animation_data, "action_slot") and bpy.data.actions[act].slots:
            H.animation_data.action_slot = bpy.data.actions[act].slots[0]
        fi = int(math.floor(frame)); scn.frame_set(fi, subframe=frame - fi)
        return {pb.name: pb.matrix.copy() for pb in H.pose.bones}

    def _thumb_axes(self, acts):
        """the left thumb's anatomical axes, in each bone's frame relative to the base: principal axes of how the
        thumb's local rotations vary over many vanilla frames (pistol grip, PDA, Veles, binoculars, gas mask...).
        finger01 / finger02 bend about one hinge axis, finger0 has two (flexion first)."""
        th = FINGERS["l"][0]; B = self.base
        rel0 = {b: (B[self.parent[b]].inverted() @ B[b]).to_quaternion() for b in th}
        samples = {b: [] for b in th}
        for f, al in acts.items():
            for a in al:
                f0, f1 = a.frame_range
                for fr in np.linspace(f0, f1, 6):
                    p = self.sample(a.name, float(fr))
                    for b in th:
                        q = (p[self.parent[b]].inverted() @ p[b]).to_quaternion()
                        d = rel0[b].inverted() @ q             # in the base bone's frame
                        if d.w < 0: d.negate()
                        ax, an = d.to_axis_angle()
                        samples[b].append(np.array(ax) * an)
        tip = B["bip01_l_finger2"].to_translation()             # the palm's side: positive flexion goes toward it
        self.thumb_axes = {}
        for b in th:
            X = np.array(samples[b]); X = X[np.linalg.norm(X, axis=1) > 1e-3]
            _, s, vt = np.linalg.svd(X - 0 * X.mean(0), full_matrices=False)
            axes = []
            for k in range(2 if b == th[0] else 1):
                ax = Vector(vt[k]).normalized()
                # sign: a positive turn brings the bone's far end toward the palm
                J = B[b].to_translation(); end = B[b] @ Vector((0, 0.03, 0))
                axw = B[b].to_3x3() @ ax
                moved = J + Quaternion(axw, 0.2) @ (end - J)
                if (tip - moved).length > (tip - end).length: ax = -ax
                axes.append(ax)
            self.thumb_axes[b] = axes
        self.thumb_log = {b: [tuple(round(x, 3) for x in a) for a in v] for b, v in self.thumb_axes.items()}

    # ------------------------------------------------------------------ skinning (numpy, as the engine)
    def skin(self, pose, k=0):
        """hands mesh vertices in arm space for a pose {bone: arm matrix}; k = which hands set"""
        return self.sets[k].skin(pose)

    # ------------------------------------------------------------------ the devices in hand space
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
        self.tablet = load_low(os.path.join(TABLET_DIR, "tablet_bake.blend"), "tablet")
        pv = np.array([v.co[:] for v in self.probe.data.vertices])
        gb = pv[(pv[:, 2] < -0.10) & (pv[:, 2] > -0.20) & (pv[:, 1] > -0.05)]
        pg = Vector((gb[:, 0].mean(), gb[:, 1].mean(), -0.05))
        R180 = Matrix.Rotation(math.pi, 4, "Z")
        self.P_probe = Matrix.Translation(pm_grip) @ R180 @ Matrix.Scale(PROBE_SCALE, 4) @ Matrix.Translation(-pg)
        self.probe.data.transform(self.P_probe); self.probe.matrix_world = Matrix.Identity(4)
        # cable plug of the probe (end of the strain relief) and its direction, item space
        self.plug_p = self.P_probe @ Vector((0.0, 0.37, 0.325)); self.plug_d = (R180 @ Vector((0, 1, 0))).normalized()
        self.lens_item = self.P_probe @ Vector((0.0, -0.5, 0.29))
        self.A_tab = self.side_grip_tab()
        self.conn_t = Vector(LAYOUT["socket"])
        self.pv_item, self.ptris = mesh_arrays(self.probe)
        self.tv_raw, self.ttris = mesh_arrays(self.tablet)
        self.tv_det = apply_m(self.A_tab, self.tv_raw)
        self.probe_bvh = bvh_of(self.pv_item, self.ptris)
        self.tablet_bvh = bvh_of(self.tv_det, self.ttris)

    def hand_axes(self):
        """the left hand's own axes in its bone frame (base pose): f wrist -> middle knuckle, l the knuckle line toward
        the index, n the palm's side (where the curled fingers go), the palm's centre p; hand = +1 if f x l is n"""
        B = self.base; Hi = B["l_hand"].inverted()
        k = {i: Hi @ B["bip01_l_finger%d" % i].to_translation() for i in (1, 2, 4)}
        f = k[2].normalized()
        l = k[1] - k[4]; l = (l - f * l.dot(f)).normalized()
        tip = Hi @ (B["bip01_l_finger22"] @ Vector((0, 0.02, 0)))
        c = tip - k[2]; n = c - f * c.dot(f); n = (n - l * n.dot(l)).normalized()
        s0 = self.sets[0]
        p = Hi @ Vector(s0.skin(self.pose_of(fingers={}))[s0.dom == "l_hand"].mean(0))
        return f, l, n, p, (1 if f.cross(l).dot(n) > 0 else -1)

    def side_grip_tab(self):
        """A_tab for SIDE_GRIP: the hand's axes turned onto the wanted ones, its palm's centre where SIDE_GRIP puts it"""
        f, l, n, p, hand = self.hand_axes()
        a = math.radians(SIDE_GRIP["alpha"])
        fd = Vector((-math.sin(a), math.cos(a), 0.0)); nd = Vector((0.0, 0.0, 1.0))
        wr = Matrix.Rotation(-math.radians(SIDE_GRIP.get("wrap", 0.0)), 3, "X")   # the palm turned round the edge
        fd, nd = wr @ fd, wr @ nd
        ld = nd.cross(fd) * hand                  # the knuckle line; the index (and the thumb) up the edge
        Hm = Matrix((f, l, f.cross(l))).transposed(); D = Matrix((fd, ld, fd.cross(ld))).transposed()
        Rr = (D @ Hm.transposed()).to_4x4()
        Hr = Matrix.Translation(Vector(SIDE_GRIP["palm"]) - Rr @ p) @ Rr       # the hand bone in tablet coords
        self.side_log = "hand axes: handedness %+d, palm side %s" % (hand, tuple(round(x, 2) for x in (Rr.to_3x3() @ n)))
        return self.L2T.inverted() @ Hr.inverted()

    def shift_probe(self, off):
        """move the probe in item space (the grip into the palm, not through it)"""
        T = Matrix.Translation(Vector(off))
        self.P_probe = T @ self.P_probe; self.probe.data.transform(T)
        self.plug_p = T @ self.plug_p; self.lens_item = T @ self.lens_item; self.grip_item = T @ self.grip_item
        self.pv_item = apply_m(T, self.pv_item); self.probe_bvh = bvh_of(self.pv_item, self.ptris)

    def use_slide(self, slide):
        """the tablet held slide metres lower in the hand (along its edge; 0: as fitted): A_tab and the collision mesh"""
        if not hasattr(self, "A_tab_fit"): self.A_tab_fit = self.A_tab.copy()
        self.A_tab = self.A_tab_fit @ Matrix.Translation(Vector((-slide, 0.0, 0.0)))
        self.tv_det = apply_m(self.A_tab, self.tv_raw); self.tablet_bvh = bvh_of(self.tv_det, self.ttris)

    def shift_tablet(self, off):
        """move the tablet in detector space"""
        self.A_tab = Matrix.Translation(Vector(off)) @ self.A_tab
        self.tv_det = apply_m(self.A_tab, self.tv_raw); self.tablet_bvh = bvh_of(self.tv_det, self.ttris)

    def fit_device(self, side, bones, span=0.012, step=0.002, tol=0.0008):
        """the smallest move of the device (a grid in its own frame) that leaves the vertices of bones (the palm) of
        every hands set no deeper than tol in it; returns the move"""
        pose = self.pose_of(fingers={})
        pts0 = np.vstack([apply_m(self.device_frame(side, pose).inverted(), s.skin(pose)[np.isin(s.dom, bones)]) for s in self.sets])
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
        return pose["l_hand"] @ self.L2T

    def tab_arm(self, pose):
        """the tablet's own coords -> arm space"""
        return self.det_arm(pose) @ self.A_tab

    def tab_point(self, p_raw):
        """a point in the tablet's own coords -> detector space"""
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
        self.tablet.matrix_world = OURS @ self.tab_arm(pose)
        bpy.context.view_layer.update()

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

    # ------------------------------------------------------------------ the right hand mirrored from the left
    def _mirror_setup(self):
        X = Matrix.Diagonal((-1, 1, 1, 1))
        self.mir_C = {b: self.rest[b].inverted() @ X @ self.rest[other(b)] for b in self.BONES if is_left(b)}
        err = max((X @ self.rest[b] @ self.mir_C[b] - self.rest[other(b)]).to_translation().length for b in self.mir_C)
        self.mirror_log = "rest symmetry: %.2f mm" % (err * 1000)

    def mirrored_right(self, pose, fingers):
        """the right hand (and fingers, as local rotations over the base) mirrored from the left hand of a pose about
        the tablet's middle plane (its y = 0); returns (r_hand arm matrix, right fingers' local rotations)"""
        T = self.tab_arm(pose)
        Mref = T @ Matrix.Diagonal((1, -1, 1, 1)) @ T.inverted()
        Pr = {other(b): Mref @ pose[b] @ self.mir_C[b] for b in self.mir_C}
        B = self.base; f = {}
        for ch in FINGERS["r"]:
            for c in ch:
                par = self.parent[c]
                f[c] = (B[par].inverted() @ B[c]).inverted() @ (Pr[par].inverted() @ Pr[c])
        return Pr["r_hand"], f

    # ------------------------------------------------------------------ grips
    def device_frame(self, side, pose):
        return self.det_arm(pose) if side == "l" else self.item_arm(pose)

    def device_bvh(self, side):
        return self.tablet_bvh if side == "l" else self.probe_bvh

    hands_at = (None, None)     # (r_hand, l_hand) arm matrices the grips are measured at (None: the base pose)
    dev_of = {}                 # side -> "l" / "r": whose device a hand's fingers are tested against

    def finger_depth(self, side, bones, fingers, other=None):
        """deepest point of the vertices of bones (every hands set) inside the hand's device. Fingers 1-4 on the
        tablet must also stay off its front: a vertex over its front half, inside its outline, counts as 1 m deep
        (a finger wrapped round an edge onto the bezel, or through to the glass). The palm and the thumb may wrap."""
        pose = self.pose_of(*self.hands_at, fingers=fingers)
        dv = self.dev_of.get(side, side)
        Fi = self.device_frame(dv, pose).inverted(); bvh = self.device_bvh(dv)
        front = dv == "l" and all(b.startswith("bip01_") for b in bones)      # fingers 1-4 only (not the palm, thumb)
        if front:
            Ri = (self.det_arm(pose) @ self.A_tab).inverted()
            hh, hw = LAYOUT["half"]; fz = LAYOUT["front"]
        d = 0.0
        for s in self.sets:
            m = np.isin(s.dom, bones)
            if m.any():
                v = s.skin(pose)[m]
                d = max(d, depths(bvh, apply_m(Fi, v)).max())
                if front:
                    r = apply_m(Ri, v)
                    if np.any((r[:, 2] > fz / 2) & (np.abs(r[:, 0]) < hh + 0.004) & (np.abs(r[:, 1]) < hw + 0.004)):
                        d = 1.0
        return d

    def curl_axes(self, side, chain, toward, fingers=None):
        """per joint of a finger 1-4: the flexion axis in the bone's own frame (about the hand's knuckle line), taken
        on the pose the finger is in (the hands at hands_at, the fingers given); the sign makes a positive angle move
        the tip toward the device (the palm's side)."""
        B = self.pose_of(*self.hands_at, fingers=fingers or {}); axes = []
        lat = (B["bip01_%s_finger1" % side].to_translation() - B["bip01_%s_finger4" % side].to_translation()).normalized()
        for i, b in enumerate(chain):
            J = B[b].to_translation()
            nxt = B[chain[i + 1]].to_translation() if i + 1 < len(chain) else J + (J - B[chain[i - 1]].to_translation())
            s = (nxt - J).normalized()
            a = (lat - s * lat.dot(s)).normalized()
            end = J + s * 0.03
            moved = J + Quaternion(a, 0.2) @ (end - J)
            if (toward - moved).length > (toward - end).length:
                a = -a
            axes.append(B[b].to_3x3().inverted() @ a)
        return axes

    def solve_curl(self, side, chain, fingers, toward, tol=0.0012, lim=((-40, 85), (-40, 100), (-40, 80)), free=25,
                   close=True, reach_open=False):
        """a finger: first turned as a whole (opened or curled, whichever needs less) until its vertices are out of
        the device (no deeper than tol), then closed, root to tip, as far as each joint goes before the rest of the
        finger touches; a joint that meets nothing up to its limit is left at `free` degrees more (a relaxed curl)"""
        axes = self.curl_axes(side, chain, toward, fingers)
        ang = {b: 0 for b in chain}

        def cur(over=None):
            f = dict(fingers)
            for b in chain:
                deg = (over or {}).get(b, ang[b])
                f[b] = fingers.get(b, Matrix.Identity(4)) @ Matrix.Rotation(math.radians(deg), 4, axes[chain.index(b)])
            return f
        done = False
        for k in range(0, max(-lim[0][0], 60) + 1, 2):   # out: the whole finger flatter, or curled, by k
            for sg in ((-1, 1) if k else (1,)):
                for i, b in enumerate(chain):
                    lo, hi = lim[min(i, 2)]
                    ang[b] = max(min(sg * k, hi), lo)
                if self.finger_depth(side, chain, cur()) <= tol:
                    done = True; break
            if done: break
        for i, b in enumerate(chain if close else []):     # close
            hi = lim[min(i, 2)][1]; start = ang[b]; best = None
            for deg in range(start + 2, hi + 1, 2):
                if self.finger_depth(side, chain[i:], cur({b: deg})) > tol:
                    best = deg - 2; break
            if best is None and i == 0 and reach_open:
                # closing meets nothing (the finger is past the device's edge, curling into the air): open the
                # knuckle instead until the finger lies on the device, if it gets there
                for deg in range(start - 2, lim[0][0] - 1, -2):
                    if self.finger_depth(side, chain, cur({b: deg})) > tol:
                        best = deg + 2; break
            ang[b] = best if best is not None else min(start + free, hi)
        self.grip_log.append(" ".join("%s %+d" % (b, ang[b]) for b in chain))
        return cur()

    grip_log = []

    def thumb_pad(self, fingers=None):
        """the pad of the left thumb, in its last bone's frame: the skin of that bone on the side its joint bends to
        (the palmar side), in the bone's outer half. Anatomical, so it stays the pad however the thumb is turned."""
        pose = self.pose_of(fingers={})
        s = self.sets[0]; b = "l_finger02"
        loc = apply_m(pose[b].inverted(), s.skin(pose)[s.dom == b])
        d = np.array(self.thumb_axes[b][0].cross(Vector((0, 1, 0))).normalized())
        y = loc[:, 1]; outer = loc[y > np.median(y)]
        k = np.argsort(-(outer @ d))[:8]
        return Vector(outer[k].mean(0))

    def thumb_aim(self, fingers, mcp_raw, up_raw, palmar_raw=(0.0, 0.0, -1.0), flex2=8.0):
        """the left thumb laid out straight: its first bone from the base joint to mcp_raw (the knuckle at its root),
        the two phalanges along up_raw, the last one bent flex2 degrees; each bone rolled so its palmar side (the side
        it bends to) faces palmar_raw (the tablet's front). Tablet coords. Returns the fingers with the thumb set."""
        th = FINGERS["l"][0]; B = self.base; f = dict(fingers)
        pose = self.pose_of(*self.hands_at, fingers=f); T = self.tab_arm(pose); T3 = T.to_3x3()
        up = (T3 @ Vector(up_raw)).normalized(); pal = (T3 @ Vector(palmar_raw)).normalized()
        for i, b in enumerate(th):
            pose = self.pose_of(*self.hands_at, fingers=f); P = pose[b]; head = P.to_translation()
            if i == 0:
                want = ((T @ Vector(mcp_raw)) - head).normalized()
                cur = (P.to_3x3() @ (B[b].inverted() @ B[th[1]].to_translation())).normalized()
            else:
                want = up if i == 1 else (Quaternion(up.cross(pal).normalized(), math.radians(flex2)) @ up)
                nxt = (B[b].inverted() @ B[th[2]].to_translation()) if i == 1 else Vector((0, 1, 0))
                cur = (P.to_3x3() @ nxt).normalized()
            q1 = cur.rotation_difference(want)
            # roll about the wanted direction: the bone's palmar side toward pal
            pl = q1 @ (P.to_3x3() @ self.thumb_axes[b][0].cross(Vector((0, 1, 0)))).normalized()
            pl = (pl - want * pl.dot(want)).normalized(); pw = (pal - want * pal.dot(want)).normalized()
            ang = math.atan2(pl.cross(pw).dot(want), pl.dot(pw))
            Q = (Quaternion(want, ang) @ q1).to_matrix().to_4x4()
            Pn = Matrix.Translation(head) @ Q @ Matrix.Translation(-head) @ P
            par = pose[self.parent[b]]
            f[b] = (B[self.parent[b]].inverted() @ B[b]).inverted() @ par.inverted() @ Pn
        return f

    def thumb_lay(self, fingers, lay=None, turn=(0.0, 0.0)):
        """the thumb laid out by THUMB_LAY (thumb_aim), its first bone turned by turn = (degrees toward the glass'
        normal, degrees about it) from there; returns (fingers, the pad's place in tablet coords)"""
        lay = lay or THUMB_LAY; th = FINGERS["l"][0]; B = self.base
        pose = self.pose_of(*self.hands_at, fingers=fingers); Ti = self.tab_arm(pose).inverted()
        c = Ti @ pose[th[0]].to_translation()
        L0 = (B[th[1]].to_translation() - B[th[0]].to_translation()).length
        zt = LAYOUT["front"] + lay["lift"]; r2 = max(L0 ** 2 - (lay["mcp_y"] - c.y) ** 2 - (zt - c.z) ** 2, 0.0)
        d0 = (Vector((c.x - math.sqrt(r2), lay["mcp_y"], zt)) - c).normalized()
        a1 = d0.cross(Vector((0, 0, 1))).normalized(); a2 = d0.cross(a1).normalized()
        d = Quaternion(a2, math.radians(turn[1])) @ (Quaternion(a1, math.radians(turn[0])) @ d0)
        f = self.thumb_aim(fingers, c + d * L0, (-1.0, lay["lean"], 0.0), flex2=lay["flex"])
        pz = self.pose_of(*self.hands_at, fingers=f)
        return f, self.tab_arm(pz).inverted() @ (pz[th[2]] @ self._pad)

    def thumb_place(self, fingers, target_raw, tol=0.002, label="thumb"):
        """the thumb moved from its laid-out rest onto a point (tablet coords): a search over the first bone's turn,
        the lean and the last joint's bend; cost = the pad's miss (1.5 mm ~ 1) + how far it is from the rest layout;
        the best that keeps every hands set's thumb out of the tablet wins. Returns (fingers, miss)"""
        th = FINGERS["l"][0]; tgt = Vector(target_raw); cand = []
        for t0 in range(-30, 31, 5):
            for t1 in range(-30, 31, 5):
                for lean in (0.3, 0.45, 0.55, 0.7, 0.85):
                    for fl in (20.0, 35.0, 50.0, 65.0, 80.0):
                        lay = dict(THUMB_LAY, lean=lean, flex=fl)
                        f, q = self.thumb_lay(fingers, lay, (t0, t1))
                        d = (q - tgt).length
                        if d > 0.01: continue
                        c = (d / 0.0015) ** 2 + (t0 / 20) ** 2 + (t1 / 20) ** 2 + ((lean - THUMB_LAY["lean"]) / 0.3) ** 2 +                             ((fl - THUMB_LAY["flex"]) / 30) ** 2
                        cand.append((c, d, (t0, t1, lean, fl), f, q))
        cand.sort(key=lambda x: x[0])
        for i, (c, d, a, f, q) in enumerate(cand[:40]):
            if self.finger_depth("l", th, f) <= tol:
                self.grip_log.append("%s: miss %.1f mm (pad at %.4f %.4f %.4f), turn %+d/%+d lean %.2f bend %d (cost %.2f, %d tried)"
                                     % (label, d * 1000, q.x, q.y, q.z, a[0], a[1], a[2], a[3], c, i + 1))
                return f, d
        if cand:
            ds = sorted((self.finger_depth("l", th, x[3]), x[1], x[2]) for x in cand[:40])[0]
            self.grip_log.append("%s: NO clear pose among %d candidates (least deep %.1f mm, miss %.1f mm, %s)"
                                 % (label, len(cand), ds[0] * 1000, ds[1] * 1000, ds[2]))
        else:
            self.grip_log.append("%s: no candidate within 10 mm" % label)
        return (cand[0][3], cand[0][1]) if cand else (fingers, 1.0)


def setup_grips(R, log=print):
    """fit the devices into the hands, then the grips: the left hand round the tablet's left edge (SIDE_GRIP), its
    fingers closed onto the back, the thumb straight up the front left bezel above the buttons (one hand; the same
    thumb lies on P1 when both hands hold the tablet lower, SLIDE_TWO_HAND), and brought down onto P1 (the press);
    the right hand round the probe's grip. Returns (fingers at rest, fingers pressing P1, fingers for two hands).""" 
    offp = R.fit_device("r", ["r_hand", "bip01_r_finger2", "bip01_r_finger3", "bip01_r_finger4"], span=0.016)
    R.shift_probe(offp or (0, 0, 0))
    offt = R.fit_device("l", ["l_hand"], tol=0.0015)
    R.shift_tablet(offt or (0, 0, 0))
    log("FIT probe %s tablet %s | %s" % (offp, offt, R.side_log))
    log("THUMB AXES %s | %s" % (R.thumb_log, R.mirror_log))
    b0 = R.pose_of(fingers={})
    px, py, pz = SIDE_GRIP["palm"]
    tc = R.tab_arm(b0) @ Vector((px - 0.02, py + 0.06, 0.012))     # inside the tablet ahead of the fingers
    pg = R.item_arm(b0) @ R.grip_item
    f = {}
    for ch in FINGERS["l"][1:]:
        f = R.solve_curl("l", ch, f, tc, lim=((-90, 85), (-60, 100), (-40, 80)), reach_open=True)
    lay, nat = R.thumb_lay(f)
    log("THUMB laid out: pad at %.4f %.4f %.4f, depth %.1f mm" % (nat.x, nat.y, nat.z, R.finger_depth("l", FINGERS["l"][0], lay) * 1000))
    p1 = BUTTONS["p1"]
    rest = lay                    # one hand: the thumb straight as laid out, above the buttons
    on = lay                      # two hands: laid out the same, the hands lower on the edges (SLIDE_TWO_HAND)
    press, _ = R.thumb_place(f, (p1[0], p1[1], p1[2] - 0.0002), label="thumb pressing P1")
    for ch in FINGERS["r"]:
        rest = R.solve_curl("r", ch, rest, pg)
        for g in (press, on):
            g.update({b: rest[b] for b in ch if b in rest})
    log("GRIP " + " | ".join(R.grip_log))
    log("GRIP depths (mm, every hands set; 1000 = on the tablet's front): " + " ".join(
        "%s %.1f" % (ch[0], R.finger_depth("l", ch, rest) * 1000) for ch in FINGERS["l"]))
    return rest, press, on


def setup_two_hand(R, l_arm, rest, log=print):
    """the two-handed hold: the right hand mirrored from the left about the tablet's middle (its thumb by + / -),
    its fingers then closed again on the tablet's back. l_arm: the left hand (arm space) of that pose.
    Returns (r_hand arm matrix, fingers)."""
    pose = R.pose_of(l_hand=l_arm, fingers=rest)
    r_arm, rf = R.mirrored_right(pose, rest)
    f = dict(rest); f.update(rf)
    R.hands_at = (r_arm, l_arm); R.dev_of = {"r": "l"}
    p = R.pose_of(r_arm, l_arm, fingers=f)
    tc = R.tab_arm(p) @ Vector((0.0, 0.06, -0.03))
    R.grip_log = []
    for ch in FINGERS["r"][1:]:
        f = R.solve_curl("r", ch, f, tc, lim=((-90, 85), (-60, 100), (-40, 80)), reach_open=True)
    dth = R.finger_depth("r", FINGERS["r"][0], f)
    log("TWO-HAND right depths (mm): " + " ".join("%s %.1f" % (ch[0], R.finger_depth("r", ch, f) * 1000) for ch in FINGERS["r"]))
    R.hands_at = (None, None); R.dev_of = {}
    log("TWO-HAND right fingers: %s | right thumb depth %.1f mm" % (" | ".join(R.grip_log), dth * 1000))
    return r_arm, f
