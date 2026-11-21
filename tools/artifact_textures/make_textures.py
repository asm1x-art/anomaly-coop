r"""Artefact textures, made again: upscaled (Real-ESRGAN, which also cleans the DXT/JPEG blocks), the original DXT kind
and alpha kept, a full mip chain, and a bump map where textures.ini asks for one.
  python tools/artifact_textures/make_textures.py [--only artifact\artifact_lava] [--src ...] [--work ...]
Reads the vanilla textures (unpacked from Anomaly's db) and writes into this worktree's gamedata/textures:
  <name>.dds                     the texture, same DXT kind (DXT1 / DXT1 with 1-bit alpha / DXT3 / DXT5), full mips
  <name>_bump.dds, _bump#.dds    X-Ray's bump pair (below), DXT5, full mips
  <name>.thm or <name>.ltx       turns the bump on: the vanilla .thm with its bump chunk set to "use" when the texture
                                 has one (a .thm wins over a .ltx in the engine), else a [texture] .ltx (monolith)
X-Ray's bump (checked against vanilla pairs, shaders r3 sload.h):
  _bump   R = gloss, G = normal z, B = normal y, A = normal x  (unpack 2v-1; x = -dh/dx, y = -dh/d(row), z up)
  _bump#  RGB = the normal's DXT error (+0.5; vanilla ships it flat 0.5, Anomaly's SSFX sload ignores it), A = height
          (read only by parallax)
Tools (official releases, put anywhere, --tools points at the folder that holds both):
  realesrgan/dist/realesrgan-ncnn-vulkan.exe  Real-ESRGAN ncnn Vulkan 20220424 (v0.2.5.0), model realesrgan-x4plus
  texconv/texconv.exe                         DirectXTex texconv may2026
"""
import argparse
import configparser
import os
import shutil
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

ap = argparse.ArgumentParser()
ap.add_argument("--src", default=r"X:\yantar-tools\work\gamedata\textures", help="vanilla textures, unpacked")
ap.add_argument("--out", default=os.path.join(ROOT, "gamedata", "textures"))
ap.add_argument("--work", default=r"H:\stalker-test\aftex-work", help="intermediate PNGs")
ap.add_argument("--tools", default=r"H:\stalker-test\tools-ext")
ap.add_argument("--model", default="realesrgan-x4plus")
ap.add_argument("--only", action="append", help="texture name(s) from textures.ini; default all")
a = ap.parse_args()

ESRGAN = os.path.join(a.tools, "realesrgan", "dist", "realesrgan-ncnn-vulkan.exe")
TEXCONV = os.path.join(a.tools, "texconv", "texconv.exe")
BC = {b"DXT1": "BC1_UNORM", b"DXT3": "BC2_UNORM", b"DXT5": "BC3_UNORM"}


def dds_header(path):
    h = open(path, "rb").read(128)
    height, width = struct.unpack_from("<II", h, 12)
    mips = struct.unpack_from("<I", h, 28)[0]
    return width, height, h[84:88], mips


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("failed: %s\n%s%s" % (" ".join(cmd), r.stdout, r.stderr))


