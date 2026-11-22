"""Headless Blender: print objects, triangle counts, bounds, loose parts and UV layers of GLB files.
blender -b --factory-startup -P inspect_glb.py -- a.glb [b.glb ...]"""
import bpy, bmesh, sys
from mathutils import Vector
for path in sys.argv[sys.argv.index("--") + 1:]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    print("==", path)
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            print("  ", o.type, o.name); continue
        me = o.data
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
        hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
        bm = bmesh.new(); bm.from_mesh(me)
        bm.verts.ensure_lookup_table()
        # loose parts
        seen = set(); parts = []
        for v in bm.verts:
            if v.index in seen: continue
            stack = [v]; seen.add(v.index); cnt = 0; pmin = v.co.copy(); pmax = v.co.copy()
            while stack:
                x = stack.pop(); cnt += 1
                pmin = Vector(map(min, pmin, x.co)); pmax = Vector(map(max, pmax, x.co))
                for e in x.link_edges:
                    y = e.other_vert(x)
                    if y.index not in seen: seen.add(y.index); stack.append(y)
            parts.append((cnt, tuple(round(c, 3) for c in pmin), tuple(round(c, 3) for c in pmax)))
        parts.sort(reverse=True)
        print("  MESH", o.name, "verts", len(me.vertices), "polys", len(me.polygons), "uv", [u.name for u in me.uv_layers],
              "mats", [m.name for m in me.materials], "bounds", tuple(round(c, 3) for c in lo), tuple(round(c, 3) for c in hi))
        print("   loose parts", len(parts), parts[:12])
        bm.free()
