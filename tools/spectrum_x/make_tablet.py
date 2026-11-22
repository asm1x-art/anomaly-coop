r"""Spectrum-X tablet, landscape rugged version, modelled by script (no Tripo), baked to 2K, in metres.
blender -b --factory-startup -P make_tablet.py -- <out_dir> [--res 2048]

The tablet's own coords (as the old Tripo tablet's, hud_rig.py): x down the screen, y to the screen's right, z out of
the glass; z = 0 is the back. Parts (each a closed slab with rounded corners and rounded edges, then one union):
  back plate (graphite), rubber frame with the screen window (wide side bezels: the hands hold them), glass,
  four raised corner bumpers (screwed), top bracket with a sensor lens, buttons (P1 / P2 on the left bezel under the
  left thumb, power / + / - on the right bezel), the cable socket on the bottom edge.
HIGH = the union + screws, lens, socket ring; its materials carry the colours, a fine stipple bump on the rubber and
the front / back prints (button glyphs, the yellow radiation sign, the maker's marks: drawn here with PIL). LOW = the
union alone (the game mesh), Smart UV with the front at twice the texel density. Bakes (Cycles): colour (with a mild
AO), tangent normal (OpenGL), roughness -> <out_dir>/tablet_color.png, tablet_normal.png, tablet_rough.png;
<out_dir>/tablet_bake.blend (object LOW, what hud_rig.py loads) and <out_dir>/tablet_layout.json (screen rectangle,
button tops, the socket, the bounds: what the rig and the animations aim at)."""
import bpy, bmesh, sys, os, math, json
import numpy as np
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]; os.makedirs(OUT, exist_ok=True)
RES = int(argv[argv.index("--res") + 1]) if "--res" in argv else 2048

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tablet_dims import *

bpy.ops.wm.read_homefile(use_empty=True)
scn = bpy.context.scene


def rrect(cx, cy, hx, hy, r, seg=SEG):
    """rounded rectangle centred (cx, cy), half sizes along x and y, CCW seen from +z; (x, y) points"""
    r = max(min(r, hx - 1e-5, hy - 1e-5), 1e-5)
    pts = []
    for k, (sx, sy, a0) in enumerate(((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270))):
        ccx, ccy = cx + sx * (hx - r), cy + sy * (hy - r)
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def bevel_levels(z0, z1, b0, b1, n=4):
    """(z, inset) from bottom to top: quarter-circle roundings of radius b0 at the bottom and b1 at the top"""
    lv = []
    for i in range(n + 1):
        t = math.radians(90 * i / n)
        lv.append((z0 + b0 * (1 - math.cos(t)), b0 * (1 - math.sin(t))) if b0 > 0 else (z0, 0))
        if b0 <= 0: break
    top = []
    for i in range(n + 1):
        t = math.radians(90 * i / n)
        top.append((z1 - b1 * (1 - math.cos(t)), b1 * (1 - math.sin(t))) if b1 > 0 else (z1, 0))
        if b1 <= 0: break
    return lv + top[::-1]


def slab(name, cx, cy, hx, hy, r, levels, mat, seg=SEG):
    """closed mesh: the rounded rectangle at each (z, inset) level, joined, capped"""
    bm = bmesh.new(); rings = []
    for z, ins in levels:
        rings.append([bm.verts.new((x, y, z)) for x, y in rrect(cx, cy, hx - ins, hy - ins, r - ins, seg)])
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
    bm.faces.new(rings[0][::-1]); bm.faces.new(rings[-1])
    return finish(name, bm, mat)


def cylinder_x(name, x0, x1, y, z, r, mat, seg=16, bev=0.0008):
    """a cylinder along +x from x0 to x1 (the socket), its outer end rounded"""
    bm = bmesh.new(); rings = []
    for x, rr in ((x0, r), (x1 - bev, r), (x1, r - bev)):
        rings.append([bm.verts.new((x, y + rr * math.cos(2 * math.pi * k / seg), z + rr * math.sin(2 * math.pi * k / seg))) for k in range(seg)])
    for a, b in zip(rings, rings[1:]):
        for i in range(seg):
            bm.faces.new((a[i], a[(i + 1) % seg], b[(i + 1) % seg], b[i]))
    bm.faces.new(rings[0][::-1]); bm.faces.new(rings[-1])
    return finish(name, bm, mat)


