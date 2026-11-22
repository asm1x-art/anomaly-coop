r"""Spectrum-X first-person HUD: hands animations (.omf) + item model with its own animations (.ogf), from
the baked low-poly probe (retopo_blender.py + bake.py) and the landscape tablet (make_tablet.py), in one Blender scene.

blender -b -P build_hud.py -- --meshes <vanilla meshes dir> --assets <X:\coop\assets\spectrum-x> --out <gamedata> [--poses]
--poses: only three still poses (spectrum_x_pose_hold / _switch / _menu: one hand; the thumb on P1; both hands, the
probe put away out of view) for the look check (pose_check.sh); the numbers and the .blend then go into --out too.

The rig (hud_rig.py): the hands' base pose comes from vanilla (right arm = the PM's idle, left arm = the PDA's
idle, both at our hud section's offsets, the PM's); the probe sits on lead_gun where the PM sits; the left hand holds
the tablet round its left side edge (hud_rig.SIDE_GRIP: palm round the edge, fingers on the back, thumb straight up
the bezel). The grips are solved against the meshes of every arms model (hud_rig.HAND_SETS): each finger turned until
it is out of the device, then closed until it touches; the thumb laid out straight (rest), moved onto P1 for the
press. The two-handed hold: both hands SLIDE_TWO_HAND lower on the edges (the tablet bone moved in the hand, D) so
the straight thumbs lie on P1 and +, the right hand mirrored from the left about the tablet's middle.
The item's bones: wpn_body (on lead_gun), probe (on wpn_body; moves off only when the probe is put away), tablet,
cable_NN.
The animations (hud_anims.py) say where each hand goes over time; two-bone IK puts the arms there.
The coiled cable is a chain of CABLE_BONES bones; every frame the cable's curve is worked out again between the
probe's plug and the tablet's socket (a sag picked so the cable keeps clear of the hands and the devices) and the
bones are laid along it, so the coil follows both hands without stretching through anything.
Engine conventions checked on the binoculars / PM / Veles: item = hands * bone(lead_gun) * MATRIX_BONE_INVERTED *
HPB(item_orientation)+item_position (see xr_space.py).

Writes:
  <out>/meshes/anomaly_weapons/hud_hands_animation/dev_hand_spectrum_x_hud_animation.omf
  <out>/meshes/dynamics/devices/dev_spectrum_x/dev_spectrum_x_hud.ogf   (bones wpn_body, tablet, cable_NN; motions)
  <out>/meshes/dynamics/devices/dev_spectrum_x/dev_spectrum_x.ogf       (world model, one bone)
  <assets>/hud/spectrum_x_hud.blend, <assets>/hud/build_numbers.json (the 3D screen's custom_ui_pos/rot and size,
  the menu pose's screen corners, the animations' lengths: for configs/mod_system_spectrum_x.ltx)
"""
import bpy, bmesh, sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
import hud_rig as hr
import hud_anims as ha
from xr_space import S as XS

argv = sys.argv[sys.argv.index("--") + 1:]
opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
G = opt("--meshes"); A = opt("--assets"); OUT = opt("--out")
POSES_ONLY = "--poses" in argv     # only the still poses for the look check (pose_hold / pose_switch / pose_menu)
FPS = ha.FPS
NAME = "spectrum_x"
CABLE_BONES = 12
CABLE_R = 0.0063            # the coil's outer radius (helix + tube)
UI_LIFT = 0.0004            # the 3D screen's interface over the screen plane

bpy.ops.wm.read_homefile(use_empty=True)
scn = bpy.context.scene
scn.render.fps = FPS
R = hr.Rig(G, A)
OURS, K, KI = hr.OURS, hr.K, hr.KI
rest_f, press_f, on_f = hr.setup_grips(R)


def fingers_at(w):
    """the left thumb between rest (0) and press (1), the rest as the grip"""
    if w <= 0: return rest_f
    out = {}
    for b in set(rest_f) | set(press_f):
        qa = rest_f.get(b, Matrix.Identity(4)).to_quaternion(); qb = press_f.get(b, Matrix.Identity(4)).to_quaternion()
        out[b] = qa.slerp(qb, w).to_matrix().to_4x4()
    return out


