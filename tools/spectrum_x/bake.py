"""Headless Blender (Cycles): bake HIGH -> LOW of a .blend made by retopo_blender.py.
blender -b <file.blend> -P bake.py -- <out_dir> <name> [--res 2048] [--extrusion 0.008] [--ray 0.03]
        [--color-png comp.png] [--decal decal.png --decal-box "u_axis v_axis umin vmin umax vmax" --decal-normal +z]
        [--glb out.glb]
Writes <name>_color.png (sRGB), <name>_normal.png (tangent, OpenGL), <name>_rough.png into out_dir.
--color-png: a colour texture that replaces HIGH's base colour (same UVs as the GLB), e.g. a composite of two variants.
--decal: RGBA image laid over HIGH's base colour by a planar projection on faces looking along --decal-normal;
         the box maps object coords (u_axis, v_axis in x/y/z, may be negated with -) to the image (0..1)."""
import bpy, sys, os
argv = sys.argv[sys.argv.index("--") + 1:]
out_dir, name = argv[0], argv[1]
opt = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d
res = int(opt("--res", 2048)); extr = float(opt("--extrusion", 0.008)); ray = float(opt("--ray", 0.03))
os.makedirs(out_dir, exist_ok=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
try:
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for t in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = t; prefs.get_devices()
            if any(d.type == t for d in prefs.devices):
                for d in prefs.devices: d.use = d.type == t
                sc.cycles.device = "GPU"; print("bake device", t); break
        except TypeError:
            pass
except Exception as e:
    print("gpu setup failed", e)
sc.cycles.samples = 8
hi = bpy.data.objects["HIGH"]; lo = bpy.data.objects["LOW"]
mat_hi = hi.data.materials[0]
nt = mat_hi.node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
if opt("--color-png"):
    img = bpy.data.images.load(opt("--color-png"))
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = img
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = hi.data.uv_layers[0].name
    nt.links.new(uvn.outputs[0], tn.inputs[0])
    nt.links.new(tn.outputs[0], bsdf.inputs["Base Color"])
if opt("--decal"):
    ua, va, u0, v0, u1, v1 = opt("--decal-box").split()
    u0, v0, u1, v1 = map(float, (u0, v0, u1, v1))
    dimg = bpy.data.images.load(opt("--decal"))
    tc = nt.nodes.new("ShaderNodeTexCoord"); sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    def axis(a, lo_, hi_):
        s = -1.0 if a.startswith("-") else 1.0; c = a.strip("+-")
        m = nt.nodes.new("ShaderNodeMath"); m.operation = "MULTIPLY_ADD"
        # (s*coord - lo)/(hi-lo) = coord*(s/(hi-lo)) + (-lo/(hi-lo))
        nt.links.new(sep.outputs[c.upper()], m.inputs[0]); m.inputs[1].default_value = s / (hi_ - lo_); m.inputs[2].default_value = -lo_ / (hi_ - lo_)
        return m
    mu, mv = axis(ua, u0, u1), axis(va, v0, v1)
    comb = nt.nodes.new("ShaderNodeCombineXYZ"); nt.links.new(mu.outputs[0], comb.inputs[0]); nt.links.new(mv.outputs[0], comb.inputs[1])
    dt = nt.nodes.new("ShaderNodeTexImage"); dt.image = dimg; dt.extension = "CLIP"; dt.interpolation = "Cubic"
    nt.links.new(comb.outputs[0], dt.inputs[0])
    # only faces looking along the decal normal
    dn = opt("--decal-normal", "+z"); s = -1.0 if dn.startswith("-") else 1.0
    geo = nt.nodes.new("ShaderNodeNewGeometry"); vt = nt.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type = "NORMAL"; vt.convert_from = "WORLD"; vt.convert_to = "OBJECT"
    nt.links.new(geo.outputs["Normal"], vt.inputs[0])
    sn = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(vt.outputs[0], sn.inputs[0])
    facing = nt.nodes.new("ShaderNodeMath"); facing.operation = "MULTIPLY"; facing.inputs[1].default_value = s
    nt.links.new(sn.outputs[dn.strip("+-").upper()], facing.inputs[0])
    gate = nt.nodes.new("ShaderNodeMapRange"); gate.inputs[1].default_value = 0.5; gate.inputs[2].default_value = 0.7
    nt.links.new(facing.outputs[0], gate.inputs[0])
    fac = nt.nodes.new("ShaderNodeMath"); fac.operation = "MULTIPLY"
    nt.links.new(gate.outputs[0], fac.inputs[0]); nt.links.new(dt.outputs["Alpha"], fac.inputs[1])
    base_src = bsdf.inputs["Base Color"].links[0].from_socket
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    nt.links.new(fac.outputs[0], mix.inputs["Factor"]); nt.links.new(base_src, mix.inputs[6]); nt.links.new(dt.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    # decal parts are matte rubber / paint: roughness up where the decal is
    if bsdf.inputs["Roughness"].is_linked:
        rs = bsdf.inputs["Roughness"].links[0].from_socket
        rm = nt.nodes.new("ShaderNodeMix"); rm.data_type = "FLOAT"
        nt.links.new(fac.outputs[0], rm.inputs["Factor"]); nt.links.new(rs, rm.inputs[2]); rm.inputs[3].default_value = 0.8
        nt.links.new(rm.outputs[0], bsdf.inputs["Roughness"])
# low material with the bake targets
ml = bpy.data.materials.new(name + "_low"); ml.use_nodes = True
lo.data.materials.clear(); lo.data.materials.append(ml)
imgs = {}
for k, cs in (("color", "sRGB"), ("normal", "Non-Color"), ("rough", "Non-Color")):
    im = bpy.data.images.new("%s_%s" % (name, k), res, res, alpha=False, float_buffer=False)
    im.colorspace_settings.name = cs
    imgs[k] = im
nodes = {}
for k, im in imgs.items():
    n = ml.node_tree.nodes.new("ShaderNodeTexImage"); n.image = im; nodes[k] = n
for o in bpy.context.scene.objects: o.select_set(o in (hi, lo))
bpy.context.view_layer.objects.active = lo
bk = sc.render.bake
bk.use_selected_to_active = True; bk.cage_extrusion = extr; bk.max_ray_distance = ray; bk.margin = 8
for k, typ in (("color", "DIFFUSE"), ("normal", "NORMAL"), ("rough", "ROUGHNESS")):
    ml.node_tree.nodes.active = nodes[k]
    kw = {}
    if typ == "DIFFUSE":
        bk.use_pass_direct = False; bk.use_pass_indirect = False; bk.use_pass_color = True
        kw = dict(pass_filter={"COLOR"})
    bpy.ops.object.bake(type=typ, normal_space="TANGENT", **kw)
    p = os.path.join(out_dir, "%s_%s.png" % (name, k))
    imgs[k].filepath_raw = p; imgs[k].file_format = "PNG"; imgs[k].save()
    print("baked", p)
# wire the low material for previews / GLB
nt2 = ml.node_tree; b2 = nt2.nodes["Principled BSDF"]
nt2.links.new(nodes["color"].outputs[0], b2.inputs["Base Color"])
nt2.links.new(nodes["rough"].outputs[0], b2.inputs["Roughness"])
nm = nt2.nodes.new("ShaderNodeNormalMap"); nt2.links.new(nodes["normal"].outputs[0], nm.inputs["Color"]); nt2.links.new(nm.outputs[0], b2.inputs["Normal"])
b2.inputs["Metallic"].default_value = 0.0
if opt("--glb"):
    for o in bpy.context.scene.objects: o.select_set(o == lo)
    bpy.ops.export_scene.gltf(filepath=opt("--glb"), use_selection=True, export_format="GLB")
    print("glb", opt("--glb"))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out_dir, name + "_bake.blend"), compress=True)
