r"""Spectrum-X: intersection check of every frame of every animation, on the EXPORTED files (what the game gets).
blender -b -P check_hud.py -- <vanilla meshes> <gamedata> <report.txt> [--hands wpn_hand_01.ogf]

Loads the hands (wpn_hand_01.ogf) + dev_hand_spectrum_x_hud_animation.omf and dev_spectrum_x_hud.ogf with its
motions, places the item as the engine does, and for each frame measures (Blender's armature deform = the engine's
linear blend):
  L-tablet / R-probe   how deep a hand's vertex goes into the device it holds (fingers, thumb, palm)
  L-probe / R-tablet   a hand inside the other device
  probe-tablet         the devices inside each other
  cable-hands          the cable's vertices inside a hand or arm (by the nearest face's normal, within 15 mm)
  cable-devices        the cable inside the probe or the tablet (its two ends, at the plug and the socket, left out)
  arms                 the left and right arm meshes touching (triangle overlap)
  screen-cover         hand vertices in front of the tablet's screen (up to 40 mm), inside its frame (a thumb on the glass)
  cable-stretch        the cable's length against its bind length
Depth of a point inside a closed mesh: the nearest face's normal says inside and two rays cross it an odd number of
times. Limits: FAIL above FAIL_MM, warn above WARN_MM (contact of skin on a surface is a millimetre or two)."""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from xr_space import offset_b
from hud_rig import depths, _odd, SCREEN, TABLET_SCALE
from io_scene_xray.formats.motions.const import MATRIX_BONE_INVERTED

a = sys.argv[sys.argv.index("--") + 1:]
G, GD, REPORT = a[0], a[1], a[2]
HANDS = a[a.index("--hands") + 1] if "--hands" in a else "wpn_hand_01.ogf"
WARN_MM, FAIL_MM = 1.5, 3.0
K = MATRIX_BONE_INVERTED.to_4x4()
OURS = offset_b((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15)); ITEM = offset_b((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))
bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene


def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]


hobjs = imp_ogf(G + "\\anomaly_weapons\\hands\\" + HANDS)
H = next(o for o in hobjs if o.type == "ARMATURE"); HM = [o for o in hobjs if o.type == "MESH"]
if len(HM) > 1:       # hands made of several meshes (the exoskeleton's): one object
    for o in bpy.context.scene.objects: o.select_set(o in HM)
    bpy.context.view_layer.objects.active = HM[0]; bpy.ops.object.join(); HM = [HM[0]]
bpy.context.view_layer.objects.active = H
acts0 = set(bpy.data.actions)
bpy.ops.xray_import.omf(directory=GD + r"\meshes\anomaly_weapons\hud_hands_animation", files=[{"name": "dev_hand_spectrum_x_hud_animation.omf"}],
                        import_motions=True, import_bone_parts=False)
hand_acts = {x.name: x for x in bpy.data.actions if x not in acts0}
acts1 = set(bpy.data.actions)
item = imp_ogf(GD + r"\meshes\dynamics\devices\dev_spectrum_x\dev_spectrum_x_hud.ogf")
IA = next(o for o in item if o.type == "ARMATURE")
item_acts = {x.name.split(".")[0]: x for x in bpy.data.actions if x not in acts1}
H.matrix_world = OURS


def kind(o):
    names = " ".join(m.name for m in o.data.materials if m) + " " + " ".join(
        n.image.name for m in o.data.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image)
    for k in ("probe", "tablet", "screen", "cable"):
        if k in names: return k
    return o.name


IM = {kind(o): o for o in item if o.type == "MESH"}
print("item meshes", sorted(IM))
# the hands' sides by the dominant bone of each vertex
hm = HM[0]
gname = {g.index: g.name for g in hm.vertex_groups}
side = []
for v in hm.data.vertices:
    g = max(v.groups, key=lambda x: x.weight) if v.groups else None
    n = gname[g.group] if g else ""
    side.append("l" if (n.startswith("l_") or n.startswith("bip01_l")) else "r")
side = np.array(side)
dom = []
for v in hm.data.vertices:
    g = max(v.groups, key=lambda x: x.weight) if v.groups else None
    dom.append(gname[g.group] if g else "")
dom = np.array(dom)
htris = np.array([tuple(p.vertices) for p in hm.data.polygons if len(p.vertices) == 3])
if os.path.isdir(os.path.dirname(REPORT)) is False: os.makedirs(os.path.dirname(REPORT))


def assign(obj, act):
    obj.animation_data_create(); obj.animation_data.action = act
    if hasattr(obj.animation_data, "action_slot") and act.slots:
        obj.animation_data.action_slot = act.slots[0]


def world_verts(o):
    dg = bpy.context.evaluated_depsgraph_get()
    e = o.evaluated_get(dg); m = e.to_mesh()
    M = np.array(o.matrix_world)
    v = np.array([x.co[:] for x in m.vertices]); tris = []
    for p in m.polygons:
        vs = list(p.vertices)
        for i in range(1, len(vs) - 1): tris.append((vs[0], vs[i], vs[i + 1]))
    e.to_mesh_clear()
    return v @ M[:3, :3].T + M[:3, 3], np.array(tris)


def bvh(v, t):
    return BVHTree.FromPolygons([Vector(x) for x in v], [tuple(x) for x in t], all_triangles=True)


def near_box(pts, v, pad=0.03):
    lo, hi = v.min(0) - pad, v.max(0) + pad
    return np.all((pts >= lo) & (pts <= hi), axis=1)


def depth_in(b, pts, vbox):
    m = near_box(pts, vbox)
    d = np.zeros(len(pts))
    if m.any(): d[m] = depths(b, pts[m], 0.05)
    return d