def item_world(pose):
    return OURS @ R.item_arm(pose)


def tablet_world(pose, M):
    return OURS @ R.det_arm(pose) @ M


# ---------------------------------------------------------------- bind pose: the base with the grip
idle0 = R.pose_of(fingers=rest_f)
IW0 = item_world(idle0); IW0i = IW0.inverted()
T0 = IW0i @ tablet_world(idle0, Matrix.Identity(4))      # detector space -> item space at bind
probe, tablet = R.probe, R.tablet
tablet.data.transform(T0 @ R.A_tab); tablet.matrix_world = Matrix.Identity(4)
conn_i = T0 @ R.A_tab @ R.conn_t
conn_dl = (R.A_tab.to_3x3() @ Vector((1, 0, 0))).normalized()     # out of the socket, detector space

# screen plane (own material, the UI is drawn over it by the engine)
sm = bpy.data.meshes.new("screen"); bm = bmesh.new()
x0, x1, y0, y1, z = hr.SCREEN
vs = [bm.verts.new(T0 @ R.A_tab @ Vector(p)) for p in ((x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z))]
face = bm.faces.new(vs); uvl = bm.loops.layers.uv.new("UVMap")
for l, uv in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): l[uvl].uv = uv
bmesh.ops.triangulate(bm, faces=bm.faces[:]); bm.normal_update()
front = (T0 @ R.A_tab).to_3x3() @ Vector((0, 0, 1))
bm.faces.ensure_lookup_table()
if bm.faces[0].normal.dot(front) < 0: bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
bm.to_mesh(sm); bm.free()
screen = bpy.data.objects.new("screen", sm); scn.collection.objects.link(screen)


# ---------------------------------------------------------------- the cable's curve
def bez(p0, p1, p2, p3, t):
    u = 1 - t
    return p0 * u ** 3 + p1 * 3 * u * u * t + p2 * 3 * u * t * t + p3 * t ** 3


L_REST = (conn_i - R.plug_p).length * 1.12


def cable_curve(conn, conn_d, down, phi, n, prel=None):
    """item space: points from the probe's plug to the tablet's socket; phi turns the sag about the line between;
    prel: the probe bone's place in the item (None: at rest)"""
    p0, d0 = R.plug_p, R.plug_d
    if prel is not None: p0, d0 = prel @ p0, (prel.to_3x3() @ d0).normalized()
    dist = (conn - p0).length
    a = 0.32 * dist + 0.12 * max(0.0, L_REST - dist)
    ax = (conn - p0).normalized()
    g = down - ax * down.dot(ax)
    g = g.normalized() if g.length > 1e-6 else ax.orthogonal().normalized()
    g = Quaternion(ax, phi) @ g
    sag = 0.12 * dist + 0.45 * max(0.0, L_REST - dist)
    p1 = p0 + d0 * a + g * sag; p2 = conn + conn_d * a + g * sag
    return [bez(p0, p1, p2, conn, i / n) for i in range(n + 1)]


def frames_along(pts):
    """parallel-transport frames (tangent, n1, n2) along points, started from the plug's fixed frame"""
    n = len(pts) - 1
    tang = [(pts[min(i + 1, n)] - pts[max(i - 1, 0)]).normalized() for i in range(n + 1)]
    nrm = Vector((0, 0, 1)); nrm = (nrm - tang[0] * nrm.dot(tang[0])).normalized()
    out = []
    for i in range(n + 1):
        if i: nrm = (nrm - tang[i] * nrm.dot(tang[i])).normalized()
        out.append((tang[i], nrm, tang[i].cross(nrm)))
    return out


def bone_frames(pts):
    fr = frames_along(pts); n = len(pts) - 1; res = []
    for k in range(CABLE_BONES):
        i = int(round(k / (CABLE_BONES - 1) * n))
        t, n1, n2 = fr[i]
        M = Matrix((t, n1, n2)).transposed().to_4x4(); M.translation = pts[i]
        res.append(M)
    return res


