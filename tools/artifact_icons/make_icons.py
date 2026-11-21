r"""Artefact inventory icons, re-rendered from the models: one camera, one light setup for all (render_icons.py in a
headless Blender with blender-xray), then an atlas of their own and the configs that point the artefacts at it.

  python tools/artifact_icons/make_icons.py [--render] [--only af_a,af_b]

  --render   run Blender first (else the renders in the work dir are taken as they are)
  --only     just these sections (render + sheet), the atlas is still made from every render there is

Inputs
  tools/artifact_icons/sections.json   the artefacts as the game has them (section, kind, visual, inv_grid_*, icons_texture,
                                        nature), dumped in game by tools/artifact_icons/dump_sections.lua
  gamedata/configs/mod_system_artefact_fx.ltx   the families' colours (the rim light of a family's icons)
  --meshes / --gamedata                 the game's models and textures, unpacked (converter -unpack)
Outputs
  gamedata/textures/ui/ui_icon_artefacts_fx.dds   the atlas (uncompressed BGRA, 50 px a cell as the game's own)
  gamedata/configs/mod_system_artefact_fx_icons.ltx   DLTX: each artefact's icons_texture and cell in it (delete the
                                        file and the old icons are back)
  <work>/contact_sheet.png              old icon | new icon for every artefact

The icons get their own atlas instead of being written into ui_icon_equipment.dds: that one is 8192x4096 DXT5, any
icon mod replaces it, and compressing it again would blur every other icon in the game.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CELL = 50
ATLAS_COLS = 24
ATLAS_NAME = r"ui\ui_icon_artefacts_fx"


def families():
    """family -> rim colour, from the .ltx"""
    path = os.path.join(ROOT, "gamedata", "configs", "mod_system_artefact_fx.ltx")
    fam, cur = {}, None
    for line in open(path, encoding="cp1251"):
        line = line.split(";")[0].strip()
        m = re.match(r"^\[artefact_fx_family_(\w+)\]", line)
        if m:
            cur = m.group(1)
            continue
        if line.startswith("["):
            cur = None
        if cur and line.startswith("color"):
            fam[cur] = [float(x) for x in line.split("=", 1)[1].split(",")]
    return fam


def load_dds(path):
    im = Image.open(path)
    im.load()
    return im.convert("RGBA")


def write_dds_bgra(path, im):
    """an uncompressed A8R8G8B8 .dds, no mips (UI)"""
    im = im.convert("RGBA")
    w, h = im.size
    r, g, b, a = im.split()
    data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PITCH, DDSD_PIXELFORMAT = 0x1, 0x2, 0x4, 0x8, 0x1000
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT
    pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    hdr = struct.pack("<I", 124) + struct.pack("<IIIIII", flags, h, w, w * 4, 0, 0) + b"\0" * 44 + pf
    hdr += struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"DDS " + hdr + data)


def finish_icon(src, w, h):
    """the 256 px render down to the game's cell, with a soft dark halo so it reads on any background"""
    big = Image.open(src).convert("RGBA")
    out_w, out_h = CELL * w, CELL * h
    # trim to the model, then fit with a margin, keeping its proportions
    bbox = big.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        big = big.crop(bbox)
    margin = 0.08
    s = min(out_w * (1 - 2 * margin) / big.width, out_h * (1 - 2 * margin) / big.height)
    small = big.resize((max(1, round(big.width * s)), max(1, round(big.height * s))), Image.LANCZOS)
    small = small.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=1))
    icon = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    icon.alpha_composite(small, ((out_w - small.width) // 2, (out_h - small.height) // 2))
    halo_a = icon.getchannel("A").filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(1.6))
    halo = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    halo.putalpha(halo_a.point(lambda v: int(v * 0.55)))
    halo.alpha_composite(icon)
    return halo


def old_icon(sec, atlases, unpacked_ui):
    tex = sec.get("icons_texture") or r"ui\ui_icon_equipment"
    if tex not in atlases:
        p = os.path.join(unpacked_ui, tex.replace("\\", os.sep) + ".dds")
        atlases[tex] = load_dds(p) if os.path.exists(p) else None
    a = atlases[tex]
    if a is None:
        return None
    x, y, w, h = sec["x"] * CELL, sec["y"] * CELL, sec["w"] * CELL, sec["h"] * CELL
    return a.crop((x, y, x + w, y + h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--work", default=r"X:\artifact-fx\icons")
    ap.add_argument("--meshes", default=r"X:\artifact-fx\unpack\meshes")
    ap.add_argument("--gamedata", default=r"X:\yantar-tools\work\gamedata")
    ap.add_argument("--ui", default=r"X:\artifact-fx\unpack\textures", help="the unpacked textures with ui\\ (old icons)")
    ap.add_argument("--blender", default=r"X:\yantar-tools\blender\blender-4.5.16-windows-x64\blender.exe")
    a = ap.parse_args()

    secs = json.load(open(os.path.join(HERE, "sections.json"), encoding="utf-8"))
    only = set(x for x in a.only.split(",") if x)
    fam = families()
    renders = os.path.join(a.work, "renders")
    os.makedirs(renders, exist_ok=True)

    if a.render:
        jobs = []
        for s in secs:
            if only and s["sec"] not in only:
                continue
            ogf = os.path.join(a.meshes, s["visual"].replace("\\", os.sep))
            if not ogf.lower().endswith(".ogf"):
                ogf += ".ogf"
            if not os.path.exists(ogf):
                print("no model:", s["sec"], ogf)
                continue
            jobs.append({"sec": s["sec"], "ogf": ogf, "w": s["w"], "h": s["h"],
                         "rim": fam.get(s.get("family") or "plain", fam.get("plain", [0.8, 0.9, 1.0]))})
        jp = os.path.join(a.work, "jobs.json")
        json.dump(jobs, open(jp, "w", encoding="utf-8"), indent=1)
        print("rendering", len(jobs))
        r = subprocess.run([a.blender, "-b", "--factory-startup", "-noaudio", "--python-exit-code", "1",
                            "--python", os.path.join(HERE, "render_icons.py"), "--", jp, renders, a.gamedata])
        if r.returncode:
            sys.exit("blender failed")

    # the atlas: every section with a render, in sections.json's order, shelf-packed in rows of ATLAS_COLS cells
    placed, x, y, row_h = [], 0, 0, 1
    for s in secs:
        if not os.path.exists(os.path.join(renders, s["sec"] + ".png")):
            continue
        if x + s["w"] > ATLAS_COLS:
            x, y, row_h = 0, y + row_h, 1
        placed.append((s, x, y))
        x += s["w"]
        row_h = max(row_h, s["h"])
    rows = y + row_h
    atlas = Image.new("RGBA", (ATLAS_COLS * CELL, rows * CELL), (0, 0, 0, 0))
    icons = {}
    for s, cx, cy in placed:
        icon = finish_icon(os.path.join(renders, s["sec"] + ".png"), s["w"], s["h"])
        icons[s["sec"]] = icon
        atlas.alpha_composite(icon, (cx * CELL, cy * CELL))
    dds = os.path.join(ROOT, "gamedata", "textures", "ui", "ui_icon_artefacts_fx.dds")
    os.makedirs(os.path.dirname(dds), exist_ok=True)
    write_dds_bgra(dds, atlas)
    atlas.save(os.path.join(a.work, "atlas_preview.png"))

    ltx = os.path.join(ROOT, "gamedata", "configs", "mod_system_artefact_fx_icons.ltx")
    with open(ltx, "w", encoding="cp1251", newline="\r\n") as f:
        f.write("; Artefacts' inventory icons rendered from their models (tools/artifact_icons/make_icons.py writes this file\n"
                "; and textures\\ui\\ui_icon_artefacts_fx.dds). Delete this file and the game's old icons are back.\n")
        for s, cx, cy in placed:
            f.write("\n![%s]\nicons_texture = %s\ninv_grid_x = %d\ninv_grid_y = %d\n" % (s["sec"], ATLAS_NAME, cx, cy))
    print("atlas", atlas.size, len(placed), "icons ->", dds)

    # the contact sheet: old | new, twice the size, on the inventory's dark grey
    sheet_secs = [s for s, _, _ in placed if not only or s["sec"] in only]
    atlases = {}
    cols = 6
    cw, ch = 2 * CELL * 2 + 30, 2 * CELL + 34
    W = cols * cw
    H = ((len(sheet_secs) + cols - 1) // cols) * ch + 30
    sheet = Image.new("RGBA", (W, H), (34, 36, 40, 255))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    d.text((8, 8), "old (game atlas)  |  new (rendered)   -   2x", fill=(220, 220, 220, 255), font=font)
    for i, s in enumerate(sheet_secs):
        ox, oy = (i % cols) * cw + 8, (i // cols) * ch + 30
        old = old_icon(s, atlases, a.ui)
        for j, im in enumerate((old, icons[s["sec"]])):
            if im is None:
                d.text((ox + j * (2 * CELL + 6) + 10, oy + 40), "none", fill=(200, 80, 80, 255), font=font)
                continue
            big = im.resize((im.width * 2 // max(1, s["w"]), im.height * 2 // max(1, s["h"])), Image.LANCZOS)
            bg = Image.new("RGBA", big.size, (24, 25, 28, 255))
            bg.alpha_composite(big)
            sheet.paste(bg, (ox + j * (2 * CELL + 6), oy))
        d.text((ox, oy + 2 * CELL + 3), s["sec"][:30], fill=(200, 200, 200, 255), font=font)
    out = os.path.join(a.work, "contact_sheet.png")
    sheet.save(out)
    print("sheet", out)


if __name__ == "__main__":
    main()
