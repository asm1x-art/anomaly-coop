r"""Spectrum-X first-person HUD: hands animations (.omf) + item model with its own animations (.ogf), from
the baked low-poly probe and tablet (retopo_blender.py + bake.py), in one Blender scene.

blender -b -P build_hud.py -- --meshes <vanilla meshes dir> --assets <X:\coop\assets\spectrum-x> --out <gamedata>
        [--previews]

Poses are built from vanilla animations, not keyed by hand:
  right arm  <- the PM's anims (pm_idle, pm_draw, ...) seen through the PM's HUD offsets,
  left arm   <- the Veles detector's anims (d2_idle, d2_draw, ...) seen through the detector's HUD offsets,
both moved into one hands model at the PM's offsets (the hud section uses those). The probe sits where the PM sits
(item_position/orientation = the PM's), the tablet where the Veles sits in the left hand; the item's "tablet" bone
follows l_hand frame by frame. Aim (RMB measure) and bore are rigid moves of one arm on top of the idle.
Engine conventions checked on the binoculars / PM / Veles: item = hands * bone(lead_gun) * MATRIX_BONE_INVERTED *
HPB(item_orientation)+item_position (see xr_space.py).

Writes:
  <out>/meshes/anomaly_weapons/hud_hands_animation/dev_hand_spectrum_x_hud_animation.omf
  <out>/meshes/dynamics/devices/dev_spectrum_x/dev_spectrum_x_hud.ogf   (bones wpn_body, tablet, cable_mid; motions)
  <out>/meshes/dynamics/devices/dev_spectrum_x/dev_spectrum_x.ogf       (world model, one bone)
  <assets>/hud/spectrum_x_hud.blend, <assets>/hud/previews/*.png
"""
import bpy, bmesh, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xr_space import offset_b
from mathutils import Matrix, Vector, Quaternion
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
G = opt("--meshes"); A = opt("--assets"); OUT = opt("--out")
PREVIEWS = "--previews" in argv

# ---- numbers (the hud section in configs/items/items/items_spectrum_x.ltx must carry the same offsets)
PM_HANDS = ((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15))          # [wpn_pm_hud] hands_position / orientation
DET_HANDS = ((0.05, -0.1895, -0.1), (2.0, 2.0, 0.0))           # [detector_base_hud]
PM_ITEM = ((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))   # [wpn_pm_hud] item_*
DET_ITEM = ((-0.078949, 0.039172, -0.019197), (320.606964, -194.089020, -186.572464))  # [detector_advanced_hud]
PROBE_SCALE = 0.20        # Tripo units -> metres: probe 20 cm long
TABLET_SCALE = 0.20       # tablet 14 cm tall
TABLET_SHIFT_X = 0.030    # in the Veles frame: toward the fingers, the thumb rests on the left bumper
AIM_POINT = (0.03, 0.55, -0.10)   # camera space (Blender axes): where the probe's lens goes on RMB
FPS = 30
NAME = "spectrum_x"

from io_scene_xray.formats.motions.const import MATRIX_BONE, MATRIX_BONE_INVERTED
K = MATRIX_BONE_INVERTED.to_4x4()      # pose_bone.matrix @ K = X-Ray bone frame (Blender axes)
KI = MATRIX_BONE.to_4x4()

OFF_R = offset_b(*PM_HANDS); OFF_L = offset_b(*DET_HANDS); OURS = OFF_R
ITEM_OFF = offset_b(*PM_ITEM); DET_OFF = offset_b(*DET_ITEM)
CR = OURS.inverted() @ OFF_R; CL = OURS.inverted() @ OFF_L

bpy.ops.wm.read_homefile(use_empty=True)
scn = bpy.context.scene
scn.render.fps = FPS


def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]


# ---------------------------------------------------------------- hands + source anims
H = next(o for o in imp_ogf(G + r"\anomaly_weapons\hands\wpn_hand_01.ogf") if o.type == "ARMATURE")
H.name = "hands"
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.parent == H: o.name = "hands_mesh"
bpy.context.view_layer.objects.active = H
for f, parts in (("wpn_hand_pm_hud_animation.omf", True), ("dev_hand_detector_2_hud_animation.omf", False)):
    bpy.ops.xray_import.omf(directory=G + r"\anomaly_weapons\hud_hands_animation", files=[{"name": f}],
                            import_motions=True, import_bone_parts=parts, add_to_motion_list=False)
