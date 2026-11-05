# The packs of things to furnish with (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Паки предметов"): things cut out of other levels' static geometry and the
# game's and addons' models, each made a rigid model of its own that Hideout Furniture places, with its name, category and an icon
# drawn from the model. packs.json lists them: { "name", "ru", "en", "cat", "from" }, "from" being "level:<thing id>" (a thing of
# levelscan.py's, its .pkl in <scan dir>) or "model:<root name>:<path of an .ogf under it>".
#   packs.py <scan dir> <texture root>...
#     -> gamedata\meshes\dynamics\shelter\packs\*.ogf, gamedata\textures\ui\shelter\pack_icons.dds,
#        gamedata\configs\mod_system_shelter_packs.ltx, gamedata\configs\text\<lang>\st_shelter_packs.xml
# The categories of everything placeable, the addons' things too, are written to [shelter_categories] by the rules below.
import json
import os
import pickle
import re
import sys

import numpy as np
from PIL import Image

import ogf
import ogfview

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
ROOTS = {
    "anomaly": None,  # set from the scan dir's sibling: the game's unpacked meshes
    "hf": r"X:\GRA2.5\MO2\mods\[Убежище] Hideout Furniture\gamedata\meshes",
    "nl": r"X:\GRA2.5\MO2\mods\[Локация] Levels_0.53\gamedata\meshes",
    "gra": r"X:\GRA2.5\MO2\mods\[Основа] GRA\gamedata\meshes",
    "wsr": r"X:\GRA2.5\MO2\mods\[Лут] World_Spawns_Rework\gamedata\meshes",
}
ICON = 100  # px of an icon; the inventory's grid is 50 px
PER_ROW = 20  # icons in a row of the texture: 2048 px across
# the categories, as the furnishing panel goes through them, with the addons' things by their section's name
CATEGORY_RULES = [
    ("bar", r"countertop|counter_1|prop_mug|prop_dish|ashtray|teapot|cuttingboard|cans_tuna|bong|decor_pot|stove|fridge|biliard|decor_game|guitar|piano|radio_item|decor_radiola"),
    ("medical", r"clinic|stretcher|med_case|decor_sink|shower|toilet"),
    ("science", r"microscope|psi_helmet|lead_box|documents|notes_writing|arti_display|exoskelet|guidebook|survivalguide"),
    ("tech", r"monitor|keyboard|mice_pad|pccase|laptop|prop_tv|tv_box|prop_fan|prop_clock"),
    ("workshop", r"workshop_item|exo_repair|gun_parts|weapon_rack|pistol_shelf|metal_plate|gaz_balon|decor_fuel|decor_bidon|decor_junk|prop_duct"),
    ("light", r"decor_light|device_gas_lamp|device_light_altar|device_metal_torch|prop_lamp"),
    ("walls", r"decor_door|decor_wall|wooden_board|wooden_plank|prop_boards|prop_door|prop_pallet"),
    ("storage", r"storage|decor_cabinet|shelves|prop_shelf|decor_box|barrel|blue_box|case_item|sumka|ammo_box|prop_crate|prop_rack"),
    ("furniture", r"prop_table|metal_table|sidetable|prop_chair|item_chair|fchair|decor_stool|couch|prop_bed|decor_rug"),
]


def category_of(section):
    for cat, rule in CATEGORY_RULES:
        if re.search(rule, section):
            return cat
    return "decor"


def placeable_sections():
    """the item sections of the addons and of the shelter: those that place something"""
    out = []
    roots = [os.path.join(GAMEDATA, "configs"), os.path.join(ROOTS["hf"], "..", "configs")]
    for root in roots:
        for dirpath, _, names in os.walk(root):
            for name in names:
                if name.endswith(".ltx") and name != "mod_system_shelter_packs.ltx":
                    sec = None
                    for line in open(os.path.join(dirpath, name), "rb"):
                        line = line.decode("cp1251", "replace")
                        m = re.match(r"\s*!?\[([^\]]+)\]", line)
                        if m:
                            sec = m.group(1)
                        elif sec and re.match(r"\s*use1_functor\s*=\s*placeable_furniture\.place_item", line):
                            out.append(sec)
    return sorted(set(out))


