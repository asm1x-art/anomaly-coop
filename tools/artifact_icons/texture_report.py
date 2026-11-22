r"""Which textures each artefact model uses, their size, format and bump map; which are shared between artefacts.
  python tools/artifact_icons/texture_report.py [--meshes X:\coop\artifact-fx\unpack\meshes] [--textures X:\coop\yantar-tools\work\gamedata\textures]
Writes a tab-separated table to stdout. Models and textures as unpacked from the game's archives.
"""
import argparse, collections, json, os, re, struct

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--meshes", default=r"X:\coop\artifact-fx\unpack\meshes")
ap.add_argument("--textures", default=r"X:\coop\yantar-tools\work\gamedata\textures")
a = ap.parse_args()


def ogf_textures(path):
    """(texture, shader) pairs of the OGF_TEXTURE chunks: two zero-terminated strings, the second a shader name"""
    b = open(path, "rb").read()
    out = []
    for m in re.finditer(rb"([a-z0-9_\\]+)\x00(models\\[a-z0-9_]+)\x00", b):
        t, s = m.group(1).decode(), m.group(2).decode()
        if (t, s) not in out:
            out.append((t, s))
    return out


def dds_info(tex):
    p = os.path.join(a.textures, tex.replace("\\", os.sep) + ".dds")
    if not os.path.exists(p):
        seq = os.path.join(a.textures, tex.replace("\\", os.sep) + ".seq")
        return "missing" + (" (.seq animation)" if os.path.exists(seq) else "")
    h = open(p, "rb").read(128)
    height, width = struct.unpack_from("<II", h, 12)
    mips = struct.unpack_from("<I", h, 28)[0]
    fourcc = h[84:88].decode("ascii", "replace").strip("\0") or "RGB%d" % struct.unpack_from("<I", h, 88)[0]
    return "%dx%d %s mips %d" % (width, height, fourcc, mips)


def has_bump(tex):
    return os.path.exists(os.path.join(a.textures, tex.replace("\\", os.sep) + "_bump.dds"))


secs = json.load(open(os.path.join(HERE, "sections.json"), encoding="utf-8"))
users = collections.defaultdict(list)
rows = []
for s in secs:
    ogf = os.path.join(a.meshes, s["visual"].replace("\\", os.sep))
    if not os.path.exists(ogf):
        continue
    for t, sh in ogf_textures(ogf):
        users[t].append(s["sec"])
        rows.append((s["sec"], s["family"], t, sh, dds_info(t), "bump" if has_bump(t) else "no bump"))
print("section\tfamily\ttexture\tshader\tsize/format\tbump\tshared with")
for r in rows:
    others = [x for x in users[r[2]] if x != r[0]]
    print("\t".join(r) + "\t" + ",".join(sorted(set(others))))