H.animation_data_create()
BONES = [pb.name for pb in H.pose.bones]
is_left = lambda n: n.startswith("l_") or n.startswith("bip01_l_")
is_right = lambda n: n.startswith("r_") or n.startswith("bip01_r_") or n == "lead_gun"
_cache = {}


def sample(act, frame):
    """armature-space pose matrices of every bone of a vanilla action at a (fractional) frame"""
    key = (act, round(frame, 3))
    if key not in _cache:
        H.animation_data.action = bpy.data.actions[act]
        fi = int(math.floor(frame)); scn.frame_set(fi, subframe=frame - fi)
        _cache[key] = {pb.name: pb.matrix.copy() for pb in H.pose.bones}
    return _cache[key]


def act_len(act):
    return bpy.data.actions[act].frame_range[1]


def src_frame(act, f, n, mode):
    L = act_len(act)
    if mode == "stretch":   # the whole source over our n frames
        return L * f / max(n - 1, 1)
    if mode == "hold0":
        return 0.0
    return min(f, L)


def rigid(pivot, rot, move):
    """armature-space rigid move: rotate about pivot, then translate"""
    return Matrix.Translation(pivot + move) @ rot.to_matrix().to_4x4() @ Matrix.Translation(-pivot)


def smooth(x):
    x = min(max(x, 0.0), 1.0); return x * x * (3 - 2 * x)


def compose(right, left, n, rmode="stretch", lmode="stretch", rmod=None, lmod=None):
    """frames -> {bone: armature-space matrix}; right/left = vanilla action names"""
    out = []
    for f in range(n):
        r = sample(right, src_frame(right, f, n, rmode)); l = sample(left, src_frame(left, f, n, lmode))
        tr = rmod(f, n) if rmod else Matrix.Identity(4)
        tl = lmod(f, n) if lmod else Matrix.Identity(4)
        m = {}
        for b in BONES:
            m[b] = (tl @ CL @ l[b]) if is_left(b) else (tr @ CR @ r[b])
        # left fingers keep their grip of frame 0 (the detector's idle presses buttons: the thumb would cross the screen)
        l0 = sample(left, 0.0)
        for b in BONES:
            if is_left(b) and "finger" in b:
                m[b] = m["l_hand"] @ l0["l_hand"].inverted() @ l0[b]
        out.append(m)
    return out


def basis_of(pose):
    """armature-space pose matrices -> pose_bone.matrix_basis"""
    res = {}
    for pb in H.pose.bones:
        b = pb.bone
        if b.parent:
            rest_rel = b.parent.matrix_local.inverted() @ b.matrix_local
            res[pb.name] = rest_rel.inverted() @ pose[b.parent.name].inverted() @ pose[pb.name]
        else:
            res[pb.name] = b.matrix_local.inverted() @ pose[pb.name]
    return res


def bake_action(name, frames, params):
    act = bpy.data.actions.new(name)
    H.animation_data.action = act
    for f, pose in enumerate(frames):
        bas = basis_of(pose)
        for pb in H.pose.bones:
            pb.matrix_basis = bas[pb.name]
            pb.keyframe_insert("location", frame=f, group=pb.name)
            pb.keyframe_insert("rotation_euler", frame=f, group=pb.name)
    for k, v in params.items():
        setattr(act.xray, k, v)
    act.xray.fps = FPS
    act.use_fake_user = True
    return act


# ---------------------------------------------------------------- the device in hand space
idle0 = compose("pm_idle", "d2_idle", 1)[0]
# item space = where the PM sits: world = OURS @ lead_gun @ K @ ITEM_OFF
def item_world(pose):
    return OURS @ pose["lead_gun"] @ K @ ITEM_OFF


def tablet_world(pose, A_tab):
    return OURS @ pose["l_hand"] @ K @ DET_OFF @ A_tab


