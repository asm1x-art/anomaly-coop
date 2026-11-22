"""Render the exported HUD files (round trip: what the game gets) through the HUD camera at chosen frames.
blender -b -P preview_hud.py -- <vanilla meshes> <gamedata> <out_dir> <motion>:<frame>[,<frame>...] ...
        [--fov 0.45] [--res 960x540] [--ui <png>] [--cam ex,ey,ez,tx,ty,tz,fov_deg] [--tag name]
Loads wpn_hand_01.ogf + dev_hand_spectrum_x_hud_animation.omf and dev_spectrum_x_hud.ogf (with its motions), places
the item as the engine does (hands offset of the hud section, lead_gun, item offset). The hands get their game
texture (act_arm_1, a PNG in <assets>\hud\tex), the devices their bakes. --ui: a picture put where the engine draws
the 3D screen (custom_ui_* from <assets>\hud\build_numbers.json, the engine's math), to check its place and that it
reads the right way round. Frames are written as <motion>_<frame>.png; sheets come from make_sheets.py."""
import bpy, sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xr_space import offset_b, hpb, S as XS
import hud_view
from mathutils import Matrix, Vector
a = sys.argv[sys.argv.index("--") + 1:]
G, GD, out = a[0], a[1], a[2]; os.makedirs(out, exist_ok=True)
A = r"X:\coop\assets\spectrum-x"
fov = float(a[a.index("--fov") + 1]) if "--fov" in a else 0.45
res = a[a.index("--res") + 1] if "--res" in a else "960x540"
ui_png = a[a.index("--ui") + 1] if "--ui" in a else None
skip = {a[i + 1] for i, x in enumerate(a) if x in ("--ui", "--cam", "--tag", "--fov", "--res")}
jobs = [x for x in a[3:] if ":" in x and not x.startswith("--") and x not in skip]
bpy.ops.wm.read_homefile(use_empty=True)
from io_scene_xray.formats.motions.const import MATRIX_BONE_INVERTED
K = MATRIX_BONE_INVERTED.to_4x4()
OURS = offset_b((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15)); ITEM = offset_b((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))
sc = bpy.context.scene


def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]


hands = imp_ogf(G + r"\anomaly_weapons\hands\wpn_hand_01.ogf")
H = next(o for o in hands if o.type == "ARMATURE")
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
w, h = map(int, res.split("x"))
cam = hud_view.setup(A, (w, h), fov)
tag = a[a.index("--tag") + 1] if "--tag" in a else ""
if "--cam" in a:      # a close-up camera (HUD camera space, Blender axes) instead of the eye
    c = [float(x) for x in a[a.index("--cam") + 1].split(",")]
    hud_view.look_at(cam, c[:3], c[3:6], fov_deg=c[6])
hud_view.texture_all(A, hands + item)

if ui_png:
    # the engine: LM = item * bone(tablet) * (HPB(custom_ui_rot) + custom_ui_pos); a UI point (x, y) -> LM (x, y, 0)
    N = json.load(open(os.path.join(A, "hud", "build_numbers.json")))
    W_, H_ = N["screen_size"]
    m = bpy.data.meshes.new("ui"); xs = [(0, 0), (W_, 0), (W_, H_), (0, H_)]
    m.from_pydata([(x, y, 0) for x, y in xs], [], [(0, 1, 2, 3)])
    uv = m.uv_layers.new(); 
    for l, (x, y) in zip(m.loops, xs): uv.data[l.index].uv = (x / W_, 1 - y / H_)
    ui = bpy.data.objects.new("ui", m); sc.collection.objects.link(ui)
    mat = bpy.data.materials.new("ui"); mat.use_nodes = True
    tn = mat.node_tree.nodes.new("ShaderNodeTexImage"); tn.image = bpy.data.images.load(ui_png)
    mat.node_tree.links.new(tn.outputs[0], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    m.materials.append(mat)
    U = hpb(*[math.radians(x) for x in N["custom_ui_rot"]]); U.translation = Vector(N["custom_ui_pos"])
    ui_local = XS @ U          # X-Ray UI frame -> Blender coords of the bone (the bone's X-Ray frame is pose @ K)


def assign(obj, act):
    obj.animation_data_create(); obj.animation_data.action = act
    if hasattr(obj.animation_data, "action_slot") and act.slots:
        obj.animation_data.action_slot = act.slots[0]


for j in jobs:
    mot, frames = j.split(":")
    assign(H, hand_acts[mot]); assign(IA, item_acts[mot])
    for fr in frames.split(","):
        sc.frame_set(int(fr))
        IA.matrix_world = OURS @ H.pose.bones["lead_gun"].matrix @ K @ ITEM
        bpy.context.view_layer.update()
        if ui_png:
            ui.matrix_world = IA.matrix_world @ IA.pose.bones["tablet"].matrix @ K @ ui_local
        sc.render.filepath = os.path.join(out, "%s%s_%03d.png" % (tag, mot, int(fr)))
        bpy.ops.render.render(write_still=True)