def soft_depth(b, pts, reach=0.015):
    """open meshes (the hands): inside by the nearest face's normal only"""
    out = np.zeros(len(pts))
    for i, p in enumerate(pts):
        p = Vector(p); loc, n, idx, d = b.find_nearest(p, reach)
        if loc is not None and (p - loc).dot(n) < 0: out[i] = d
    return out


lines = []; worst = {}; fails = []
cable_len0 = None
for mot in sorted(hand_acts):
    if mot not in item_acts:
        lines.append("%s: no item motion" % mot); continue
    assign(H, hand_acts[mot]); assign(IA, item_acts[mot])
    f0, f1 = [int(x) for x in hand_acts[mot].frame_range]
    res = {}
    for fr in range(f0, f1 + 1):
        sc.frame_set(fr)
        IA.matrix_world = OURS @ H.pose.bones["lead_gun"].matrix @ K @ ITEM
        bpy.context.view_layer.update()
        hv, _ = world_verts(hm)
        V = {k: world_verts(o) for k, o in IM.items()}
        B = {k: bvh(*V[k]) for k in ("probe", "tablet")}
        L, Rr = side == "l", side == "r"
        m = {}
        m["L-tablet"] = depth_in(B["tablet"], hv[L], V["tablet"][0])
        m["R-probe"] = depth_in(B["probe"], hv[Rr], V["probe"][0])
        m["L-probe"] = depth_in(B["probe"], hv[L], V["probe"][0])
        m["R-tablet"] = depth_in(B["tablet"], hv[Rr], V["tablet"][0])
        m["probe-tablet"] = np.r_[depth_in(B["tablet"], V["probe"][0], V["tablet"][0]), depth_in(B["probe"], V["tablet"][0], V["probe"][0])]
        cv = V["cable"][0]
        # the cable's ends: the vertices nearest its first and last rings (plug, socket) - 15 mm left out
        n = len(cv); ends = np.zeros(n, bool); ends[:6 * 15] = True; ends[-6 * 15:] = True
        bh = bvh(hv, htris)
        m["cable-hands"] = np.r_[soft_depth(bh, cv[near_box(cv, hv)]), 0]
        m["cable-devices"] = np.r_[depth_in(B["tablet"], cv[~ends], V["tablet"][0]), depth_in(B["probe"], cv[~ends], V["probe"][0])]
        # arms touching: triangles of the left arm against the right arm
        idxL = np.where(L)[0]; idxR = np.where(Rr)[0]
        mapL = {j: i for i, j in enumerate(idxL)}; mapR = {j: i for i, j in enumerate(idxR)}
        tL = [tuple(mapL[x] for x in t) for t in htris if all(x in mapL for x in t)]
        tR = [tuple(mapR[x] for x in t) for t in htris if all(x in mapR for x in t)]
        ov = BVHTree.FromPolygons([Vector(x) for x in hv[L]], tL, all_triangles=True).overlap(
            BVHTree.FromPolygons([Vector(x) for x in hv[Rr]], tR, all_triangles=True))
        m["arms"] = np.array([0.01 * len(ov)])          # reported as a count (x10 mm)
        # screen cover: hand vertices in front of the glass inside its frame
        sv = V["screen"][0]
        c0 = sv.mean(0)
        _, _, vt = np.linalg.svd(sv - c0)
        ax0, ax1, nrm = vt[0], vt[1], vt[2]
        if np.dot(nrm, -c0) < 0: nrm = -nrm                # toward the camera (at the origin)
        rel = hv - c0; h = rel @ nrm; u = rel @ ax0; v_ = rel @ ax1
        half0 = np.abs((sv - c0) @ ax0).max(); half1 = np.abs((sv - c0) @ ax1).max()
        cover = (h > -0.002) & (h < 0.04) & (np.abs(u) < half0) & (np.abs(v_) < half1)
        m["screen-cover"] = np.array([cover.sum() * 0.0001])   # count x 0.1 mm
        # cable length
        L_c = 0
        rings = cv.reshape(-1, 6, 3).mean(1)
        L_c = np.linalg.norm(np.diff(rings, axis=0), axis=1).sum()
        if cable_len0 is None and mot.endswith("_idle") and fr == f0:
            cable_len0 = L_c
        m["cable-stretch"] = np.array([L_c / 1000.0])
        for k, d in m.items():
            x = float(d.max()) if len(d) else 0.0
            if k not in res or x > res[k][0]:
                extra = ""
                if k in ("L-tablet", "R-probe", "L-probe", "R-tablet") and x > 0:
                    sel = L if k.startswith("L") else Rr
                    extra = dom[sel][int(np.argmax(d))]
                res[k] = (x, fr, extra)
    worst[mot] = res
    row = []
    for k, (x, fr, extra) in res.items():
        if k == "arms":
            txt = "%s %d tris@%d" % (k, round(x * 100), fr)
            if x > 0: fails.append("%s %s" % (mot, txt))
        elif k == "screen-cover":
            txt = "%s %d verts@%d" % (k, round(x * 10000), fr)
            if x > 0: fails.append("%s %s" % (mot, txt))
        elif k == "cable-stretch":
            txt = "%s %.0f mm" % (k, x * 1e6)
        else:
            mm = x * 1000
            txt = "%s %.1fmm@%d%s" % (k, mm, fr, (" " + extra) if extra else "")
            if mm > FAIL_MM: fails.append("%s %s FAIL" % (mot, txt))
            elif mm > WARN_MM: fails.append("%s %s warn" % (mot, txt))
        row.append(txt)
    lines.append("%s (%d frames): %s" % (mot, f1 - f0 + 1, " | ".join(row)))
    print(lines[-1])
out = "\n".join(lines) + "\n\nPROBLEMS (%d):\n" % len(fails) + "\n".join(fails) + "\n"
open(REPORT, "w", encoding="utf-8").write(out)
print(out)
