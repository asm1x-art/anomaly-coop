r"""Spectrum-X textures in X-Ray form, from the Blender bakes (bake.py) and the flat textures (make_flat_textures.py).
  python tools/spectrum_x/make_xray_textures.py [--assets X:\coop\assets\spectrum-x] [--tools H:\stalker-test\tools-ext]
Writes into this worktree's gamedata/textures/dev:
  dev_spectrum_x_probe / _tablet   .dds (DXT1, full mips), _bump.dds + _bump#.dds (DXT5), .thm with the bump on
  dev_spectrum_x_screen / _cable   .dds (DXT1), no bump
The X-Ray bump pair and the .thm follow tools/artifact_textures/make_textures.py (branch artifact-textures):
  _bump  R = gloss, G = normal z, B = normal y, A = normal x (DirectX tangent space: y = -y of Blender's OpenGL bake)
  _bump# RGB = 0.5 (no DXT error term), A = height 0.5 (no parallax), half size
Gloss comes from the baked roughness, kept low ("matte"): gloss = GLOSS_K * (1 - roughness)^2, and black rubber (the
tablet's bumpers and buttons) gets a third of that. The .thm template is the Veles' item\item_detector_2.thm."""
import argparse, os, shutil, struct, subprocess, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--assets", default=r"X:\coop\assets\spectrum-x")
ap.add_argument("--tools", default=r"H:\stalker-test\tools-ext")
ap.add_argument("--vanilla", default=r"X:\coop\yantar-tools\work\gamedata\textures", help="unpacked vanilla textures (thm template)")
ap.add_argument("--out", default=os.path.join(ROOT, "gamedata", "textures"))
a = ap.parse_args()
TEXCONV = os.path.join(a.tools, "texconv", "texconv.exe")
WORK = os.path.join(a.assets, "bake", "xray"); os.makedirs(WORK, exist_ok=True)
GLOSS_K = 0.14
RUBBER_LUM, RUBBER_K = 0.07, 0.33


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: sys.exit("failed: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))


def to_dds(rgba, out_dds, fmt):
    os.makedirs(os.path.dirname(out_dds), exist_ok=True)
    base = os.path.splitext(os.path.basename(out_dds))[0]
    png = os.path.join(WORK, base.replace("#", "_x") + ".png")
    Image.fromarray(rgba).save(png)
    run([TEXCONV, "-nologo", "-y", "-dx9", "-m", "0", "-f", fmt, "-sepalpha", "--ignore-srgb", "-o", WORK, png])
    shutil.move(os.path.join(WORK, os.path.splitext(os.path.basename(png))[0] + ".dds"), out_dds)


def write_thm_on(src_thm, dst_thm, bump_name):
    """the template .thm with THM_CHUNK_BUMP (0x817: float virtual height, u32 mode, name) set to mode 2 = use"""
    b = open(src_thm, "rb").read(); out, o, done = bytearray(), 0, False
    while o + 8 <= len(b):
        cid, sz = struct.unpack_from("<II", b, o); data = b[o + 8:o + 8 + sz]
        if cid == 0x817:
            data = struct.pack("<fI", struct.unpack_from("<f", data, 0)[0], 2) + bump_name.encode("ascii") + b"\0"; done = True
        out += struct.pack("<II", cid, len(data)) + data; o += 8 + sz
    if not done:
        data = struct.pack("<fI", 0.05, 2) + bump_name.encode("ascii") + b"\0"
        out += struct.pack("<II", 0x817, len(data)) + data
    open(dst_thm, "wb").write(bytes(out))


def full(name, bake_dir, stem):
    col = np.asarray(Image.open(os.path.join(bake_dir, stem + "_color.png")).convert("RGB"))
    nrm = np.asarray(Image.open(os.path.join(bake_dir, stem + "_normal.png")).convert("RGB")).astype(np.float32) / 255
    rough = np.asarray(Image.open(os.path.join(bake_dir, stem + "_rough.png")).convert("L")).astype(np.float32) / 255
    n = nrm * 2 - 1; n[..., 1] *= -1                     # OpenGL -> DirectX
    n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-6)
    enc = np.clip((n * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)
    lum = (col.astype(np.float32) / 255) @ np.array([0.299, 0.587, 0.114], np.float32)
    gloss = GLOSS_K * (1 - rough) ** 2 * np.where(lum < RUBBER_LUM, RUBBER_K, 1.0)
    bump = np.empty(col.shape[:2] + (4,), np.uint8)
    bump[..., 0] = np.clip(gloss * 255 + 0.5, 0, 255).astype(np.uint8)
    bump[..., 1] = enc[..., 2]; bump[..., 2] = enc[..., 1]; bump[..., 3] = enc[..., 0]
    bx = np.full((col.shape[0] // 2, col.shape[1] // 2, 4), 128, np.uint8)
    rel = os.path.join("dev", name)
    to_dds(np.dstack([col, np.full(col.shape[:2], 255, np.uint8)]), os.path.join(a.out, rel + ".dds"), "BC1_UNORM")
    to_dds(bump, os.path.join(a.out, rel + "_bump.dds"), "BC3_UNORM")
    to_dds(bx, os.path.join(a.out, rel + "_bump#.dds"), "BC3_UNORM")
    write_thm_on(os.path.join(a.vanilla, "item", "item_detector_2.thm"), os.path.join(a.out, rel + ".thm"), "dev\\" + name + "_bump")
    print(name, col.shape[1], "x", col.shape[0], "gloss mean %.3f" % gloss.mean())


def flat(name, png):
    col = np.asarray(Image.open(png).convert("RGB"))
    to_dds(np.dstack([col, np.full(col.shape[:2], 255, np.uint8)]), os.path.join(a.out, "dev", name + ".dds"), "BC1_UNORM")
    print(name, col.shape[1], "x", col.shape[0])


full("dev_spectrum_x_probe", os.path.join(a.assets, "bake", "pistol_blender"), "pistol")
full("dev_spectrum_x_tablet", os.path.join(a.assets, "bake", "tablet_v2"), "tablet")
flat("dev_spectrum_x_screen", os.path.join(a.assets, "hud", "tex", "screen.png"))
flat("dev_spectrum_x_cable", os.path.join(a.assets, "hud", "tex", "cable.png"))