cam_down_i = (IW0i.to_3x3() @ Vector((0, 0, -1))).normalized()
conn_d0 = (T0.to_3x3() @ conn_dl).normalized()
N_SEG, TURNS, R_HELIX, R_TUBE, SIDES = 360, 26, 0.0045, 0.0018, 6
pts0 = cable_curve(conn_i, conn_d0, cam_down_i, 0.0, N_SEG)
fr0 = frames_along(pts0)
center = []
for i, p in enumerate(pts0):
    t = i / N_SEG; fade = ha.smooth(t / 0.08) * ha.smooth((1 - t) / 0.08)
    a = 2 * math.pi * TURNS * t
    tg, n1, n2 = fr0[i]
    center.append(p + (n1 * math.cos(a) + n2 * math.sin(a)) * R_HELIX * fade)
cm = bpy.data.meshes.new("cable"); bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
rings = []
for i, c in enumerate(center):
    tg = (center[min(i + 1, N_SEG)] - center[max(i - 1, 0)]).normalized()
    n1 = (fr0[i][1] - tg * fr0[i][1].dot(tg)).normalized(); n2 = tg.cross(n1)
    rings.append([bm.verts.new(c + (n1 * math.cos(2 * math.pi * k / SIDES) + n2 * math.sin(2 * math.pi * k / SIDES)) * R_TUBE) for k in range(SIDES)])
for i in range(N_SEG):
    for k in range(SIDES):
        k2 = (k + 1) % SIDES
        f = bm.faces.new((rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]))
        for l, uv in zip(f.loops, ((k / SIDES, i / 8), (k / SIDES, (i + 1) / 8), ((k + 1) / SIDES, (i + 1) / 8), ((k + 1) / SIDES, i / 8))):
            l[uvl].uv = uv
