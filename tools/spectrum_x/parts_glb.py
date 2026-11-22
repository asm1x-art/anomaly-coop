"""Headless Blender: weld a Tripo GLB (its mesh is split at UV seams) and list its connected parts with bounds.
blender -b --factory-startup -P parts_glb.py -- a.glb [--uvcmp b.glb]"""
import bpy, bmesh, sys
import numpy as np
argv = sys.argv[sys.argv.index("--") + 1:]
path = argv[0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=path)
o = [x for x in bpy.context.scene.objects if x.type == "MESH"][0]
if "--uvcmp" in argv:
    def uvs(ob):
        a = np.zeros(len(ob.data.loops) * 2, np.float32); ob.data.uv_layers[0].data.foreach_get("uv", a); return a
    a = uvs(o)
    bpy.ops.import_scene.gltf(filepath=argv[argv.index("--uvcmp") + 1])
    o2 = [x for x in bpy.context.scene.objects if x.type == "MESH" and x != o][0]
    b = uvs(o2)
    print("UVCMP same len", a.shape == b.shape, "maxdiff", float(np.abs(a - b).max()) if a.shape == b.shape else None)
    sys.exit(0)
bm = bmesh.new(); bm.from_mesh(o.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
bm.verts.ensure_lookup_table()
seen = set(); parts = []
for v in bm.verts:
    if v.index in seen: continue
    stack = [v]; seen.add(v.index); idx = []
    while stack:
        x = stack.pop(); idx.append(x.index)
        for e in x.link_edges:
            y = e.other_vert(x)
            if y.index not in seen: seen.add(y.index); stack.append(y)
    co = np.array([bm.verts[i].co[:] for i in idx])
    parts.append((len(idx), co.min(0).round(3).tolist(), co.max(0).round(3).tolist()))
parts.sort(key=lambda p: -p[0])
print("PARTS", len(parts), "verts", len(bm.verts))
for p in parts[:30]: print("  ", p)
