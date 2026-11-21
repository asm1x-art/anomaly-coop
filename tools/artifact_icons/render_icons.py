r"""Blender (headless) side of the artefact icons: every artefact model rendered with one camera and one light setup.

Run by make_icons.py, not by hand:
  blender -b --factory-startup -noaudio --python render_icons.py -- <jobs.json> <out dir> <gamedata dir>

jobs.json: [{"sec": "af_medusa", "ogf": "<abs path>.ogf", "w": 1, "h": 1, "rim": [r, g, b]}, ...]
Writes <out dir>/<sec>.png (transparent, 256 px a cell) for each job, and <out dir>/render_log.txt.

The model's surfaces by their X-Ray shader (blender-xray keeps it as material.xray.eshader):
  distortion (models\xdistort*)          hidden: it only bends what is behind
  light planes (models\lightplanes)      glowing sprites: emission from the texture, added on top
  self-lit (models\selflight*)           the texture as is plus a glow of it
  webs/windows (pautina, window, aref)   cut out / see-through by the texture's alpha
  the rest                               a lit surface with the texture
Light: a key light from the upper left, a soft fill, and a rim light from behind in the artefact family's colour (the
in-game glow's colour), so the icons read as one set.
"""
import json
import math
import os
import sys

import bpy
import addon_utils
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
JOBS, OUT, GAMEDATA = argv[0], argv[1], argv[2]
CELL = 256

addon_utils.enable("io_scene_xray", default_set=True)
pref = bpy.context.preferences.addons["io_scene_xray"].preferences
pref.gamedata_folder = GAMEDATA.replace("\\", "/").rstrip("/") + "/"

log = open(os.path.join(OUT, "render_log.txt"), "a", encoding="utf-8")


def say(*a):
    t = " ".join(str(x) for x in a)
    print(t)
    log.write(t + "\n")
    log.flush()


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.samples = 96
    cy.use_denoising = True
    cy.max_bounces = 6
    cy.transparent_max_bounces = 16
    # a GPU if Blender finds one, else the CPU
    try:
        cp = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                cp.compute_device_type = kind
                cp.get_devices()
                if any(d.type == kind for d in cp.devices):
                    for d in cp.devices:
                        d.use = d.type == kind
                    cy.device = "GPU"
                    say("render device", kind)
                    break
            except Exception:
                pass
    except Exception as e:
        say("no GPU:", e)
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "Medium High Contrast"
    sc.view_settings.exposure = 0.0
    w = bpy.data.worlds.new("afx_world")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.08, 0.085, 0.095, 1)
    bg.inputs[1].default_value = 1.0
    sc.world = w


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures, bpy.data.images, bpy.data.lights, bpy.data.cameras):
        for b in list(coll):
            if b.users == 0:
                coll.remove(b)


def tex_node(m):
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            return n
    return None


def fix_missing_image(tex):
    """an animated texture (.seq) is a folder of frames next to it: take the first frame"""
    img = tex.image
    p = bpy.path.abspath(img.filepath)
    if os.path.exists(p):
        return
    base = os.path.basename(p).lower()
    for root, _, files in os.walk(os.path.dirname(p)):
        for f in files:
            if f.lower() == base:
                img.filepath = os.path.join(root, f)
                img.reload()
                say("  texture from", img.filepath)
                return