def straighten(meshes):
    """a thing that stands crooked on its level ("straight": true in packs.json): its plane nearest to level is made level"""
    G = np.concatenate([np.cross(m["P"][m["I"][:, 1]] - m["P"][m["I"][:, 0]], m["P"][m["I"][:, 2]] - m["P"][m["I"][:, 0]]) / 2 for m in meshes])
    A = np.linalg.norm(G, axis=1)
    G, A = G[A > 1e-7] / A[A > 1e-7, None], A[A > 1e-7]
    left, best = np.ones(len(G), bool), None
    for _ in range(8):  # the biggest planes, faces within 4 degrees of each other
        if not left.any():
            break
        face = G[np.argmax(A * left)]
        sel = left & (np.abs(G @ face) > np.cos(np.radians(4)))
        left &= ~sel
        if A[sel].sum() / A.sum() >= 0.08:
            up = (G[sel] * np.sign(G[sel] @ face)[:, None] * A[sel, None]).sum(0)
            up = up / np.linalg.norm(up) * (1 if up[1] >= 0 else -1)
            if best is None or up[1] > best[1]:
                best = up
    axis = np.cross(best, (0, 1, 0))
    sin, cos = np.linalg.norm(axis), best[1]
    k = axis / max(sin, 1e-9)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    R = np.eye(3) + sin * K + (1 - cos) * K @ K
    return [dict(m, P=m["P"] @ R.T, N=m["N"] @ R.T) for m in meshes]


def upright(meshes):
    """turned so that its footprint is the smallest (a thing of a level stands at any angle), its origin at the bottom's middle"""
    P = np.concatenate([m["P"] for m in meshes])
    best, best_area = 0.0, None
    for deg in range(0, 90):
        a = np.radians(deg)
        x = P[:, 0] * np.cos(a) - P[:, 2] * np.sin(a)
        z = P[:, 0] * np.sin(a) + P[:, 2] * np.cos(a)
        area = (x.max() - x.min()) * (z.max() - z.min())
        if best_area is None or area < best_area - 1e-6:
            best, best_area = a, area
    c, s = np.cos(best), np.sin(best)
    R = np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])
    out = []
    for m in meshes:
        out.append(dict(m, P=m["P"] @ R.T, N=m["N"] @ R.T))
    P = np.concatenate([m["P"] for m in out])
    lo, hi = P.min(0), P.max(0)
    foot = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    # the longer side along x
    swap = (hi[2] - lo[2]) > (hi[0] - lo[0])
    for m in out:
        m["P"] = m["P"] - foot
        if swap:
            m["P"] = m["P"][:, [2, 1, 0]] * np.array([-1, 1, 1])
            m["N"] = m["N"][:, [2, 1, 0]] * np.array([-1, 1, 1])
    return out


def icon_of(meshes, tex_roots):
    size = ICON * 3
    col = ogfview.view(meshes, tex_roots, 0.6, size)
    back = np.array((0.13, 0.14, 0.16), dtype=np.float32)
    alpha = (np.abs(col - back).sum(2) > 0.002).astype(np.float32)
    rgba = np.dstack([col, alpha])
    return Image.fromarray((rgba * 255).astype(np.uint8), "RGBA").resize((ICON, ICON), Image.LANCZOS)


