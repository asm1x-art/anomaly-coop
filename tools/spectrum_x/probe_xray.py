"""Headless Blender + blender-xray: list bones of an OGF and motions of OMFs applied to it.
blender -b -P probe_xray.py -- model.ogf [anim.omf ...]"""
import bpy, sys, os
a = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_homefile(use_empty=True)
d, f = os.path.split(a[0])
bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=True)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
print("ARM", arm.name, "bones", len(arm.data.bones), "objs", [o.name for o in bpy.context.scene.objects])
for b in arm.data.bones:
    print("  BONE", b.name, "parent", b.parent.name if b.parent else None, "head", tuple(round(c, 4) for c in b.head_local))
print("ACTIONS in ogf", [ac.name for ac in bpy.data.actions])
n0 = len(bpy.data.actions)
for omf in a[1:]:
    bpy.context.view_layer.objects.active = arm; arm.select_set(True)
    d, f = os.path.split(omf)
    bpy.ops.xray_import.omf(directory=d, files=[{"name": f}], import_motions=True, import_bone_parts=False, add_to_motion_list=True)
    acts = list(bpy.data.actions)[n0:]; n0 = len(bpy.data.actions)
    print("OMF", f)
    for ac in acts:
        print("   ", ac.name, tuple(ac.frame_range), "fps", getattr(ac.xray, "fps", None), "speed", getattr(ac.xray, "speed", None))