def remake_material(m, shell=False):
    """the X-Ray shader's look in Cycles; returns False for a surface that should not show. shell: a distortion
    surface shows as coloured glass (a model that has nothing else)"""
    es = (getattr(m, "xray", None) and m.xray.eshader or "").lower()
    if shell and "distort" in es and "color" not in es:
        es = es + "color"
    nt = m.node_tree
    tex = tex_node(m)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    for n in list(nt.nodes):
        if n not in (tex, out):
            nt.nodes.remove(n)
    if "distort" in es and "color" not in es:
        return False
    links = nt.links
    if tex is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        links.new(bsdf.outputs[0], out.inputs[0])
        return True
    tex.interpolation = "Cubic"
    fix_missing_image(tex)
    if "lightplanes" in es:
        # a glowing sprite: as opaque as it is bright, so it shows on the transparent background too
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs[1].default_value = 2.5
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        bw = nt.nodes.new("ShaderNodeRGBToBW")
        mix = nt.nodes.new("ShaderNodeMixShader")
        links.new(tex.outputs["Color"], em.inputs[0])
        links.new(tex.outputs["Color"], bw.inputs[0])
        links.new(bw.outputs[0], mix.inputs[0])
        links.new(tr.outputs[0], mix.inputs[1])
        links.new(em.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
        return True
    if "distort" in es:
        # a coloured distortion shell: see-through glass of its colour, faintly glowing
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 0.35
        bsdf.inputs["Alpha"].default_value = 0.45
        bsdf.inputs["Roughness"].default_value = 0.2
        links.new(bsdf.outputs[0], out.inputs[0])
        return True
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.45
    if "selflight" in es:
        links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 0.6
    if any(k in es for k in ("pautina", "window", "aref", "selflightl")) or "alpha" in es:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs[0], out.inputs[0])
    return True


def light(name, kind, energy, color, loc, size=1.0):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == "AREA":
        ld.size = size
    o = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc
    d = Vector((0, 0, 0)) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


def render_one(job):
    clear()
    d, f = os.path.split(job["ogf"])
    r = bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=False)
    if r != {"FINISHED"}:
        say("! import failed", job["sec"], r)
        return False
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    shown = []
    for o in meshes:
        keep = True
        for s in o.material_slots:
            if s.material and s.material.use_nodes and not remake_material(s.material):
                keep = False
        o.hide_render = not keep
        if keep:
            shown.append(o)
    if not shown:
        # only distortion surfaces (the AMK ones): show them as coloured glass
        clear()
        bpy.ops.xray_import.ogf(directory=d, files=[{"name": f}], import_motions=False)
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        for o in meshes:
            for s_ in o.material_slots:
                if s_.material and s_.material.use_nodes:
                    remake_material(s_.material, shell=True)
            o.hide_render = False
        shown = meshes
    bpy.context.view_layer.update()
    # the visible part's box, in world space (X-Ray Y-up is turned Z-up by the importer)
    pts = []
    for o in shown:
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) / 2
    rad = max((p - ctr).length for p in pts)
    # one camera for all: from the front-right, a little from above, orthographic, the model's sphere fills 88%
    az, el = math.radians(30), math.radians(22)
    dirv = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam_d = bpy.data.cameras.new("cam")
    cam_d.type = "ORTHO"
    w, h = job.get("w", 1), job.get("h", 1)
    cam_d.ortho_scale = 2 * rad / 0.88 * max(1.0, w / h if w > h else h / w)
    cam = bpy.data.objects.new("cam", cam_d)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = ctr + dirv * (rad * 6)
    cam.rotation_euler = (-dirv).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    # lights, sized to the model
    k = rad * 6
    rim = job.get("rim", [0.8, 0.9, 1.0])
    light("key", "AREA", 60 * k * k, (1.0, 0.97, 0.92), ctr + Vector((-0.6, -1.0, 1.0)) * k, size=k * 0.6)
    light("fill", "AREA", 15 * k * k, (0.85, 0.9, 1.0), ctr + Vector((1.0, -0.6, 0.2)) * k, size=k)
    light("rim", "AREA", 90 * k * k, tuple(rim), ctr + Vector((0.3, 1.0, 0.6)) * k, size=k * 0.5)
    sc = bpy.context.scene
    sc.render.resolution_x = CELL * w
    sc.render.resolution_y = CELL * h
    sc.render.filepath = os.path.join(OUT, job["sec"] + ".png")
    bpy.ops.render.render(write_still=True)
    say("ok", job["sec"], f, "surfaces", len(meshes), "shown", len(shown))
    return True


setup_render()
jobs = json.load(open(JOBS, encoding="utf-8"))
done = 0
for j in jobs:
    try:
        if render_one(j):
            done += 1
    except Exception as e:
        say("! error", j.get("sec"), repr(e))
say("rendered", done, "of", len(jobs))
