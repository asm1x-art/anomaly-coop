"""Render the exported HUD files (round trip: what the game gets) through the HUD camera at chosen frames.
blender -b -P preview_hud.py -- <vanilla meshes> <gamedata> <out_dir> <motion>:<frame>[,<frame>...] ...
        [--fov 0.64] [--res 960x540] [--eevee]
Loads wpn_hand_01.ogf + dev_hand_spectrum_x_hud_animation.omf and dev_spectrum_x_hud.ogf (with its motions), places
the item as the engine does (hands offset of the hud section, lead_gun, item offset)."""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xr_space import offset_b
a = sys.argv[sys.argv.index("--") + 1:]
G, GD, out = a[0], a[1], a[2]; os.makedirs(out, exist_ok=True)
fov = float(a[a.index("--fov") + 1]) if "--fov" in a else 0.64
res = a[a.index("--res") + 1] if "--res" in a else "960x540"
jobs = [x for x in a[3:] if ":" in x and not x.startswith("--")]
bpy.ops.wm.read_homefile(use_empty=True)
from io_scene_xray.formats.motions.const import MATRIX_BONE_INVERTED
K = MATRIX_BONE_INVERTED.to_4x4()
OURS = offset_b((-0.031, -0.17, 0.0), (-0.5, 1.0, 1.15)); ITEM = offset_b((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))
sc = bpy.context.scene


def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]


H = next(o for o in imp_ogf(G + r"\anomaly_weapons\hands\wpn_hand_01.ogf") if o.type == "ARMATURE")
bpy.context.view_layer.objects.active = H
acts0 = set(bpy.data.actions)
bpy.ops.xray_import.omf(directory=GD + r"\meshes\anomaly_weapons\hud_hands_animation", files=[{"name": "dev_hand_spectrum_x_hud_animation.omf"}],
                        import_motions=True, import_bone_parts=False)
hand_acts = {x.name: x for x in bpy.data.actions if x not in acts0}
acts1 = set(bpy.data.actions)
item = imp_ogf(GD + r"\meshes\dynamics\devices\dev_spectrum_x\dev_spectrum_x_hud.ogf")
IA = next(o for o in item if o.type == "ARMATURE")
item_acts = {x.name.split(".")[0]: x for x in bpy.data.actions if x not in acts1}
print("ACTS hands", sorted(hand_acts), "item", sorted(item_acts))
H.matrix_world = OURS
cam = bpy.data.objects.new("hudcam", bpy.data.cameras.new("hudcam")); sc.collection.objects.link(cam)
sc.camera = cam; cam.rotation_euler = (math.radians(90), 0, 0)
cam.data.sensor_fit = "VERTICAL"; cam.data.angle = math.radians(fov * 83); cam.data.clip_start = 0.01
if "--eevee" in a:
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.6, 0.68, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 1.2
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(-20), math.radians(30)); sun.data.energy = 3
else:
    sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
sc.render.resolution_x, sc.render.resolution_y = map(int, res.split("x"))
# textures for the item: the baked PNGs (the importer finds no textures folder)
TEX = {"dev_spectrum_x_probe": r"X:\coop\assets\spectrum-x\bake\pistol_blender\pistol_color.png",
       "dev_spectrum_x_tablet": r"X:\coop\assets\spectrum-x\bake\tablet_blender\tablet_color.png",
       "dev_spectrum_x_screen": r"X:\coop\assets\spectrum-x\hud\tex\screen.png",
       "dev_spectrum_x_cable": r"X:\coop\assets\spectrum-x\hud\tex\cable.png"}
for o in item:
    if o.type != "MESH": continue
    for m in o.data.materials:
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE":
                for k, p in TEX.items():
                    if k in (n.image.name if n.image else "") or k in n.name or k in m.name:
                        n.image = bpy.data.images.load(p)


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
        sc.render.filepath = os.path.join(out, "%s_%03d.png" % (mot, int(fr)))
        bpy.ops.render.render(write_still=True)