def upscale(img, scale, tag):
    """x4 by Real-ESRGAN on a wrap-padded copy (the textures tile: no seams at the edges), cropped, then resized to
    the asked scale (Lanczos). img: HxWx3 uint8."""
    h, w = img.shape[:2]
    pad = max(8, min(h, w) // 8)
    padded = np.pad(img, ((pad, pad), (pad, pad), (0, 0)), mode="wrap")
    src = os.path.join(a.work, tag + "_in.png")
    dst = os.path.join(a.work, tag + "_x4.png")
    Image.fromarray(padded).save(src)
    run([ESRGAN, "-i", src, "-o", dst, "-n", a.model, "-s", "4", "-f", "png"])
    up = np.asarray(Image.open(dst).convert("RGB"))
    up = up[pad * 4:(pad + h) * 4, pad * 4:(pad + w) * 4]
    if scale != 4:
        up = np.asarray(Image.fromarray(up).resize((w * scale, h * scale), Image.LANCZOS))
    # keep the original's colour and brightness: the upscaler's own low frequencies (it darkens / shifts small, blurry
    # sources, e.g. a 64 px lava) are swapped for the plain-resized original's; only its new detail is kept
    ref = np.asarray(Image.fromarray(img).resize((w * scale, h * scale), Image.LANCZOS)).astype(np.float32)
    s = (max(scale, 2) * 0.75, max(scale, 2) * 0.75, 0)
    upf = up.astype(np.float32)
    upf += ndimage.gaussian_filter(ref, s, mode="wrap") - ndimage.gaussian_filter(upf, s, mode="wrap")
    return np.clip(upf + 0.5, 0, 255).astype(np.uint8)


def make_bump(rgb, strength, gloss, detail):
    """X-Ray _bump and _bump# (RGBA uint8) from the colour: height = luminance, high-passed so only the surface's own
    relief stays (not its big light/dark patches), normal from its slopes."""
    f = rgb.astype(np.float32) / 255.0
    lum = f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114
    lum = ndimage.gaussian_filter(lum, 0.8, mode="wrap")
    hp = lum - ndimage.gaussian_filter(lum, detail, mode="wrap")
    scale_px = rgb.shape[1] / 256.0  # the same relief whatever the size
    dx = (np.roll(hp, -1, 1) - np.roll(hp, 1, 1)) * 0.5 * scale_px
    dy = (np.roll(hp, -1, 0) - np.roll(hp, 1, 0)) * 0.5 * scale_px
    n = np.stack([-dx * strength * 8, -dy * strength * 8, np.ones_like(hp)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    enc = np.clip((n * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8)
    bump = np.empty(rgb.shape[:2] + (4,), np.uint8)
    bump[..., 0] = int(round(gloss * 255))
    bump[..., 1] = enc[..., 2]  # z
    bump[..., 2] = enc[..., 1]  # y
    bump[..., 3] = enc[..., 0]  # x
    height = np.clip(0.5 + hp * 2.0, 0, 1)
    bx = np.empty_like(bump)
    bx[..., 0:3] = 128
    bx[..., 3] = (height * 255 + 0.5).astype(np.uint8)
    return bump, bx


def to_dds(rgba, out_dds, fmt, alpha_kind):
    """PNG -> DDS by texconv: legacy DX9 header (as vanilla), full mips, alpha mipped on its own."""
    os.makedirs(os.path.dirname(out_dds), exist_ok=True)
    base = os.path.splitext(os.path.basename(out_dds))[0]
    png = os.path.join(a.work, base.replace("#", "_x") + ".png")
    Image.fromarray(rgba).save(png)
    cmd = [TEXCONV, "-nologo", "-y", "-dx9", "-m", "0", "-f", fmt, "-sepalpha", "--ignore-srgb", "-o", a.work, png]
    if alpha_kind == "1bit":
        cmd[1:1] = ["-at", "0.5", "--keep-coverage", "0.5"]
    run(cmd)
    shutil.move(os.path.join(a.work, os.path.splitext(os.path.basename(png))[0] + ".dds"), out_dds)


def write_thm_on(src_thm, dst_thm, bump_name):
    """The vanilla .thm with THM_CHUNK_BUMP (0x817: float virtual height, u32 mode, name) set to mode 2 = use."""
    b = open(src_thm, "rb").read()
    out, o, done = bytearray(), 0, False
    while o + 8 <= len(b):
        cid, sz = struct.unpack_from("<II", b, o)
        data = b[o + 8:o + 8 + sz]
        if cid == 0x817:
            vh = struct.unpack_from("<f", data, 0)[0]
            data = struct.pack("<fI", vh, 2) + bump_name.encode("ascii") + b"\0"
            done = True
        out += struct.pack("<II", cid, len(data)) + data
        o += 8 + sz
    if not done:
        data = struct.pack("<fI", 0.05, 2) + bump_name.encode("ascii") + b"\0"
        out += struct.pack("<II", 0x817, len(data)) + data
    os.makedirs(os.path.dirname(dst_thm), exist_ok=True)
    open(dst_thm, "wb").write(bytes(out))


def main():
    ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    ini.optionxform = str
    ini.read(os.path.join(HERE, "textures.ini"), encoding="utf-8")
    names = a.only or ini.sections()
    os.makedirs(a.work, exist_ok=True)
    for name in names:
        c = ini[name]
        t0 = time.time()
        rel = name.replace("\\", os.sep)
        src = os.path.join(a.src, rel + ".dds")
        w, h, fourcc, mips = dds_header(src)
        im = Image.open(src)
        im.load()
        rgba = np.asarray(im.convert("RGBA"))
        alpha = rgba[..., 3]
        if fourcc == b"DXT1":
            alpha_kind = "1bit" if alpha.min() < 128 else "none"
        else:
            alpha_kind = "none" if alpha.min() == 255 else "full"
        scale = int(c.get("scale", "4"))
        tag = name.replace("\\", "_")
        rgb = upscale(rgba[..., :3], scale, tag)
        if alpha_kind == "none":
            a_up = np.full(rgb.shape[:2], 255, np.uint8)
        else:
            # the alpha's shape through the upscaler too (as grey), so cut-outs stay crisp, not blurred
            a3 = np.repeat(alpha[..., None], 3, -1)
            a_up = upscale(a3, scale, tag + "_alpha").mean(-1).round().astype(np.uint8)
            if alpha_kind == "1bit":
                a_up = np.where(a_up >= 128, 255, 0).astype(np.uint8)
        out = np.dstack([rgb, a_up])
        to_dds(out, os.path.join(a.out, rel + ".dds"), BC[fourcc], alpha_kind)
        line = "%-34s %4dx%-4d %s mips %2d -> %4dx%-4d %s alpha %s" % (
            name, w, h, fourcc.decode(), mips, rgb.shape[1], rgb.shape[0], BC[fourcc], alpha_kind)
        if c.get("bump", "0") == "1":
            bump, bx = make_bump(rgb, float(c["strength"]), float(c["gloss"]), float(c["detail"]))
            to_dds(bump, os.path.join(a.out, rel + "_bump.dds"), "BC3_UNORM", "full")
            half = Image.fromarray(bx).resize((bx.shape[1] // 2, bx.shape[0] // 2), Image.LANCZOS)
            to_dds(np.asarray(half), os.path.join(a.out, rel + "_bump#.dds"), "BC3_UNORM", "full")
            thm = os.path.join(a.src, rel + ".thm")
            if os.path.exists(thm):
                write_thm_on(thm, os.path.join(a.out, rel + ".thm"), name + "_bump")
                line += " bump (.thm)"
            else:
                with open(os.path.join(a.out, rel + ".ltx"), "w", newline="\r\n") as f:
                    f.write("; the bump pair %s_bump / _bump# (tools/artifact_textures)\n[texture]\nbump_mode = use\n" % name)
                line += " bump (.ltx)"
        print(line + "  %.1fs" % (time.time() - t0), flush=True)


main()
