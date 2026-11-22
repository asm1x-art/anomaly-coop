r"""Look at the baked tablet alone (LOW with its bakes: colour, normal map, roughness), Cycles, a few views.
blender -b <tablet_bake.blend> -P render_tablet.py -- <out.png> [--res 1600x1000]
Views: front, three-quarter front, back, close-up of the left bezel (P1 / P2) and of the bottom edge (socket);
written as one sheet."""
import bpy, sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hud_view
from mathutils import Vector
a = sys.argv[sys.argv.index("--") + 1:]
out = a[0]; res = a[a.index("--res") + 1] if "--res" in a else "800x500"
w, h = map(int, res.split("x"))
sc = bpy.context.scene
for o in list(sc.objects):
    if o.name != "LOW": bpy.data.objects.remove(o)
low = sc.objects["LOW"]
# the screen plane (dark glass) as build_hud.py makes it
import json
lay = json.load(open(os.path.join(os.path.dirname(bpy.data.filepath), "tablet_layout.json")))
x0, x1, y0, y1, z = lay["screen"]
m = bpy.data.meshes.new("scr"); m.from_pydata([(x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z)], [], [(0, 1, 2, 3)])
uv = m.uv_layers.new()
for l, c in zip(m.loops, ((0, 0), (1, 0), (1, 1), (0, 1))): uv.data[l.index].uv = c
scr = bpy.data.objects.new("scr", m); sc.collection.objects.link(scr)
ms = bpy.data.materials.new("scr"); ms.use_nodes = True
tn = ms.node_tree.nodes.new("ShaderNodeTexImage"); tn.image = bpy.data.images.load(r"X:\coop\assets\spectrum-x\hud\tex\screen.png")
bs = ms.node_tree.nodes["Principled BSDF"]; ms.node_tree.links.new(tn.outputs[0], bs.inputs["Base Color"]); bs.inputs["Roughness"].default_value = 0.1
m.materials.append(ms)
sc.view_settings.view_transform = "Standard"
sc.render.engine = "CYCLES"; sc.cycles.samples = 48; sc.cycles.use_denoising = True
try:
    p = bpy.context.preferences.addons["cycles"].preferences; p.compute_device_type = "OPTIX"; p.get_devices()
    for d in p.devices: d.use = d.type == "OPTIX"
    sc.cycles.device = "GPU"
except Exception as e: print(e)
wd = bpy.data.worlds.new("w"); sc.world = wd; wd.use_nodes = True
wd.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.27, 0.3, 1); wd.node_tree.nodes["Background"].inputs[1].default_value = 0.6
for nm, loc, en in (("key", (0.25, -0.35, 0.45), 6), ("rim", (-0.3, 0.3, 0.2), 2.5)):
    L = bpy.data.objects.new(nm, bpy.data.lights.new(nm, "AREA")); L.data.energy = en; L.data.size = 0.3
    L.location = loc; L.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler(); sc.collection.objects.link(L)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
sc.render.resolution_x, sc.render.resolution_y = w, h
c = Vector((0, 0, 0.013))
# tablet coords: x down, y right, z out: "up" on screen = -x
views = [("front", (0, 0, 0.45), c, 30), ("three_q", (0.12, 0.2, 0.33), c, 32), ("back", (0.05, -0.08, -0.4), c, 32),
         ("left_bezel", (0.03, -0.15, 0.12), Vector((-0.012, -0.078, 0.023)), 24), ("bottom", (0.17, 0.05, 0.1), Vector((0.06, 0.01, 0.013)), 22)]
paths = []
for nm, eye, tgt, fov in views:
    hud_view.look_at(cam, eye, tgt, up=(-1, 0, 0), fov_deg=fov)
    pth = os.path.join(os.path.dirname(out), "tab_%s.png" % nm); paths.append(pth)
    sc.render.filepath = pth; bpy.ops.render.render(write_still=True)
hud_view.sheet(paths + [paths[0]], out, cols=3)
