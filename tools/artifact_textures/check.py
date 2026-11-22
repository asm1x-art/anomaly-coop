r"""Checks the reworked textures against vanilla without the game: every DDS opens, same DXT kind, full mips, the size
textures.ini asks for, alpha coverage as vanilla's, a vanilla name for each file, bump pairs complete and turned on.
  python tools/artifact_textures/check.py [--src ...] [--new ...]
Prints one line per texture and the anomalies at the end; exit code 1 if there are any.
"""
import argparse
import configparser
import os
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ap = argparse.ArgumentParser()
ap.add_argument("--src", default=r"X:\coop\yantar-tools\work\gamedata\textures")
ap.add_argument("--new", default=os.path.join(ROOT, "gamedata", "textures"))
a = ap.parse_args()


def header(p):
    h = open(p, "rb").read(128)
    height, width = struct.unpack_from("<II", h, 12)
    return width, height, h[84:88], struct.unpack_from("<I", h, 28)[0]


def full_mips(w, h):
    n = 1
    while w > 1 or h > 1:
        w, h, n = max(1, w // 2), max(1, h // 2), n + 1
    return n


def rgba(p):
    im = Image.open(p)
    im.load()
    return np.asarray(im.convert("RGBA"))


def thm_bump(p):
    """(mode, name) of the .thm's bump chunk 0x817, or None."""
    b = open(p, "rb").read()
    o = 0
    while o + 8 <= len(b):
        cid, sz = struct.unpack_from("<II", b, o)
        if cid == 0x817:
            d = b[o + 8:o + 8 + sz]
            return struct.unpack_from("<I", d, 4)[0], d[8:].split(b"\0")[0].decode("ascii", "replace")
        o += 8 + sz
    return None


ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
ini.optionxform = str
ini.read(os.path.join(HERE, "textures.ini"), encoding="utf-8")
bad = []
expected = set()
for name in ini.sections():
    c = ini[name]
    rel = name.replace("\\", os.sep)
    src, new = os.path.join(a.src, rel + ".dds"), os.path.join(a.new, rel + ".dds")
    expected.add(os.path.normcase(new))
    if not os.path.exists(new):
        bad.append("%s: not made" % name)
        continue
    w0, h0, f0, _ = header(src)
    w1, h1, f1, m1 = header(new)
    sc = int(c.get("scale", "4"))
    if f1 != f0:
        bad.append("%s: format %s, vanilla %s" % (name, f1, f0))
    if (w1, h1) != (w0 * sc, h0 * sc):
        bad.append("%s: size %dx%d, expected %dx%d" % (name, w1, h1, w0 * sc, h0 * sc))
    if m1 != full_mips(w1, h1):
        bad.append("%s: mips %d of %d" % (name, m1, full_mips(w1, h1)))
    try:
        old, cur = rgba(src), rgba(new)
    except Exception as e:  # noqa: BLE001 - any decode failure is the finding
        bad.append("%s: does not open (%s)" % (name, e))
        continue
    # alpha coverage at the vanilla size: share of cut-out (< 128) pixels and the mean alpha
    small = np.asarray(Image.fromarray(cur).resize((w0, h0), Image.BOX))
    cov0, cov1 = (old[..., 3] < 128).mean() * 100, (small[..., 3] < 128).mean() * 100
    mean0, mean1 = old[..., 3].mean(), small[..., 3].mean()
    if abs(cov0 - cov1) > 2.0 or abs(mean0 - mean1) > 6.0 or (old[..., 3].min() == 255) != (cur[..., 3].min() == 255):
        bad.append("%s: alpha cut-out %.1f%% -> %.1f%%, mean %.0f -> %.0f" % (name, cov0, cov1, mean0, mean1))
    line = "%-34s %4dx%-4d -> %4dx%-4d %s mips %2d  alpha<128 %5.1f%% -> %5.1f%%  mean %3.0f -> %3.0f" % (
        name, w0, h0, w1, h1, f1.decode(), m1, cov0, cov1, mean0, mean1)
    bump_dds, bx_dds = os.path.join(a.new, rel + "_bump.dds"), os.path.join(a.new, rel + "_bump#.dds")
    thm, ltx = os.path.join(a.new, rel + ".thm"), os.path.join(a.new, rel + ".ltx")
    if c.get("bump", "0") == "1":
        expected |= {os.path.normcase(bump_dds), os.path.normcase(bx_dds)}
        for p, want in ((bump_dds, (w1, h1)), (bx_dds, (w1 // 2, h1 // 2))):
            if not os.path.exists(p):
                bad.append("%s: %s missing" % (name, os.path.basename(p)))
                continue
            bw, bh, bf, bm = header(p)
            if bf != b"DXT5" or (bw, bh) != want or bm != full_mips(bw, bh):
                bad.append("%s: %s is %dx%d %s mips %d" % (name, os.path.basename(p), bw, bh, bf, bm))
            rgba(p)
        if os.path.exists(os.path.join(a.src, rel + ".thm")):
            expected.add(os.path.normcase(thm))
            tb = thm_bump(thm) if os.path.exists(thm) else None
            if tb != (2, name + "_bump"):
                bad.append("%s: .thm bump %s" % (name, tb))
            if os.path.exists(ltx):
                bad.append("%s: both .thm and .ltx" % name)
            line += "  bump .thm"
        else:
            expected.add(os.path.normcase(ltx))
            if not os.path.exists(ltx) or "bump_mode = use" not in open(ltx).read():
                bad.append("%s: no bump .ltx" % name)
            line += "  bump .ltx"
    else:
        for p in (bump_dds, bx_dds, thm, ltx):
            if os.path.exists(p):
                bad.append("%s: %s without bump = 1" % (name, os.path.basename(p)))
        if os.path.exists(os.path.join(a.src, rel + "_bump.dds")):
            line += "  vanilla bump kept"
    print(line)

# every file we ship must be one of the above and carry a vanilla texture's name
for top in sorted({n.split("\\")[0] for n in ini.sections()}):
    for dp, _, fs in os.walk(os.path.join(a.new, top)):
        for f in fs:
            p = os.path.join(dp, f)
            if os.path.normcase(p) in expected:
                stem = os.path.splitext(os.path.relpath(p, a.new))[0]
                base = stem.replace("_bump#", "").replace("_bump", "") if f.endswith(".dds") else stem
                if not os.path.exists(os.path.join(a.src, base + ".dds")):
                    bad.append("%s: no vanilla texture of that name" % p)
            elif not os.path.relpath(p, a.new).startswith(os.path.join("pfx", "coop")):
                bad.append("%s: not from textures.ini" % p)

print("\n%d textures, %d anomalies" % (len(ini.sections()), len(bad)))
for b in bad:
    print("  " + b)
sys.exit(1 if bad else 0)