def main():
    scan_dir, tex_roots = sys.argv[1], sys.argv[2:]
    ROOTS["anomaly"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(scan_dir))), "assets", "dyn", "meshes")
    packs = json.load(open(os.path.join(HERE, "packs.json"), encoding="utf-8"))
    things = {}
    for name in os.listdir(scan_dir):
        if name.endswith(".pkl"):
            for t in pickle.load(open(os.path.join(scan_dir, name), "rb")):
                things[t["id"]] = t
    out_dir = os.path.join(GAMEDATA, "meshes", "dynamics", "shelter", "packs")
    os.makedirs(out_dir, exist_ok=True)
    rows = (len(packs) + PER_ROW - 1) // PER_ROW
    atlas = Image.new("RGBA", (ICON * PER_ROW, 2048 if rows > 10 else 1024), (0, 0, 0, 0))
    sections = []
    texts = {"rus": {}, "eng": {}}
    used_textures = set()
    for n, p in enumerate(packs):
        kind, _, rest = p["from"].partition(":")
        if kind == "level":
            meshes = things[rest]["meshes"]
        else:
            root, _, path = rest.partition(":")
            meshes = ogfview.read_ogf(os.path.join(ROOTS[root], *path.split("/")) + ".ogf")["meshes"]
        meshes = upright(straighten(meshes) if p.get("straight") else [dict(m) for m in meshes])
        used_textures |= {m["tex"] for m in meshes}
        allP = np.concatenate([m["P"] for m in meshes])
        lo, hi = allP.min(0), allP.max(0)
        centre, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 0.02)
        wood = any("wood" in m["tex"] or "chair" in m["tex"] for m in meshes)
        material = "objects\\large_furniture" if wood else "objects\\large_metal_trash"
        mass = float(np.clip(np.prod(hi - lo) * 60, 3, 120))
        name = p["name"]
        ogf.write(os.path.join(out_dir, name + ".ogf"), [(m["tex"], m["P"], m["N"], m["UV"], m["I"]) for m in meshes],
                  [(centre, half, mass)], f"shelter pack {name}", material)
        gx, gy = n % PER_ROW * 2, n // PER_ROW * 2
        atlas.paste(icon_of(meshes, tex_roots), (n % PER_ROW * ICON, n // PER_ROW * ICON))
        visual = f"dynamics\\shelter\\packs\\{name}.ogf"
        sections += [
            f"[shelter_item_pack_{name}]:tch_junk", "class                   = II_ATTCH", "kind                    = i_tool",
            f"visual                  = {visual}", "description             = st_shelter_pack_descr",
            f"inv_name                = st_shelter_pack_{name}", f"inv_name_short          = st_shelter_pack_{name}",
            "icons_texture           = ui\\shelter\\pack_icons", f"inv_grid_x              = {gx}", f"inv_grid_y              = {gy}",
            "inv_grid_width          = 2", "inv_grid_height         = 2", "cost                    = 200", f"inv_weight              = {min(mass, 60):.1f}",
            "use1_functor            = placeable_furniture.place_item", "use1_action_functor     = placeable_furniture.func_place_item",
            "placeable_type          = prop", f"placeable_section       = shelter_pack_{name}", f"shelter_category        = {p['cat']}", "",
            f"[shelter_pack_{name}]:physic_object", f"visual                  = {visual}", "placeable_type          = prop",
            "base_rotation           = 0", "script_binding          = bind_hf_base.init", f"item_section            = shelter_item_pack_{name}",
            f"bounding_box_size       = {hi[0]-lo[0]:.3f}, {hi[2]-lo[2]:.3f}, {hi[1]-lo[1]:.3f}",
            f"bounding_box_origin     = {centre[0]:.3f}, {centre[1]:.3f}, {centre[2]:.3f}", ""]
        texts["rus"][f"st_shelter_pack_{name}"] = p["ru"]
        texts["eng"][f"st_shelter_pack_{name}"] = p["en"]
        print(f"{name}: {p['cat']}, {sum(len(m['I']) for m in meshes)} triangles, {hi[0]-lo[0]:.2f} x {hi[1]-lo[1]:.2f} x {hi[2]-lo[2]:.2f}")
    atlas.save(os.path.join(GAMEDATA, "textures", "ui", "shelter", "pack_icons.dds"))
    sections += ["; every placeable thing's category for the furnishing panel (scripts\\shelter_furniture.script)", "[shelter_categories]"]
    for sec in placeable_sections():
        if not sec.startswith("shelter_item_pack_"):
            sections.append(f"{sec} = {category_of(sec)}")
    sections += ["", "; the things' items, each once, for the test copy's key (zz_shelter_test)", "[shelter_pack_items]"]
    sections += [f"shelter_item_pack_{p['name']}" for p in packs] + [""]
    head = ["; The packs of things to furnish with: written by tools\\shelter\\packs.py from tools\\shelter\\packs.json.", ""]
    with open(os.path.join(GAMEDATA, "configs", "mod_system_shelter_packs.ltx"), "w", encoding="cp1251", newline="\r\n") as f:
        f.write("\n".join(head + sections))
    texts["rus"]["st_shelter_pack_descr"] = "Предмет обстановки. Ставится в режиме расстановки (H) из тайника убежища."
    texts["eng"]["st_shelter_pack_descr"] = "A thing to furnish with. Placed in the furnishing mode (H) from the shelter's stash."
    for lang, table in texts.items():
        with open(os.path.join(GAMEDATA, "configs", "text", lang, "st_shelter_packs.xml"), "w", encoding="cp1251", newline="\r\n") as f:
            f.write('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n')
            for sid, text in table.items():
                f.write(f'\t<string id="{sid}">\n\t\t<text>{text}</text>\n\t</string>\n')
            f.write("</string_table>\n")
    print(len(packs), "things;", "textures:", len(used_textures))
    json.dump(sorted(used_textures), open(os.path.join(os.path.abspath(scan_dir), "pack_textures.json"), "w"), indent=0)


if __name__ == "__main__":
    main()
