"""Inventory icon of Spectrum-X: the HUD model in its bind pose, rendered in Cycles on a transparent background.
blender -b spectrum_x_hud.blend -P render_icon.py -- <out.png> [--dir x y z] [--res 512]"""
import bpy, sys, math
import numpy as np
from mathutils import Vector
a = sys.argv[sys.argv.index("--") + 1:]; out = a[0]
d = Vector(tuple(map(float, a[a.index("--dir") + 1:a.index("--dir") + 4]))) if "--dir" in a else Vector((-1.0, -0.7, 0.55))
res = int(a[a.index("--res") + 1]) if "--res" in a else 512
sc = bpy.context.scene
for o in sc.objects:
    o.hide_render = o.name in ("hands", "hands_mesh") or o.type == "CAMERA"
IA = bpy.data.objects["spectrum_x_hud"]
if IA.animation_data: IA.animation_data.action = None
for pb in IA.pose.bones: pb.matrix_basis.identity()
IA.matrix_world.identity(); bpy.context.view_layer.update()
meshes = [o for o in sc.objects if o.type == "MESH" and not o.hide_render]
pts = np.array([o.matrix_world @ v.co for o in meshes for v in o.data.vertices])
c = Vector(((pts.min(0) + pts.max(0)) / 2).tolist())
d.normalize()
cam = bpy.data.objects.new("iconcam", bpy.data.cameras.new("iconcam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = "ORTHO"; cam.location = c + d * 2.0
cam.rotation_euler = (-d).to_track_quat("-Z", "Z").to_euler()
bpy.context.view_layer.update()
# fit the ortho scale to the projected extent
inv = cam.matrix_world.inverted()
pc = np.array([(inv @ Vector(p))[:2] for p in pts])
ext = (pc.max(0) - pc.min(0)).max()
cam.data.ortho_scale = ext * 1.06
mid = (pc.max(0) + pc.min(0)) / 2
cam.location = cam.matrix_world @ Vector((mid[0], mid[1], 0))
sc.render.engine = "CYCLES"; sc.cycles.samples = 64; sc.render.film_transparent = True
sc.render.resolution_x = sc.render.resolution_y = res
w = sc.world or bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.6, 0.62, 0.66, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
for nm, rot, e in (("key", (55, 0, -40), 4.0), ("rim", (60, 0, 150), 2.5)):
    l = bpy.data.objects.new(nm, bpy.data.lights.new(nm, "SUN")); sc.collection.objects.link(l)
    l.rotation_euler = tuple(math.radians(x) for x in rot); l.data.energy = e
for m in bpy.data.materials:      # baked normals + roughness for a nicer icon
    if m.name in ("probe", "tablet"):
        nt = m.node_tree; bs = nt.nodes["Principled BSDF"]
        base = r"X:\coop\assets\spectrum-x\bake\%s\%s" % (("pistol_blender", "pistol") if m.name == "probe" else ("tablet_v2", "tablet"))
        tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = bpy.data.images.load(base + "_normal.png"); tn.image.colorspace_settings.name = "Non-Color"
        nm_ = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(tn.outputs[0], nm_.inputs["Color"]); nt.links.new(nm_.outputs[0], bs.inputs["Normal"])
        rn = nt.nodes.new("ShaderNodeTexImage"); rn.image = bpy.data.images.load(base + "_rough.png"); rn.image.colorspace_settings.name = "Non-Color"
        mr = nt.nodes.new("ShaderNodeMath"); mr.operation = "MAXIMUM"; mr.inputs[1].default_value = 0.45
        nt.links.new(rn.outputs[0], mr.inputs[0]); nt.links.new(mr.outputs[0], bs.inputs["Roughness"])
    elif m.name == "screen":
        bs = m.node_tree.nodes["Principled BSDF"]; bs.inputs["Emission Strength"].default_value = 0.0
sc.render.filepath = out; bpy.ops.render.render(write_still=True)