bmesh.ops.triangulate(bm, faces=bm.faces[:]); bm.normal_update()
bm.to_mesh(cm); bm.free()
cable = bpy.data.objects.new("cable", cm); scn.collection.objects.link(cable)
cable_t = [i // SIDES / N_SEG for i in range(len(cm.vertices))]
CB0 = bone_frames(pts0)
CNAMES = ["cable_%02d" % k for k in range(CABLE_BONES)]

# ---------------------------------------------------------------- item armature (from the PM's: wpn_body = X-Ray identity)
for o in R.pm_objs:
    if o.type == "MESH": bpy.data.objects.remove(o)
IA = R.pm_arm; IA.name = "spectrum_x_hud"; IA.data.name = "spectrum_x_hud"
# the PM's import brings its motion refs (wpn_pm_hud_animation): exported, they make the engine load the PM's motions
# instead of ours ("model has no motion [idle]" on draw). Our motions are embedded: no refs.
IA.xray.motionrefs_collection.clear()
for c in list(IA.data.collections): IA.data.collections.remove(c)
bpy.context.view_layer.objects.active = IA
for o in scn.objects: o.select_set(o == IA)
bpy.ops.object.mode_set(mode="EDIT")
eb = IA.data.edit_bones
for b in list(eb):
    if b.name != "wpn_body": eb.remove(b)
root = eb["wpn_body"]
TAB0 = T0.copy()
for nm, F in [("tablet", TAB0), ("probe", Matrix.Identity(4))] + list(zip(CNAMES, CB0)):
    e = eb.new(nm); e.head = (0, 0, 0); e.tail = (0, 0.02, 0); e.matrix = F @ KI; e.length = 0.02; e.parent = root
bpy.ops.object.mode_set(mode="OBJECT")
REST = {b.name: b.matrix_local.copy() for b in IA.data.bones}
for pb in IA.pose.bones:
    pb.rotation_mode = "ZXY"       # new bones come in quaternion mode: their rotation_euler keys would stay at zero
for c in list(IA.data.collections): IA.data.collections.remove(c)
_bc = IA.data.collections.new("default")
for b in IA.data.bones: _bc.assign(b)
ITEM_BONES = ["wpn_body", "tablet", "probe"] + CNAMES


def bind(obj, weights):
    obj.parent = IA
    md = obj.modifiers.new("arm", "ARMATURE"); md.object = IA
    for bn in ITEM_BONES:
        obj.vertex_groups.new(name=bn)
    for i, w in enumerate(weights):
        for bn, x in w.items():
            if x > 1e-4: obj.vertex_groups[bn].add([i], x, "REPLACE")


def cable_w(t):
    s = t * (CABLE_BONES - 1); i = min(int(s), CABLE_BONES - 2); u = s - i
    return {CNAMES[i]: 1 - u, CNAMES[i + 1]: u}


bind(probe, [{"probe": 1.0}] * len(probe.data.vertices))
bind(tablet, [{"tablet": 1.0}] * len(tablet.data.vertices))
bind(screen, [{"tablet": 1.0}] * len(screen.data.vertices))
bind(cable, [cable_w(t) for t in cable_t])


# ---------------------------------------------------------------- materials (texture names as the game sees them)
def make_mat(name, tex, img_path=None, color=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bs = nt.nodes["Principled BSDF"]
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.name = tex; tn.label = tex
    if img_path and os.path.exists(img_path):
        tn.image = bpy.data.images.load(img_path)
    else:
        im = bpy.data.images.new(name + "_img", 8, 8); im.generated_color = color or (0.05, 0.05, 0.05, 1); tn.image = im
    nt.links.new(tn.outputs[0], bs.inputs["Base Color"])
    m.xray.eshader = r"models\model"; m.xray.cshader = "default"; m.xray.gamemtl = "objects\\small_box"
    return m


for obj, mat in ((probe, make_mat("probe", r"dev\dev_spectrum_x_probe", os.path.join(A, "bake", "pistol_blender", "pistol_color.png"))),
                 (tablet, make_mat("tablet", r"dev\dev_spectrum_x_tablet", os.path.join(hr.TABLET_DIR, "tablet_color.png"))),
                 (screen, make_mat("screen", r"dev\dev_spectrum_x_screen", os.path.join(A, "hud", "tex", "screen.png"))),
                 (cable, make_mat("cable", r"dev\dev_spectrum_x_cable", os.path.join(A, "hud", "tex", "cable.png")))):
    obj.data.materials.clear(); obj.data.materials.append(mat)
    for p in obj.data.polygons: p.use_smooth = obj is not screen

# ---------------------------------------------------------------- animations: poses per frame
P = ha.Poses(R); AN = ha.Anims(P)
Oi = OURS.inverted()
I4 = Matrix.Identity(4)
plans = []      # name, frames [(pose, the probe bone in the item)], params, loop
P_LOOP = dict(speed=1.0, accrue=2.0, falloff=2.0, power=1.0, flags=0, bonepart=65535)
P_ONCE = dict(P_LOOP, flags=2)
R.clamped = 0
if POSES_ONLY:
    hold = R.pose_of(Oi @ P.R0, Oi @ P.L0, fingers=rest_f)
    # both hands hold the tablet SLIDE_TWO_HAND lower on its edges, so the thumbs, laid out as at rest, lie on the
    # buttons: the tablet moved in the hand (D, detector space) for this pose only
    A0 = R.A_tab.copy(); R.use_slide(hr.SLIDE_TWO_HAND); D = R.A_tab @ A0.inverted()
    L_menu = Oi @ P.tablet_hand(**ha.MENU)
    r_menu, menu_f = hr.setup_two_hand(R, L_menu, rest_f)     # the thumbs laid out as at rest: on the buttons now
    menu = R.pose_of(r_menu, L_menu, fingers=menu_f)
    R.use_slide(0.0)
    # the probe holstered out of view: its hold place moved by PROBE_AWAY, kept on the item's root (the right hand)
    away = ha.moved(item_world(hold), ha.PROBE_AWAY, tuple(R.grip_item))
    still = {"pose_hold": (hold, I4, I4), "pose_switch": (R.pose_of(Oi @ P.R0, Oi @ P.L0, fingers=press_f), I4, I4),
             "pose_menu": (menu, item_world(menu).inverted() @ away, D)}
    for nm, fr in still.items():
        plans.append((nm, [fr] * 3, P_LOOP, True))
else:
    for nm in AN.table:
        D, loop, _ = AN.table[nm]
        seq = []; c0 = R.clamped
        for Hr, Hl, w in AN.frames(nm):
            seq.append((R.pose_of(Oi @ Hr, Oi @ Hl, fingers=fingers_at(w)), I4, I4))
        plans.append((nm, seq, P_LOOP if loop else P_ONCE, loop))
        if R.clamped > c0: print("IK reach limit: %s, %d hand-frames (the hand stops short at full reach)" % (nm, R.clamped - c0))
print("IK clamped frames:", R.clamped)


# ---------------------------------------------------------------- the cable: a sag clear of hands and devices
def hand_bvh_item(pose):
    """every hands set's mesh in item space, one BVH"""
    Mi = R.item_arm(pose).inverted(); vs, ts, n0 = [], [], 0
    for s_ in R.sets:
        v = hr.apply_m(Mi, s_.skin(pose)); vs.append(v); ts.append(s_.htris + n0); n0 += len(v)
    return BVHTree.FromPolygons([Vector(v) for v in np.vstack(vs)], [tuple(t) for t in np.vstack(ts)], all_triangles=True)


def cable_cost(pts, hb, tab_inv, probe_inv):
    c = 0.0; n = len(pts) - 1
    for i, p in enumerate(pts):
        t = i / n
        loc, nrm, idx, d = hb.find_nearest(p, 0.05)
        if loc is not None:
            sd = d if (p - loc).dot(nrm) >= 0 else -d
            if sd < CABLE_R: c += (CABLE_R - sd) ** 2
        if 0.1 < t < 0.92:
            q = tab_inv @ p
            loc, nrm, idx, d = R.tablet_bvh.find_nearest(q, 0.05)
            if loc is not None:
                sd = d if (q - loc).dot(nrm) >= 0 else -d
                if sd < CABLE_R: c += (CABLE_R - sd) ** 2
        if t > 0.1:
            q = probe_inv @ p
            loc, nrm, idx, d = R.probe_bvh.find_nearest(q, 0.05)
            if loc is not None:
                sd = d if (q - loc).dot(nrm) >= 0 else -d
                if sd < CABLE_R: c += (CABLE_R - sd) ** 2
    return c


PHIS = [math.radians(a) for a in range(-80, 81, 10)]
cable_log = {}


def solve_cable(seq, loop):
    """per frame: the item-space socket, its direction, down, and the best sag angle (smoothed over the frames)"""
    data, phis = [], []
    prev = 0.0
    for pose, prel, D in seq:
        iw = item_world(pose).inverted()
        tab = iw @ tablet_world(pose, Matrix.Identity(4)) @ D     # detector -> item (D: the tablet moved in the hand)
        conn = tab @ R.A_tab @ R.conn_t
        cd = (tab.to_3x3() @ conn_dl).normalized()
        down = (iw.to_3x3() @ Vector((0, 0, -1))).normalized()
        hb = hand_bvh_item(pose); tab_inv = tab.inverted(); pinv = prel.inverted()
        best = None
        for ph in PHIS:
            c = cable_cost(cable_curve(conn, cd, down, ph, 48, prel), hb, tab_inv, pinv) + 2e-6 * (ph - prev) ** 2
            if best is None or c < best[0]: best = (c, ph)
        prev = best[1]; phis.append(best[1]); data.append((conn, cd, down, hb, tab_inv, prel))
    n = len(phis); sm = []
    for i in range(n):
        acc = []
        for j in range(i - 3, i + 4):
            if loop: acc.append(phis[j % n])
            elif 0 <= j < n: acc.append(phis[j])
        sm.append(sum(acc) / len(acc))
    if loop and n > 1: sm[-1] = sm[0]
    res = [cable_cost(cable_curve(c, cd, dn, ph, 48, pr), hb, ti, pr.inverted()) for (c, cd, dn, hb, ti, pr), ph in zip(data, sm)]
    return [(c, cd, dn, ph, pr) for (c, cd, dn, hb, ti, pr), ph in zip(data, sm)], max(res)


# ---------------------------------------------------------------- bake
def bake_action(name, frames, params):
    H = R.H
    for pb in H.pose.bones:
        assert pb.rotation_mode != "QUATERNION", pb.name
    act = bpy.data.actions.new(name)
    H.animation_data_create(); H.animation_data.action = act
    for f, (pose, _, _) in enumerate(frames):
        bas = R.basis_of(pose)
        for pb in H.pose.bones:
            pb.matrix_basis = bas[pb.name]
            pb.keyframe_insert("location", frame=f, group=pb.name)
            pb.keyframe_insert("rotation_euler", frame=f, group=pb.name)
    for k, v in params.items():
        setattr(act.xray, k, v)
    act.xray.fps = FPS; act.use_fake_user = True
    return act


def bake_item_action(name, frames, cab, params):
    act = bpy.data.actions.new(name + "@item")
    IA.animation_data_create(); IA.animation_data.action = act
    for f, ((pose, _, D), (conn, cd, down, ph, prel)) in enumerate(zip(frames, cab)):
        iw = item_world(pose).inverted()
        want = {"tablet": iw @ tablet_world(pose, Matrix.Identity(4)) @ D, "probe": prel}
        for k, M in enumerate(bone_frames(cable_curve(conn, cd, down, ph, N_SEG, prel))):
            want[CNAMES[k]] = M
        for bn in ITEM_BONES:
            pbn = IA.pose.bones[bn]
            pbn.matrix_basis = Matrix.Identity(4) if bn == "wpn_body" else REST[bn].inverted() @ (want[bn] @ KI)
            pbn.keyframe_insert("location", frame=f, group=bn)
            pbn.keyframe_insert("rotation_euler", frame=f, group=bn)
    for k, v in params.items(): setattr(act.xray, k, v)
    act.xray.fps = FPS; act.use_fake_user = True
    return act


hand_acts, item_acts, lengths = [], [], {}
for nm, seq, par, loop in plans:
    cab, worst = solve_cable(seq, loop)
    cable_log[nm] = worst
    full = "%s_%s" % (NAME, nm)
    hand_acts.append(bake_action(full, seq, par))
    item_acts.append(bake_item_action(full, seq, cab, par))
    lengths[full] = round((len(seq) - 1) / FPS, 3)
    print("ANIM", full, len(seq), "frames, cable residual %.2e" % worst)

# ---------------------------------------------------------------- numbers for the configs
def hpb_of(M):
    """X-Ray Fmatrix::setHPB angles (deg) of a rotation given as columns i, j, k (X-Ray coords)"""
    i, j, k = M.col[0], M.col[1], M.col[2]
    p = math.asin(max(-1, min(1, k[1]))); h = math.atan2(-k[0], k[2]); b = math.atan2(-i[1], j[1])
    return [math.degrees(x) for x in (h, p, b)]


S3 = XS.to_3x3()
tl_det = R.A_tab @ Vector((x0, y0, z)) + (R.A_tab.to_3x3() @ Vector((0, 0, 1))).normalized() * UI_LIFT
ux = (R.A_tab.to_3x3() @ Vector((0, 1, 0))).normalized()     # screen right
uy = (R.A_tab.to_3x3() @ Vector((1, 0, 0))).normalized()     # screen down
ix, jy = S3 @ ux, S3 @ uy
kz = ix.cross(jy)
Mui = Matrix((ix, jy, kz)).transposed()
ui_rot = hpb_of(Mui)
from xr_space import hpb as _hpb
chk = _hpb(*[math.radians(a) for a in ui_rot]).to_3x3()
ui_pos = list(S3 @ tl_det)
size = [(y1 - y0) * hr.TABLET_SCALE, (x1 - x0) * hr.TABLET_SCALE]
# the menu pose: the screen's corners in HUD camera space (X-Ray axes: x right, y up, z forward)
mi, _, mD = dict((nm, seq) for nm, seq, par, loop in plans)["pose_menu" if POSES_ONLY else "menu_idle"][0]
corners = []
for p in ((x0, y0, z), (x0, y1, z), (x1, y1, z), (x1, y0, z)):          # TL, TR, BR, BL
    c = tablet_world(mi, mD @ R.A_tab) @ Vector(p)
    corners += [c.x, c.z, c.y]
nums = {"custom_ui_bone": "tablet", "custom_ui_pos": ui_pos, "custom_ui_rot": ui_rot,
        "ui_rot_check": max(abs(a - b) for a, b in zip([x for r in chk for x in r], [x for r in Mui for x in r])),
        "screen_size": size, "menu_screen_corners": corners, "lengths": lengths, "cable_residual": cable_log,
        "ik_clamped": R.clamped, "probe_shift": list(R.P_probe.translation)}
NUMS_DIR = OUT if POSES_ONLY else os.path.join(A, "hud")     # the pose check does not touch the game's numbers
json.dump(nums, open(os.path.join(NUMS_DIR, "build_numbers.json"), "w"), indent=1)
print("NUMBERS", json.dumps(nums))

# ---------------------------------------------------------------- export
H = R.H
H.animation_data.action = None; IA.animation_data.action = None
omf_dir = os.path.join(OUT, "meshes", "anomaly_weapons", "hud_hands_animation"); os.makedirs(omf_dir, exist_ok=True)
H.xray.motions_collection.clear()
for a in hand_acts:
    it = H.xray.motions_collection.add(); it.name = a.name
for o in scn.objects: o.select_set(o == H)
bpy.context.view_layer.objects.active = H
bpy.ops.xray_export.omf_file(filepath=os.path.join(omf_dir, "dev_hand_spectrum_x_hud_animation.omf"), fmt_ver="cscop",
                             export_mode="OVERWRITE", export_motions=True, export_bone_parts=True, high_quality=True)
for a in hand_acts: a.name = a.name + "@hands"
for a in item_acts: a.name = a.name.replace("@item", "")
IA.xray.motions_collection.clear()
for a in item_acts:
    it = IA.xray.motions_collection.add(); it.name = a.name
dev_dir = os.path.join(OUT, "meshes", "dynamics", "devices", "dev_spectrum_x"); os.makedirs(dev_dir, exist_ok=True)
for o in scn.objects: o.select_set(o == IA or o.parent == IA)
bpy.context.view_layer.objects.active = IA
bpy.ops.xray_export.ogf_file(filepath=os.path.join(dev_dir, "dev_spectrum_x_hud.ogf"), fmt_version="cscop",
                             export_motions=True, hq_export=True, use_export_paths=False, texture_name_from_image_path=False)
for a in item_acts: a.name = a.name + "@item"
for a in hand_acts: a.name = a.name.replace("@hands", "")
print("EXPORTED")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT if POSES_ONLY else os.path.join(A, "hud"), "spectrum_x_hud.blend"), compress=True)

