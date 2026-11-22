"""Check of the pose composition: right arm from pm_idle (with the PM's HUD offsets), left arm from d2_idle (detector
offsets), both moved into one hands model at OURS offsets; PM and Veles placed as the engine places them.
blender -b -P compose_test.py -- <gamedata meshes> <out.png>"""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xr_space import offset_b
from mathutils import Matrix
from io_scene_xray.formats.motions.const import MATRIX_BONE_INVERTED as MATRIX_BONE
K = MATRIX_BONE.to_4x4()
a = sys.argv[sys.argv.index("--") + 1:]; G, out = a[0], a[1]
bpy.ops.wm.read_homefile(use_empty=True)
def imp_ogf(p):
    before = set(bpy.data.objects); d, f = os.path.split(p)
    bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
    return [o for o in bpy.data.objects if o not in before]
H = next(o for o in imp_ogf(G + "/anomaly_weapons/hands/wpn_hand_01.ogf") if o.type == "ARMATURE")
bpy.context.view_layer.objects.active = H
for f in ("wpn_hand_pm_hud_animation.omf", "dev_hand_detector_2_hud_animation.omf"):
    bpy.ops.xray_import.omf(directory=G + "/anomaly_weapons/hud_hands_animation", files=[{"name": f}], import_motions=True, import_bone_parts=False)
OFF_PM = offset_b((-0.031, -0.17, 0), (-0.5, 1, 1.15))
OFF_DET = offset_b((0.05, -0.1895, -0.1), (2, 2, 0))
OURS = OFF_PM
H.animation_data_create()
def sample(act, frame):
    H.animation_data.action = bpy.data.actions[act]; bpy.context.scene.frame_set(frame)
    return {pb.name: pb.matrix.copy() for pb in H.pose.bones}
pm = sample("pm_idle", 0); det = sample("d2_idle", 0)
CR = OURS.inverted() @ OFF_PM; CL = OURS.inverted() @ OFF_DET
target = {}
for b in H.pose.bones:
    n = b.name
    left = n.startswith("l_") or n.startswith("bip01_l_")
    target[n] = (CL @ det[n]) if left else (CR @ pm[n])
H.animation_data.action = None
for pb in H.pose.bones: pb.matrix_basis = Matrix.Identity(4)
def depth(b): return 0 if not b.parent else 1 + depth(b.parent)
for d in range(8):
    for pb in H.pose.bones:
        if depth(pb.bone) == d: pb.matrix = target[pb.name]
    bpy.context.view_layer.update()
H.matrix_world = OURS
pmo = imp_ogf(G + "/anomaly_weapons/wpn_pm/wpn_pm_hud.ogf"); pr = next(o for o in pmo if o.parent is None)
pr.matrix_world = OURS @ H.pose.bones["lead_gun"].matrix @ K @ offset_b((0.000746, -0.000321, 0.003479), (1.239378, -0.134046, -2.052052))
deto = imp_ogf(G + "/dynamics/devices/dev_detector_2/dev_detector_2_hud.ogf"); dr = next(o for o in deto if o.parent is None)
dr.matrix_world = OURS @ H.pose.bones["l_hand"].matrix @ K @ offset_b((-0.078949, 0.039172, -0.019197), (320.606964, -194.089020, -186.572464))
for nm, objs in (("PM", pmo), ("DET", deto)):
    for o in objs:
        if o.type == "MESH":
            import numpy as np
            co = np.array([v.co[:] for v in o.data.vertices]); print("BBOX", nm, o.name, co.min(0).round(4), co.max(0).round(4))
        if o.type == "ARMATURE": print("BONES", nm, [(b.name, tuple(round(x, 4) for x in b.head_local)) for b in o.data.bones][:12])
sc = bpy.context.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.rotation_euler = (math.radians(90), 0, 0); cam.data.sensor_fit = "VERTICAL"; cam.data.angle = math.radians(0.64 * 83); cam.data.clip_start = 0.01
sc.render.engine = "BLENDER_WORKBENCH"; sc.render.resolution_x, sc.render.resolution_y = 960, 540
sc.render.filepath = out; bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=out.replace(".png", ".blend"))
