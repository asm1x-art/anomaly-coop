"""Calibration: hands + binoculars_idle + binocular HUD model placed as the engine does, rendered from the HUD camera
for each candidate bone-frame correction K. blender -b -P calib_binoc.py -- <gamedata meshes dir> <out dir>"""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xr_space import offset_b, S
from mathutils import Matrix
a = sys.argv[sys.argv.index("--") + 1:]
G, out = a[0], a[1]; os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_homefile(use_empty=True)
def imp_ogf(p):
    before = set(bpy.data.objects)
    d, f = os.path.split(p); bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]
hands = next(o for o in imp_ogf(G + "/anomaly_weapons/hands/wpn_hand_01.ogf") if o.type == "ARMATURE")
bpy.context.view_layer.objects.active = hands
bpy.ops.xray_import.omf(directory=G + "/anomaly_weapons/hud_hands_animation", files=[{"name": "dev_hand_binocular_hud_animation.omf"}], import_motions=True, import_bone_parts=False)
hands.animation_data_create(); hands.animation_data.action = bpy.data.actions["binoculars_idle"]
bpy.context.scene.frame_set(0)
hands.matrix_world = offset_b((0, -0.155, 0.2), (0, 0, 0))
item = [o for o in imp_ogf(G + "/dynamics/devices/dev_binoculars/dev_binoculars_hud.ogf")]
iroot = next((o for o in item if o.parent is None))
print("ITEM", [(o.name, o.type) for o in item])
sc = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.rotation_euler = (math.radians(90), 0, 0); cam.data.sensor_fit = "VERTICAL"; cam.data.angle = math.radians(0.64 * 83)
cam.data.clip_start = 0.01
sc.render.engine = "BLENDER_WORKBENCH"; sc.render.resolution_x, sc.render.resolution_y = 960, 540
sc.display.shading.light = "STUDIO"
pb = hands.pose.bones["lead_gun"]
from io_scene_xray.formats.motions.const import MATRIX_BONE, MATRIX_BONE_INVERTED
item_off = offset_b((0, 0, 0), (180, 0, 0))
for name, K in (("I", Matrix.Identity(4)), ("MB", MATRIX_BONE.to_4x4()), ("MBI", MATRIX_BONE_INVERTED.to_4x4())):
    iroot.matrix_world = hands.matrix_world @ pb.matrix @ K @ item_off
    sc.render.filepath = os.path.join(out, "calib_%s.png" % name); bpy.ops.render.render(write_still=True)