def finish(name, bm, mat):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); scn.collection.objects.link(o)
    if mat: me.materials.append(mat)
    return o


# ---------------------------------------------------------------- materials (HIGH): colours, roughness, bump, prints
def srgb(c): return tuple(((x / 255) ** 2.2) for x in c) + (1.0,)


MATS = {}


def material(name, color, rough, bump_scale=0.0, bump_str=0.0, metallic=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    bs = nt.nodes["Principled BSDF"]
    bs.inputs["Roughness"].default_value = rough; bs.inputs["Metallic"].default_value = metallic
    col = nt.nodes.new("ShaderNodeRGB"); col.outputs[0].default_value = srgb(color)
    m["base"] = col.name
    if bump_scale:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = bump_scale
        nz.inputs["Detail"].default_value = 2.0
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
        bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = bump_str
        bp.inputs["Distance"].default_value = 0.0002
        nt.links.new(nz.outputs["Fac"], bp.inputs["Height"]); nt.links.new(bp.outputs[0], bs.inputs["Normal"])
    MATS[name] = m
    return m


GRAPHITE = material("graphite", (60, 63, 68), 0.55, 1500, 0.10)
RUBBER = material("rubber", (38, 38, 40), 0.85, 2600, 0.22)
BUTTON = material("button", (30, 30, 31), 0.80, 3000, 0.10)
GLASS = material("glass", (8, 9, 11), 0.12)
METAL = material("metal", (118, 120, 124), 0.35, metallic=1.0)
LENS = material("lens", (6, 7, 9), 0.08)

# ---------------------------------------------------------------- parts
parts = []
parts.append(slab("back", 0, 0, HH - 0.003, HW - 0.003, 0.010, bevel_levels(0.0, FRONT / 2, 0.0025, 0.0), GRAPHITE))
frame = slab("frame", 0, 0, HH, HW, 0.012, bevel_levels(0.003, FRONT, 0.002, 0.003), RUBBER)
wx0, wx1, wy0, wy1 = WIN
wcx, wcy, whx, why = (wx0 + wx1) / 2, (wy0 + wy1) / 2, (wx1 - wx0) / 2, (wy1 - wy0) / 2
cutter = slab("cutter", wcx, wcy, whx, why, WIN_R,
              [(-0.01, 0), (FRONT - 0.0016, 0), (FRONT + 0.0006, -0.0022), (FRONT + 0.01, -0.0022)], None)
parts.append(frame)
parts.append(slab("glass", wcx, wcy, whx + 0.0015, why + 0.0015, WIN_R + 0.0015, [(0.006, 0), (GLASS_Z, 0)], GLASS))
BUMP = []
for sx in (-1, 1):
    for sy in (-1, 1):
        bx, by = sx * (HH + 0.0025 - BUMPER), sy * (HW + 0.0025 - BUMPER)
        BUMP.append((bx, by))
        parts.append(slab("bumper", bx, by, BUMPER, BUMPER, 0.010, bevel_levels(-0.0015, FRONT + 0.0018, 0.0025, 0.0025), RUBBER))
parts.append(slab("bracket", -HH - 0.0005, 0.0, 0.0075, 0.030, 0.0045, bevel_levels(0.006, GLASS_Z, 0.0015, 0.0015), GRAPHITE))
for side, names in ((-1, ("p1", "p2")), (1, ("plus", "minus"))):
    for nm, bx in zip(names, BTN_X):
        parts.append(slab("btn_" + nm, bx, side * BTN_Y, BTN_HX, BTN_HY, 0.0022, bevel_levels(FRONT - 0.002, BTN_TOP, 0, 0.0008, 2), BUTTON, seg=6))
parts.append(slab("btn_power", PWR_X, BTN_Y, 0.0052, 0.0052, 0.0052, bevel_levels(FRONT - 0.002, BTN_TOP, 0, 0.0008, 2), BUTTON, seg=6))
parts.append(cylinder_x("socket", HH - 0.004, HH + SOCK_LEN, SOCK[1], SOCK[2], SOCK_R, RUBBER))


def apply_bool(target, other, op):
    md = target.modifiers.new("b", "BOOLEAN"); md.operation = op; md.solver = "EXACT"; md.object = other
    md.material_mode = "TRANSFER"
    bpy.context.view_layer.objects.active = target
    for o in scn.objects: o.select_set(o == target)
    bpy.ops.object.modifier_apply(modifier="b")


apply_bool(frame, cutter, "DIFFERENCE"); bpy.data.objects.remove(cutter)
body = parts[0]
for p in parts[1:]:
    apply_bool(body, p, "UNION"); bpy.data.objects.remove(p)
body.name = "HIGH"
bm = bmesh.new(); bm.from_mesh(body.data)
bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
bmesh.ops.triangulate(bm, faces=bm.faces[:])
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
bm.to_mesh(body.data); bm.free()
# smooth shading with the hard edges (> 40 degrees) sharp: the exporter takes the split (corner) normals, so the big
# flat faces shade flat and only the roundings blend (all-smooth gives dark streaks across the bezels)
bm = bmesh.new(); bm.from_mesh(body.data)
for e in bm.edges:
    e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(40))
