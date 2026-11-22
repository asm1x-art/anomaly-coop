"""Headless Blender: Tripo high-poly GLB -> low-poly by Decimate (collapse), cut boxes removed, Smart UV.
blender -b --factory-startup -P retopo_blender.py -- high.glb out.blend --tris 12000
        [--cut "x0 y0 z0 x1 y1 z1"]... [--front-uv +z 2.0]
Writes out.blend with objects HIGH (welded, cut) and LOW (decimated, triangulated, UV 'UVMap').
--cut: axis-aligned boxes (Blender coords of the imported GLB) whose vertices are deleted (Tripo's cut cable stubs);
       the holes left are filled.
--rot-y <deg>: rotate the model about Y first (the tablet comes tilted from Tripo: its screen faces +Z then).
--front-uv <axis> <k>: islands whose faces look along <axis> get k times the texel density (buttons, labels)."""
import bpy, bmesh, sys, time
from mathutils import Vector
argv = sys.argv[sys.argv.index("--") + 1:]
high, out = argv[0], argv[1]
tris = int(argv[argv.index("--tris") + 1]) if "--tris" in argv else 12000
cuts = [list(map(float, argv[i + 1].split())) for i, a in enumerate(argv) if a == "--cut"]
front = None
if "--front-uv" in argv:
    i = argv.index("--front-uv"); front = (argv[i + 1], float(argv[i + 2]))
AX = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=high)
hi = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
hi.name = "HIGH"
if "--rot-y" in argv:
    import math
    from mathutils import Matrix
    hi.data.transform(Matrix.Rotation(math.radians(float(argv[argv.index("--rot-y") + 1])), 4, "Y"))
bm = bmesh.new(); bm.from_mesh(hi.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
if cuts:
    dead = [v for v in bm.verts if any(c[0] <= v.co.x <= c[3] and c[1] <= v.co.y <= c[4] and c[2] <= v.co.z <= c[5] for c in cuts)]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    # fill the open ends left by the cut (only small holes: the cut cross-sections)
    edges = [e for e in bm.edges if e.is_boundary]
    bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    # drop leftover crumbs: connected pieces under 300 verts
    bm.verts.ensure_lookup_table(); seen = set(); crumbs = []
    for v in bm.verts:
        if v in seen: continue
        st = [v]; seen.add(v); grp = []
        while st:
            x = st.pop(); grp.append(x)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y not in seen: seen.add(y); st.append(y)
        if len(grp) < 300: crumbs += grp
    bmesh.ops.delete(bm, geom=crumbs, context="VERTS")
    print("cut: removed %d verts, %d crumbs" % (len(dead), len(crumbs)))
bm.to_mesh(hi.data); bm.free()
hi.data.update()
n_hi = sum(len(p.vertices) - 2 for p in hi.data.polygons)
lo = hi.copy(); lo.data = hi.data.copy(); lo.name = "LOW"; bpy.context.scene.collection.objects.link(lo)
for m in list(lo.data.materials): pass
lo.data.materials.clear()
mod = lo.modifiers.new("dec", "DECIMATE"); mod.decimate_type = "COLLAPSE"
mod.ratio = tris / n_hi; mod.use_collapse_triangulate = True
bpy.context.view_layer.objects.active = lo
for o in bpy.context.scene.objects: o.select_set(o == lo)
bpy.ops.object.modifier_apply(modifier="dec")
bm = bmesh.new(); bm.from_mesh(lo.data)
bmesh.ops.triangulate(bm, faces=bm.faces)
bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
bm.to_mesh(lo.data); bm.free()
for uv in list(lo.data.uv_layers): lo.data.uv_layers.remove(uv)
lo.data.uv_layers.new(name="UVMap")
for p in lo.data.polygons: p.use_smooth = True
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.004, area_weight=0.0, scale_to_bounds=False)
if front:
    ax = Vector(AX[front[0]])
    bpy.ops.object.mode_set(mode="OBJECT")
    bm = bmesh.new(); bm.from_mesh(lo.data); uvl = bm.loops.layers.uv[0]
    bm.faces.ensure_lookup_table()
    # islands of faces looking along ax: scale their UVs around their centre
    sel = [f for f in bm.faces if f.normal.dot(ax) > 0.8]
    # UV islands: faces joined across an edge whose two loops carry the same UVs on both sides
    def same_uv(f, g, e):
        lf = {l.vert: l[uvl].uv for l in f.loops if l.vert in e.verts}
        lg = {l.vert: l[uvl].uv for l in g.loops if l.vert in e.verts}
        return all((lf[v] - lg[v]).length < 1e-6 for v in e.verts)
    selset = {f.index for f in sel}; done = set()
    for f in sel:
        if f.index in done: continue
        isl = set(); st = [f]
        while st:
            g = st.pop()
            if g.index in isl: continue
            isl.add(g.index)
            for e in g.edges:
                for k in e.link_faces:
                    if k.index not in isl and same_uv(g, k, e): st.append(k)
        done |= isl
        if len(isl & selset) * 2 < len(isl): continue
        loops = [l for i in isl for l in bm.faces[i].loops]
        c = sum((l[uvl].uv for l in loops), Vector((0, 0))) / len(loops)
        for l in loops: l[uvl].uv = c + (l[uvl].uv - c) * front[1]
    bm.to_mesh(lo.data); bm.free()
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.context.scene.tool_settings.use_uv_select_sync = True   # pack every island (bmesh edits drop the UV selection)
bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
bpy.ops.object.mode_set(mode="OBJECT")
n_lo = len(lo.data.polygons)
print("RETOPO high %d tris -> low %d tris, %.0fs" % (n_hi, n_lo, time.time() - t0))
bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