# PM grip (item space) and Veles body (detector space), from the vanilla meshes
pm_objs = imp_ogf(G + r"\anomaly_weapons\wpn_pm\wpn_pm_hud.ogf")
pm_arm = next(o for o in pm_objs if o.type == "ARMATURE")
pm_v = np.array([v.co[:] for o in pm_objs if o.type == "MESH" and o.name.endswith("00") for v in o.data.vertices])
band = pm_v[(pm_v[:, 2] < -0.02) & (pm_v[:, 2] > -0.06)]
pm_grip = Vector(band.mean(0)); pm_grip.z = -0.005
print("PM grip", pm_grip)


def load_low(blend, name):
    with bpy.data.libraries.load(blend) as (src, dst):
        dst.objects = ["LOW"]
    o = dst.objects[0]; o.name = name; scn.collection.objects.link(o)
    o.data = o.data.copy(); o.data.name = name
    return o


probe = load_low(os.path.join(A, "bake", "pistol_blender", "pistol_bake.blend"), "probe")
tablet = load_low(os.path.join(A, "bake", "tablet_blender", "tablet_bake.blend"), "tablet")
# probe: lens -Y -> +Y (item forward), top +Z; grip centre onto the PM's grip
pv = np.array([v.co[:] for v in probe.data.vertices])
gb = pv[(pv[:, 2] < -0.10) & (pv[:, 2] > -0.20) & (pv[:, 1] > -0.05)]
pg = Vector((gb[:, 0].mean(), gb[:, 1].mean(), -0.05))
R180 = Matrix.Rotation(math.pi, 4, "Z")
P_probe = Matrix.Translation(pm_grip) @ R180 @ Matrix.Scale(PROBE_SCALE, 4) @ Matrix.Translation(-pg)
probe.data.transform(P_probe); probe.matrix_world = Matrix.Identity(4)
# cable plug of the probe (end of the strain relief) and its direction, item space
plug_p = P_probe @ Vector((0.0, 0.37, 0.325)); plug_d = (R180 @ Vector((0, 1, 0))).normalized()
# tablet: top -x -> +Y, front +z -> +Z, right +y -> +X; back on the palm, centred on the Veles body
tv = np.array([v.co[:] for v in tablet.data.vertices])
A_rot = Matrix(((0, 1, 0, 0), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
cx, cy, zb = (tv[:, 0].min() + tv[:, 0].max()) / 2, (tv[:, 1].min() + tv[:, 1].max()) / 2, tv[:, 2].min()
A_tab = Matrix.Translation(Vector((TABLET_SHIFT_X, 0.0, 0.004))) @ A_rot @ Matrix.Scale(TABLET_SCALE, 4) @ Matrix.Translation(Vector((-cx, -cy, -zb)))
con = tv[(tv[:, 0] > 0.255) & (np.abs(tv[:, 1]) < 0.06)]
conn_t = Vector((0.29, con[:, 1].mean(), con[:, 2].mean())) if len(con) else Vector((0.29, 0, 0))
# the screen: a plane on the glass (tablet's own coords), own material for the future UI
SCREEN = (-0.383, 0.042, -0.171, 0.171, 0.0394 + 0.0012)

# bind pose = idle frame 0, everything in item space
IW0 = item_world(idle0); IW0i = IW0.inverted()
T0 = IW0i @ tablet_world(idle0, Matrix.Identity(4))      # detector space -> item space at bind
tablet.data.transform(T0 @ A_tab); tablet.matrix_world = Matrix.Identity(4)
conn_i = T0 @ A_tab @ conn_t
conn_d = (T0 @ A_tab).to_3x3() @ Vector((1, 0, 0)); conn_d.normalize()

# screen plane
sm = bpy.data.meshes.new("screen"); bm = bmesh.new()
x0, x1, y0, y1, z = SCREEN
vs = [bm.verts.new(T0 @ A_tab @ Vector(p)) for p in ((x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z))]
face = bm.faces.new(vs); uvl = bm.loops.layers.uv.new("UVMap")
for l, uv in zip(face.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): l[uvl].uv = uv
bmesh.ops.triangulate(bm, faces=bm.faces[:]); bm.normal_update()
# the plane must face out of the glass: check against the tablet's front (+z in its own coords)
front = (T0 @ A_tab).to_3x3() @ Vector((0, 0, 1))
bm.faces.ensure_lookup_table()
if bm.faces[0].normal.dot(front) < 0: bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
bm.to_mesh(sm); bm.free()
screen = bpy.data.objects.new("screen", sm); scn.collection.objects.link(screen)

# ---------------------------------------------------------------- the coiled cable (bind pose)
cam_down_i = (IW0i.to_3x3() @ Vector((0, 0, -1))).normalized()   # camera-space down, seen in item space


def bez(p0, p1, p2, p3, t):
    u = 1 - t
    return p0 * u ** 3 + p1 * 3 * u * u * t + p2 * 3 * u * t * t + p3 * t ** 3


L = (conn_i - plug_p).length
c0 = plug_p + plug_d * L * 0.35 + cam_down_i * L * 0.25
c1 = conn_i + conn_d * L * 0.35 + cam_down_i * L * 0.25
N_SEG, TURNS, R_HELIX, R_TUBE, SIDES = 360, 26, 0.0045, 0.0018, 6
pts = [bez(plug_p, c0, c1, conn_i, i / N_SEG) for i in range(N_SEG + 1)]
# parallel-transport frames
tang = [(pts[min(i + 1, N_SEG)] - pts[max(i - 1, 0)]).normalized() for i in range(N_SEG + 1)]
nrm = tang[0].orthogonal().normalized(); frames = []
for i in range(N_SEG + 1):
    if i: nrm = (nrm - tang[i] * nrm.dot(tang[i])).normalized()
    frames.append((tang[i], nrm, tang[i].cross(nrm)))
center = []
for i, p in enumerate(pts):
    t = i / N_SEG; fade = smooth(t / 0.08) * smooth((1 - t) / 0.08)
    a = 2 * math.pi * TURNS * t
    tg, n1, n2 = frames[i]
    center.append(p + (n1 * math.cos(a) + n2 * math.sin(a)) * R_HELIX * fade)
cm = bpy.data.meshes.new("cable"); bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
rings = []
for i, c in enumerate(center):
    tg = (center[min(i + 1, N_SEG)] - center[max(i - 1, 0)]).normalized()
    n1 = (frames[i][1] - tg * frames[i][1].dot(tg)).normalized(); n2 = tg.cross(n1)
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
cable_t = [i // SIDES / N_SEG for i in range(len(cm.vertices))]   # param along the cable per vertex

# ---------------------------------------------------------------- item armature (from the PM's: wpn_body = X-Ray identity)
for o in pm_objs:
    if o.type == "MESH": bpy.data.objects.remove(o)
IA = pm_arm; IA.name = "spectrum_x_hud"; IA.data.name = "spectrum_x_hud"
for c in list(IA.data.collections): IA.data.collections.remove(c)
bpy.context.view_layer.objects.active = IA
for o in scn.objects: o.select_set(o == IA)
bpy.ops.object.mode_set(mode="EDIT")
eb = IA.data.edit_bones
for b in list(eb):
    if b.name != "wpn_body": eb.remove(b)
root = eb["wpn_body"]
TAB0 = T0 @ Matrix.Identity(4)          # tablet bone frame at bind = detector frame in item space
MID0 = Matrix.Translation((plug_p + conn_i) / 2)
for nm, F in (("tablet", TAB0), ("cable_mid", MID0)):
    e = eb.new(nm); e.head = (0, 0, 0); e.tail = (0, 0.02, 0); e.matrix = F @ KI; e.length = 0.02; e.parent = root
bpy.ops.object.mode_set(mode="OBJECT")
REST = {b.name: b.matrix_local.copy() for b in IA.data.bones}
for c in list(IA.data.collections): IA.data.collections.remove(c)
_bc = IA.data.collections.new("default")
for b in IA.data.bones: _bc.assign(b)

# meshes -> armature, weights
def bind(obj, weights):
    obj.parent = IA
    md = obj.modifiers.new("arm", "ARMATURE"); md.object = IA
    for bn in ("wpn_body", "tablet", "cable_mid"):
        obj.vertex_groups.new(name=bn)
    for i, w in enumerate(weights):
        for bn, x in w.items():
            if x > 1e-4: obj.vertex_groups[bn].add([i], x, "REPLACE")


bind(probe, [{"wpn_body": 1.0}] * len(probe.data.vertices))
bind(tablet, [{"tablet": 1.0}] * len(tablet.data.vertices))
bind(screen, [{"tablet": 1.0}] * len(screen.data.vertices))
bind(cable, [{"wpn_body": (1 - t) ** 2, "cable_mid": 2 * t * (1 - t), "tablet": t * t} for t in cable_t])

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
                 (tablet, make_mat("tablet", r"dev\dev_spectrum_x_tablet", os.path.join(A, "bake", "tablet_blender", "tablet_color.png"))),
                 (screen, make_mat("screen", r"dev\dev_spectrum_x_screen", os.path.join(A, "hud", "tex", "screen.png"))),
                 (cable, make_mat("cable", r"dev\dev_spectrum_x_cable", os.path.join(A, "hud", "tex", "cable.png")))):
    obj.data.materials.clear(); obj.data.materials.append(mat)
    for p in obj.data.polygons: p.use_smooth = obj is not screen

# ---------------------------------------------------------------- animations
def item_frames(frames):
    """per frame: item-space frames of the tablet and the cable's middle"""
    res = []
    for pose in frames:
        iw = item_world(pose).inverted()
        tab = iw @ tablet_world(pose, Matrix.Identity(4))
        pa, pb_ = Matrix.Identity(4), tab @ TAB0.inverted()     # root (static) and the tablet's motion
        # mid bone: halfway between not moving and the tablet's motion
        q = pb_.to_quaternion(); qm = Quaternion().slerp(q, 0.5)
        mid = Matrix.Translation(pb_.to_translation() * 0.5) @ qm.to_matrix().to_4x4() @ MID0
        res.append({"tablet": tab, "cable_mid": mid})
    return res


def bake_item_action(name, frames, params):
    act = bpy.data.actions.new(name + "@item")
    IA.animation_data_create(); IA.animation_data.action = act
    for f, fr in enumerate(item_frames(frames)):
        for bn in ("wpn_body", "tablet", "cable_mid"):
            pbn = IA.pose.bones[bn]
            if bn == "wpn_body":
                pbn.matrix_basis = Matrix.Identity(4)
            else:
                pose = fr[bn] @ KI
                pbn.matrix_basis = REST[bn].inverted() @ pose     # parent wpn_body stays at rest
            pbn.keyframe_insert("location", frame=f, group=bn)
            pbn.keyframe_insert("rotation_euler", frame=f, group=bn)
    for k, v in params.items(): setattr(act.xray, k, v)
    act.xray.fps = FPS; act.use_fake_user = True
    return act


P_LOOP = dict(speed=1.0, accrue=2.0, falloff=2.0, power=1.0, flags=0, bonepart=65535)
P_ONCE = dict(P_LOOP, flags=2)

# aim (RMB measure): the right arm moves so that the probe's lens is ahead, a bit right of centre, pointing forward
lens_item = P_probe @ Vector((0.0, -0.5, 0.29))
def aim_move(pose):
    iw = item_world(pose)
    lens = OURS.inverted() @ iw @ lens_item                      # hands-armature space
    fwd = (OURS.inverted().to_3x3() @ iw.to_3x3() @ Vector((0, 1, 0))).normalized()
    want_pos = OURS.inverted() @ Vector(AIM_POINT)
    want_fwd = (OURS.inverted().to_3x3() @ Vector((0, 1, 0))).normalized()
    rot = fwd.rotation_difference(want_fwd)
    return rigid(lens, rot, want_pos - lens)

T_AIM = aim_move(idle0)
def aim_mod(k0, k1):
    def mod(f, n):
        x = smooth(k0 + (k1 - k0) * f / max(n - 1, 1))
        loc = T_AIM.to_translation() * x; q = Quaternion().slerp(T_AIM.to_quaternion(), x)
        return Matrix.Translation(loc) @ q.to_matrix().to_4x4()
    return mod

# bore: the tablet comes up and tilts toward the eyes, then back
tab_c = (OURS.inverted() @ tablet_world(idle0, A_tab) @ Vector((cx, cy, 0.05)))
def bore_mod(f, n):
    x = math.sin(math.pi * f / (n - 1)) ** 2
    rot = Quaternion(Vector((1, 0, 0)), math.radians(-22) * x) @ Quaternion(Vector((0, 0, 1)), math.radians(-10) * x)
    return rigid(tab_c, rot, Vector((0.035, 0.0, 0.05)) * x)

sec = lambda s: int(round(s * FPS)) + 1
plan = [
    # name, right src, left src, frames, rmode, lmode, rmod, lmod, params
    ("draw", "pm_draw", "d2_draw", sec(0.75), "stretch", "stretch", None, None, P_ONCE),
    ("holster", "pm_holster", "d2_holster", sec(0.55), "stretch", "stretch", None, None, P_ONCE),
    ("idle", "pm_idle", "d2_idle", sec(6.3), "stretch", "stretch", None, None, P_LOOP),
    ("idle_moving", "pm_idle_moving", "d2_move", sec(25 / 30 / 0.9), "stretch", "stretch", None, None, P_LOOP),
    ("idle_sprint", "pm_idle_sprint", "d2_sprint", sec(25 / 30 / 1.2), "stretch", "stretch", None, None, P_LOOP),
    ("idle_crouch", "pm_idle_crouch", "d2_crouch", sec(25 / 30 / 0.6), "stretch", "stretch", None, None, P_LOOP),
    ("aim_start", "pm_idle", "d2_idle", sec(0.30), "hold0", "hold0", aim_mod(0, 1), None, P_ONCE),
    ("aim", "pm_idle", "d2_idle", sec(2.0), "stretch", "stretch", aim_mod(1, 1), None, P_LOOP),
    ("aim_end", "pm_idle", "d2_idle", sec(0.30), "hold0", "hold0", aim_mod(1, 0), None, P_ONCE),
    ("bore", "pm_idle", "d2_idle", sec(3.0), "stretch", "stretch", None, bore_mod, P_ONCE),
]
hand_acts, item_acts, all_frames = [], [], {}
for nm, r, l, n, rm, lm, rmod, lmod, par in plan:
    fr = compose(r, l, n, rm, lm, rmod, lmod)
    all_frames[nm] = fr
    full = "%s_%s" % (NAME, nm)
    hand_acts.append(bake_action(full, fr, par))
    item_acts.append(bake_item_action(full, fr, par))
    print("ANIM", full, n, "frames")

# ---------------------------------------------------------------- export
H.animation_data.action = None; IA.animation_data.action = None
omf_dir = os.path.join(OUT, "meshes", "anomaly_weapons", "hud_hands_animation"); os.makedirs(omf_dir, exist_ok=True)
H.xray.motions_collection.clear()
for a in hand_acts:
    it = H.xray.motions_collection.add(); it.name = a.name
for o in scn.objects: o.select_set(o == H)
bpy.context.view_layer.objects.active = H
bpy.ops.xray_export.omf_file(filepath=os.path.join(omf_dir, "dev_hand_spectrum_x_hud_animation.omf"), fmt_ver="cscop",
                             export_mode="OVERWRITE", export_motions=True, export_bone_parts=True, high_quality=True)
# item motions are named like the hand motions (the engine plays the same name on both)
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
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A, "hud", "spectrum_x_hud.blend"), compress=True)

# ---------------------------------------------------------------- world model: the same meshes in the bind pose, one bone
for obj in (probe, tablet, screen, cable):
    vg = {g.index: g.name for g in obj.vertex_groups}
    for bn in ("tablet", "cable_mid"):
        obj.vertex_groups.remove(obj.vertex_groups[bn])
    obj.vertex_groups["wpn_body"].add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
bpy.context.view_layer.objects.active = IA
for o in scn.objects: o.select_set(o == IA)
bpy.ops.object.mode_set(mode="EDIT")
for bn in ("tablet", "cable_mid"):
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