for f in bm.faces: f.smooth = True
bm.to_mesh(body.data); bm.free()
low = body.copy(); low.data = body.data.copy(); low.name = "LOW"; scn.collection.objects.link(low)
print("LOW tris", len(low.data.polygons), "verts", len(low.data.vertices))

# HIGH details: screws on the bumpers (front) and the back plate, the lens in the bracket, the metal ring of the socket
def screw(x, y, z, nz, r=0.0019):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=r, radius2=r * 0.8, depth=0.0012)
    # a slot across the head: the top verts near its middle line pushed down
    for v in bm.verts:
        if v.co.z > 0 and abs(v.co.x) < r * 0.18: v.co.z -= 0.0004
    o = finish("screw", bm, METAL)
    o.matrix_world = Matrix.Translation((x, y, z)) @ (Matrix.Rotation(math.pi, 4, "X") if nz < 0 else Matrix.Identity(4))
    return o


det = []
for (bx, by) in BUMP:      # one screw per bumper, a little toward the tablet's inside
    det.append(screw(bx - math.copysign(0.0015, bx), by - math.copysign(0.0015, by), FRONT + 0.0018 + 0.0002, 1))
for sx in (-1, 1):
    for sy in (-1, 1):
        det.append(screw(sx * 0.040, sy * 0.066, -0.0002, -1, 0.0016))
bmL = bmesh.new(); bmesh.ops.create_cone(bmL, cap_ends=True, segments=20, radius1=0.0032, radius2=0.0032, depth=0.003)
lens = finish("lens", bmL, LENS); lens.matrix_world = Matrix.Translation((-HH - 0.0005, 0.016, GLASS_Z))
det.append(lens)
bmR = bmesh.new(); bmesh.ops.create_cone(bmR, cap_ends=True, segments=20, radius1=SOCK_R * 0.62, radius2=SOCK_R * 0.62, depth=0.002)
ring = finish("sockring", bmR, METAL)
ring.matrix_world = Matrix.Translation((HH + SOCK_LEN, SOCK[1], SOCK[2])) @ Matrix.Rotation(math.pi / 2, 4, "Y")
det.append(ring)
for o in det:
    o.select_set(True)
for o in scn.objects: o.select_set(o in det or o == body)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()