# ---------------------------------------------------------------- world model: the same meshes in the bind pose, one bone
for obj in (probe, tablet, screen, cable):
    for bn in ITEM_BONES[1:]:
        obj.vertex_groups.remove(obj.vertex_groups[bn])
    obj.vertex_groups["wpn_body"].add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
bpy.context.view_layer.objects.active = IA
for o in scn.objects: o.select_set(o == IA)
bpy.ops.object.mode_set(mode="EDIT")
for bn in ITEM_BONES[1:]:
    IA.data.edit_bones.remove(IA.data.edit_bones[bn])
bpy.ops.object.mode_set(mode="OBJECT")
IA.xray.motions_collection.clear()
# physics of the dropped item: one box around everything (X-Ray axes: x, z, y of Blender's), 1.6 kg
allv = np.array([v.co[:] for o in (probe, tablet, cable) for v in o.data.vertices])
lo_, hi_ = allv.min(0), allv.max(0); cen, hs = (lo_ + hi_) / 2, (hi_ - lo_) / 2
sh = IA.data.bones["wpn_body"].xray.shape
sh.type = "1"; sh.box_rot = (1, 0, 0, 0, 1, 0, 0, 0, 1)
sh.box_trn = (cen[0], cen[2], cen[1]); sh.box_hsz = (hs[0], hs[2], hs[1]); sh.version_data = 1
IA.data.bones["wpn_body"].xray.mass.value = 1.6
for o in scn.objects: o.select_set(o == IA or o.parent == IA)
bpy.ops.xray_export.ogf_file(filepath=os.path.join(dev_dir, "dev_spectrum_x.ogf"), fmt_version="cscop",
                             export_motions=False, hq_export=False, use_export_paths=False, texture_name_from_image_path=False)
print("EXPORTED world")
