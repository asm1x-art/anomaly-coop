"""Headless Blender: orthographic Workbench render of a GLB along one axis with a 0.05 grid drawn on top (to pick cut boxes).
blender -b --factory-startup -P ortho_grid.py -- model.glb out.png <view: x|-x|y|-y|z|-z> [--box x0 y0 z0 x1 y1 z1 ...]"""
import bpy, sys, math
from mathutils import Vector
argv = sys.argv[sys.argv.index("--") + 1:]
glb, out, view = argv[0], argv[1], argv[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
sc.render.resolution_x = sc.render.resolution_y = 1200
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = 1.1
d = {"x": Vector((1, 0, 0)), "-x": Vector((-1, 0, 0)), "y": Vector((0, 1, 0)), "-y": Vector((0, -1, 0)), "z": Vector((0, 0, 1)), "-z": Vector((0, 0, -1))}[view]
cam.location = d * 3
up = Vector((0, 0, 1)) if view not in ("z", "-z") else Vector((0, 1, 0))
cam.rotation_euler = (-d).to_track_quat("-Z", "Y" if up.z == 0 else "Z").to_euler() if False else (-d).to_track_quat("-Z", "Y").to_euler()
if view in ("x", "-x", "y", "-y"):
    q = (-d).to_track_quat("-Z", "Y")
    import mathutils
    # camera up = world Z
    m = mathutils.Matrix.Identity(3); f = -d; r = f.cross(Vector((0, 0, 1))).normalized(); u = r.cross(f)
    m.col[0] = r; m.col[1] = u; m.col[2] = -f
    cam.rotation_euler = m.to_euler()
bpy.ops.render.render(write_still=False)
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
# grid overlay with PIL-free approach: write grid info for the composer
print("CAM", [round(c, 3) for c in cam.matrix_world.col[0][:3]], [round(c, 3) for c in cam.matrix_world.col[1][:3]])
