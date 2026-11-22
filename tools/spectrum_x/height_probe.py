"""Headless Blender: height map of a GLB seen along -Z (max z per pixel), for finding buttons / screen on the tablet.
blender -b --factory-startup -P height_probe.py -- model.glb out.npy x0 x1 y0 y1 px_per_unit [--rot-y deg]
out.npy: float32 [rows over x0..x1, cols over y0..y1], NaN where nothing is hit."""
import bpy, sys, numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
a = sys.argv[sys.argv.index("--") + 1:]
glb, out = a[0], a[1]; x0, x1, y0, y1, ppu = map(float, a[2:7])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
o = [x for x in bpy.context.scene.objects if x.type == "MESH"][0]
if "--rot-y" in a:
    import math
    from mathutils import Matrix
    o.data.transform(Matrix.Rotation(math.radians(float(a[a.index("--rot-y") + 1])), 4, "Y"))
dg = bpy.context.evaluated_depsgraph_get()
bvh = BVHTree.FromObject(o, dg)
nx, ny = int((x1 - x0) * ppu), int((y1 - y0) * ppu)
h = np.full((nx, ny), np.nan, np.float32)
d = Vector((0, 0, -1))
for i in range(nx):
    x = x0 + (i + 0.5) / ppu
    for j in range(ny):
        hit = bvh.ray_cast(Vector((x, y0 + (j + 0.5) / ppu, 1.0)), d, 2.0)
        if hit[0] is not None: h[i, j] = hit[0].z
np.save(out, h); print("HEIGHT", h.shape, np.nanmin(h), np.nanmax(h))