# ---------------------------------------------------------------- prints: drawn by tablet_prints.py (PIL, outside Blender)
import subprocess
subprocess.run(["python", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tablet_prints.py"), OUT], check=True)
FRONT_PNG = os.path.join(OUT, "print_front.png"); BACK_PNG = os.path.join(OUT, "print_back.png")


def add_print(m, png, facing, mirror):
    nt = m.node_tree; bs = nt.nodes["Principled BSDF"]
    base = nt.nodes[m["base"]].outputs[0]
    src = bs.inputs["Base Color"].links[0].from_socket if bs.inputs["Base Color"].is_linked else base
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    def lin(sock, k, c):
        mm = nt.nodes.new("ShaderNodeMath"); mm.operation = "MULTIPLY_ADD"
        nt.links.new(sock, mm.inputs[0]); mm.inputs[1].default_value = k; mm.inputs[2].default_value = c
        return mm.outputs[0]
    sy = -1.0 if mirror else 1.0
    u = lin(sep.outputs["Y"], sy / (BOX[3] - BOX[2]), (-BOX[2] if not mirror else BOX[3]) / (BOX[3] - BOX[2]))
    v = lin(sep.outputs["X"], -1 / (BOX[1] - BOX[0]), BOX[1] / (BOX[1] - BOX[0]))
    cmb = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(u, cmb.inputs[0]); nt.links.new(v, cmb.inputs[1])
    im = nt.nodes.new("ShaderNodeTexImage"); im.image = bpy.data.images.load(png); im.extension = "CLIP"; im.interpolation = "Cubic"
    nt.links.new(cmb.outputs[0], im.inputs[0])
    geo = nt.nodes.new("ShaderNodeNewGeometry"); vt = nt.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type = "NORMAL"; vt.convert_from = "WORLD"; vt.convert_to = "OBJECT"
    nt.links.new(geo.outputs["Normal"], vt.inputs[0])
    sn = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(vt.outputs[0], sn.inputs[0])
    g = nt.nodes.new("ShaderNodeMapRange"); g.inputs[1].default_value = 0.6 * facing; g.inputs[2].default_value = 0.8 * facing
    nt.links.new(sn.outputs["Z"], g.inputs[0])
    f = nt.nodes.new("ShaderNodeMath"); f.operation = "MULTIPLY"
    nt.links.new(g.outputs[0], f.inputs[0]); nt.links.new(im.outputs["Alpha"], f.inputs[1])
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"
    nt.links.new(f.outputs[0], mx.inputs["Factor"]); nt.links.new(src, mx.inputs[6]); nt.links.new(im.outputs["Color"], mx.inputs[7])
    nt.links.new(mx.outputs[2], bs.inputs["Base Color"])


for m in MATS.values():
    nt = m.node_tree; nt.links.new(nt.nodes[m["base"]].outputs[0], nt.nodes["Principled BSDF"].inputs["Base Color"])
for m in (RUBBER, BUTTON, GRAPHITE):
    add_print(m, FRONT_PNG, 1, False)
add_print(GRAPHITE, BACK_PNG, -1, True)

# ---------------------------------------------------------------- LOW: UVs (front faces at twice the density)
for o in scn.objects: o.select_set(o == low)
bpy.context.view_layer.objects.active = low
low.data.materials.clear()
for uv in list(low.data.uv_layers): low.data.uv_layers.remove(uv)
low.data.uv_layers.new(name="UVMap")
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.003, area_weight=0.0, scale_to_bounds=False)
bpy.ops.object.mode_set(mode="OBJECT")
bm = bmesh.new(); bm.from_mesh(low.data); uvl = bm.loops.layers.uv[0]
bm.faces.ensure_lookup_table()
# islands = connected faces sharing UVs; front islands (mostly +z) scaled x2
parent = list(range(len(bm.faces)))
def fnd(i):
    while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
    return i
for e in bm.edges:
    lf = e.link_faces
    if len(lf) != 2: continue
    f, g = lf
    ok = True
    for v in e.verts:
        a = next(l[uvl].uv for l in f.loops if l.vert == v); b = next(l[uvl].uv for l in g.loops if l.vert == v)
        if (a - b).length > 1e-6: ok = False
    if ok: parent[fnd(f.index)] = fnd(g.index)
isl = {}
for f in bm.faces: isl.setdefault(fnd(f.index), []).append(f)
nf = 0
for fs in isl.values():
    nz = sum(f.normal.z * f.calc_area() for f in fs) / max(sum(f.calc_area() for f in fs), 1e-12)
    if nz > 0.7:
        loops = [l for f in fs for l in f.loops]
        c = sum((l[uvl].uv for l in loops), Vector((0, 0))) / len(loops)
        for l in loops: l[uvl].uv = c + (l[uvl].uv - c) * 2.0
        nf += 1
bm.to_mesh(low.data); bm.free()
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.context.scene.tool_settings.use_uv_select_sync = True
bpy.ops.uv.select_all(action="SELECT")
bpy.ops.uv.pack_islands(rotate=True, margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")
print("UV islands", len(isl), "front x2:", nf)

# ---------------------------------------------------------------- bake HIGH -> LOW
scn.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for t in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = t; prefs.get_devices()
            if any(dv.type == t for dv in prefs.devices):
                for dv in prefs.devices: dv.use = dv.type == t
                scn.cycles.device = "GPU"; print("bake device", t); break
        except TypeError:
            pass
except Exception as e:
    print("gpu setup failed", e)
w = bpy.data.worlds.new("w"); scn.world = w
ml = bpy.data.materials.new("tablet_low"); ml.use_nodes = True; low.data.materials.append(ml)
imgs = {}
for k, cs in (("color", "sRGB"), ("ao", "Non-Color"), ("normal", "Non-Color"), ("rough", "Non-Color")):
    im = bpy.data.images.new("tablet_" + k, RES, RES, alpha=False); im.colorspace_settings.name = cs; imgs[k] = im
nodes = {}
for k, im in imgs.items():
    n = ml.node_tree.nodes.new("ShaderNodeTexImage"); n.image = im; nodes[k] = n
for o in scn.objects: o.select_set(o in (body, low))
bpy.context.view_layer.objects.active = low
bk = scn.render.bake
bk.use_selected_to_active = True; bk.cage_extrusion = 0.003; bk.max_ray_distance = 0.006; bk.margin = 8
for k, typ, smp in (("color", "DIFFUSE", 4), ("ao", "AO", 64), ("normal", "NORMAL", 4), ("rough", "ROUGHNESS", 4)):
    ml.node_tree.nodes.active = nodes[k]; scn.cycles.samples = smp
    kw = {}
    if typ == "DIFFUSE":
        bk.use_pass_direct = False; bk.use_pass_indirect = False; bk.use_pass_color = True
        kw = dict(pass_filter={"COLOR"})
    bpy.ops.object.bake(type=typ, normal_space="TANGENT", **kw)
    p = os.path.join(OUT, "tablet_%s.png" % k)
    imgs[k].filepath_raw = p; imgs[k].file_format = "PNG"; imgs[k].save(); print("baked", p)
# colour x mild AO
c = np.array(imgs["color"].pixels[:], np.float32).reshape(RES, RES, 4)
ao = np.array(imgs["ao"].pixels[:], np.float32).reshape(RES, RES, 4)[..., :1]
c[..., :3] *= 0.6 + 0.4 * ao
imgs["color"].pixels[:] = c.ravel(); imgs["color"].save()
nt2 = ml.node_tree; b2 = nt2.nodes["Principled BSDF"]
nt2.links.new(nodes["color"].outputs[0], b2.inputs["Base Color"])
nt2.links.new(nodes["rough"].outputs[0], b2.inputs["Roughness"])
nm = nt2.nodes.new("ShaderNodeNormalMap"); nt2.links.new(nodes["normal"].outputs[0], nm.inputs["Color"])
nt2.links.new(nm.outputs[0], b2.inputs["Normal"])

lay = {"screen": [WIN[0] + 0.001, WIN[1] - 0.001, WIN[2] + 0.001, WIN[3] - 0.001, GLASS_Z + 0.0008],
       "buttons": BUTTONS, "thumb_rest": THUMB_REST, "socket": [HH + SOCK_LEN, SOCK[1], SOCK[2]], "socket_dir": [1, 0, 0],
       "bounds": [list(map(float, np.min([v.co[:] for v in low.data.vertices], 0))),
                  list(map(float, np.max([v.co[:] for v in low.data.vertices], 0)))],
       "front": FRONT, "glass": GLASS_Z, "window": WIN, "bezel": [BEZ_L, BEZ_R, BEZ_T, BEZ_B], "half": [HH, HW],
       "tris": len(low.data.polygons)}
json.dump(lay, open(os.path.join(OUT, "tablet_layout.json"), "w"), indent=1)
print("LAYOUT", json.dumps(lay))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "tablet_bake.blend"), compress=True)
