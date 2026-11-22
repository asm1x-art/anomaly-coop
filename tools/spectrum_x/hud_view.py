r"""Spectrum-X: render helpers for the HUD scene (Workbench, textured): the HUD camera at the hud_fov, extra close-up
cameras, the hands' texture (act_arm_1 from the game's archives, a PNG in <assets>\hud\tex) and the devices'."""
import bpy, math, os, re
from mathutils import Matrix, Vector

TEX = {"dev_spectrum_x_probe": r"bake\pistol_blender\pistol_color.png",
       "dev_spectrum_x_tablet": r"bake\tablet_v2\tablet_color.png",
       "dev_spectrum_x_screen": r"hud\tex\screen.png",
       "dev_spectrum_x_cable": r"hud\tex\cable.png",
       "act_arm": r"hud\tex\act_arm_1.png"}


def setup(A, res=(960, 540), fov=0.45):
    sc = bpy.context.scene
    cam = bpy.data.objects.new("hudcam", bpy.data.cameras.new("hudcam")); sc.collection.objects.link(cam)
    sc.camera = cam; cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.sensor_fit = "VERTICAL"; cam.data.angle = math.radians(fov * 83); cam.data.clip_start = 0.005
    sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    sc.display.shading.show_cavity = False
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    w = bpy.data.worlds.new("w"); sc.world = w; w.color = (0.32, 0.34, 0.37)
    sc.display.shading.background_type = "WORLD"
    return cam


def texture_all(A, objs):
    imgs = {}
    for o in objs:
        if o.type != "MESH": continue
        for m in o.data.materials:
            if not m or not m.use_nodes: continue
            for n in m.node_tree.nodes:
                if n.type != "TEX_IMAGE": continue
                key = " ".join([n.name, n.label, m.name, n.image.name if n.image else "",
                                {"probe": "dev_spectrum_x_probe", "tablet": "dev_spectrum_x_tablet"}.get(o.name, "")])
                arm = re.search(r"act_arm\w*", key)
                if arm and os.path.exists(os.path.join(A, "hud", "tex", arm.group(0) + ".png")):
                    k = arm.group(0)
                    if k not in imgs: imgs[k] = bpy.data.images.load(os.path.join(A, "hud", "tex", k + ".png"))
                    n.image = imgs[k]; continue
                for k, p in TEX.items():
                    if k in key:
                        if k not in imgs: imgs[k] = bpy.data.images.load(os.path.join(A, p))
                        n.image = imgs[k]


def look_at(cam, eye, target, up=(0, 0, 1), fov_deg=None):
    eye, target = Vector(eye), Vector(target)
    d = (target - eye).normalized(); r = d.cross(Vector(up)).normalized(); u = r.cross(d)
    m = Matrix((r, u, -d)).transposed().to_4x4(); m.translation = eye
    cam.matrix_world = m
    if fov_deg: cam.data.angle = math.radians(fov_deg)


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def sheet(paths, out, cols=2, scale=1.0, labels=None):
    """contact sheet of PNGs (PIL is not in Blender: plain numpy via bpy images)"""
    import numpy as np
    ims = []
    for p in paths:
        im = bpy.data.images.load(p); w, h = im.size
        a = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)
        ims.append(a); bpy.data.images.remove(im)
    h, w = ims[0].shape[:2]; rows = (len(ims) + cols - 1) // cols
    S = np.zeros((rows * h, cols * w, 4), dtype=np.float32); S[..., 3] = 1
    for i, a in enumerate(ims):
        r, c = divmod(i, cols); S[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = a
    img = bpy.data.images.new("sheet", cols * w, rows * h); img.pixels[:] = S.ravel()
    img.filepath_raw = out; img.file_format = "PNG"; img.save(); bpy.data.images.remove(img)
