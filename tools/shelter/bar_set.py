# The shelter's bar furniture (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Бар: мебель"): modules cut out of the 100 Rentgen's own things (l05_bar's
# static geometry, levelscan.py's .pkl) so that a counter of any length can be put together for the room, each made a rigid model
# Hideout Furniture places and a default recipe of the workbench's (the "blueprints": no finding, no recipe item).
#   bar_set.py <scan dir> <texture root>... [--preview out.jpg]
#     -> gamedata\meshes\dynamics\shelter\bar\*.ogf, gamedata\textures\ui\shelter\bar_icons.dds,
#        gamedata\configs\mod_system_shelter_bar.ltx, gamedata\configs\items\settings\mod_craft_shelter_bar.ltx,
#        gamedata\configs\text\<lang>\st_shelter_bar.xml
# A module: a thing of the level, the part of it along its x kept (connected parts wholly inside, in metres from its low end),
# textures dropped by name (the cookware off a plain section), parts above a height dropped (what's left of it). Connected parts are
# the level's own, nothing is cut through. The counter's sections keep the level's frame, so they stand side by side as they stood.
import os
import pickle
import sys

import numpy as np
from PIL import Image

import ogf
import ogfview
import packs

GAMEDATA = packs.GAMEDATA
COOKWARE = ("prop_kastrula", "prop_trube", "prop_blevotina", "prop_lamppost2", "wood_table_01")
# name, ru, en, thing, x range, textures left out, the height kept (None: all), materials: (section, how many) twice
MODULES = [
    ("counter", "Секция барной стойки", "Bar counter section", "l05_bar_56", (1.67, 3.50), COOKWARE, 1.02,
     (("prt_i_wood", 8), ("prt_i_scrap", 3))),
    ("counter_short", "Короткая секция стойки", "Short bar counter section", "l05_bar_56", (1.10, 1.67), COOKWARE, 1.02,
     (("prt_i_wood", 3), ("prt_i_scrap", 1))),
    ("counter_kitchen", "Секция стойки с посудой", "Bar counter section with cookware", "l05_bar_56", (1.67, 3.50), (), None,
     (("prt_i_wood", 8), ("prt_i_scrap", 5))),
    ("counter_sink", "Кухонная секция с мойкой", "Kitchen section with a sink", "l05_bar_57", (-0.01, 3.50), ("prop_blevotina",), None,
     (("prt_i_wood", 10), ("prt_i_scrap", 6))),
    ("fridge", "Холодильник бара", "The bar's fridge", "l05_bar_56", (-0.01, 1.08), (), None,
     (("prt_i_scrap", 8), ("prt_i_copper", 4))),
    ("buffet", "Буфет с полками", "A buffet with shelves", "l05_bar_4", (-0.01, 1.82), (), None,
     (("prt_i_wood", 8), ("prt_i_fasteners", 4))),
    ("cabinet", "Тумба за стойку", "A cabinet behind the counter", "l05_bar_265", (-0.01, 0.93), (), None,
     (("prt_i_wood", 5), ("prt_i_fasteners", 2))),
    ("table", "Стол из бара", "A table from the bar", "l05_bar_397", (-0.01, 1.63), (), None,
     (("prt_i_wood", 6), ("prt_i_fasteners", 3))),
    ("table_small", "Столик из бара", "A small table from the bar", "l05_bar_407", (-0.01, 0.46), (), None,
     (("prt_i_wood", 3), ("prt_i_fasteners", 1))),
    ("chair", "Стул из бара", "A chair from the bar", "l05_bar_406", (-0.01, 0.67), (), None,
     (("prt_i_wood", 2), ("prt_i_fasteners", 1))),
]


def connected(m):
    """triangles of a mesh by connected part, vertices welded by position (a millimetre): lists of indices into I"""
    key = {}
    weld = np.array([key.setdefault(tuple(k), len(key)) for k in np.round(m["P"] * 1000).astype(np.int64)])
    parent = list(range(len(key)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for t in weld[m["I"]]:
        a = find(t[0])
        for b in t[1:]:
            b = find(b)
            if a != b:
                parent[b] = a
    roots = np.array([find(weld[t[0]]) for t in m["I"]])
    return [np.nonzero(roots == r)[0] for r in np.unique(roots)]


def centred(meshes):
    """the level's frame kept, the origin at the bottom's middle"""
    P = np.concatenate([m["P"] for m in meshes])
    lo, hi = P.min(0), P.max(0)
    foot = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    return [dict(m, P=m["P"] - foot) for m in meshes]


def module_meshes(thing, x_range, drop, height):
    lo = np.concatenate([m["P"] for m in thing["meshes"]]).min(0)
    out = []
    for m in thing["meshes"]:
        if m["tex"].split("\\")[-1] in drop:
            continue
        keep = []
        for tris in connected(m):
            q = m["P"][np.unique(m["I"][tris])] - lo
            if q[:, 0].min() >= x_range[0] and q[:, 0].max() <= x_range[1] and (height is None or q[:, 1].max() <= height):
                keep.append(tris)
        if not keep:
            continue
        tris = np.concatenate(keep)
        used = np.unique(m["I"][tris])
        remap = np.full(len(m["P"]), -1)
        remap[used] = np.arange(len(used))
        out.append(dict(m, P=m["P"][used], N=m["N"][used], UV=m["UV"][used], I=remap[m["I"][tris]]))
    return out


def main():
    args = sys.argv[1:]
    preview = None
    if "--preview" in args:
        i = args.index("--preview")
        preview = args[i + 1]
        del args[i:i + 2]
    scan_dir, tex_roots = args[0], args[1:]
    things = {t["id"]: t for t in pickle.load(open(os.path.join(scan_dir, "l05_bar.pkl"), "rb"))}
    out_dir = os.path.join(GAMEDATA, "meshes", "dynamics", "shelter", "bar")
    os.makedirs(out_dir, exist_ok=True)
    atlas = Image.new("RGBA", (packs.ICON * 10, 256), (0, 0, 0, 0))
    sections = ["; The shelter's bar furniture: written by tools\\shelter\\bar_set.py.", ""]
    recipes = ["; The bar's furniture on the workbench: known from the start (tools\\shelter\\bar_set.py)", "[7]", "title = st_shelter_craft_bar"]
    texts = {"rus": {"st_shelter_craft_bar": "Мебель бара"}, "eng": {"st_shelter_craft_bar": "Bar furniture"}}
    texts["rus"]["st_shelter_bar_descr"] = "Мебель для бара, как в «100 рентген». Ставится прямо из рюкзака; колесо поворачивает. Секции стоят встык: собирайте стойку нужной длины."
    texts["eng"]["st_shelter_bar_descr"] = "Bar furniture, as in the 100 Rentgen. Placed right from the backpack, the wheel turns it. Sections stand side by side: build a counter of the length you need."
    views = []
    for n, (name, ru, en, thing, x_range, drop, height, materials) in enumerate(MODULES):
        meshes = module_meshes(things[thing], x_range, drop, height)
        meshes = centred(meshes) if name.startswith("counter") else packs.upright(meshes)
        allP = np.concatenate([m["P"] for m in meshes])
        lo, hi = allP.min(0), allP.max(0)
        centre, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 0.02)
        wood = any("wood" in m["tex"] for m in meshes)
        material = "objects\\large_furniture" if wood else "objects\\large_metal_trash"
        mass = float(np.clip(np.prod(hi - lo) * 60, 3, 120))
        ogf.write(os.path.join(out_dir, name + ".ogf"), [(m["tex"], m["P"], m["N"], m["UV"], m["I"]) for m in meshes],
                  [(centre, half, mass)], f"shelter bar {name}", material)
        atlas.paste(packs.icon_of(meshes, tex_roots), (n * packs.ICON, 0))
        visual = f"dynamics\\shelter\\bar\\{name}.ogf"
        item, prop = f"shelter_item_bar_{name}", f"shelter_bar_{name}"
        sections += [
            f"[{item}]:tch_junk", "class                   = II_ATTCH", "kind                    = i_tool",
            f"visual                  = {visual}", "description             = st_shelter_bar_descr",
            f"inv_name                = st_{item}", f"inv_name_short          = st_{item}",
            "icons_texture           = ui\\shelter\\bar_icons", f"inv_grid_x              = {n * 2}", "inv_grid_y              = 0",
            "inv_grid_width          = 2", "inv_grid_height         = 2", "cost                    = 200", f"inv_weight              = {min(mass, 30):.1f}",
            "use1_functor            = placeable_furniture.place_item", "use1_action_functor     = placeable_furniture.func_place_item",
            "placeable_type          = prop", f"placeable_section       = {prop}", "shelter_category        = bar", "",
            f"[{prop}]:physic_object", f"visual                  = {visual}", "placeable_type          = prop",
            "base_rotation           = 0", "script_binding          = bind_hf_base.init", f"item_section            = {item}",
            f"bounding_box_size       = {hi[0]-lo[0]:.3f}, {hi[2]-lo[2]:.3f}, {hi[1]-lo[1]:.3f}",
            f"bounding_box_origin     = {centre[0]:.3f}, {centre[1]:.3f}, {centre[2]:.3f}", ""]
        (a, an), (b, bn) = materials
        recipes.append(f"x_{item} = 1, recipe_basic_0, {a},{an},{b},{bn}")
        texts["rus"][f"st_{item}"] = ru
        texts["eng"][f"st_{item}"] = en
        print(f"{name}: {sum(len(m['I']) for m in meshes)} triangles, {hi[0]-lo[0]:.2f} x {hi[1]-lo[1]:.2f} x {hi[2]-lo[2]:.2f}, {sorted({m['tex'].split(chr(92))[-1] for m in meshes})}")
        if preview:
            col = ogfview.view(meshes, tex_roots, 0.6, 400)
            views.append(Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8), "RGB"))
    atlas.save(os.path.join(GAMEDATA, "textures", "ui", "shelter", "bar_icons.dds"))
    with open(os.path.join(GAMEDATA, "configs", "mod_system_shelter_bar.ltx"), "w", encoding="cp1251", newline="\r\n") as f:
        f.write("\n".join(sections))
    with open(os.path.join(GAMEDATA, "configs", "items", "settings", "mod_craft_shelter_bar.ltx"), "w", encoding="cp1251", newline="\r\n") as f:
        f.write("\n".join(recipes) + "\n")
    for lang, table in texts.items():
        with open(os.path.join(GAMEDATA, "configs", "text", lang, "st_shelter_bar.xml"), "w", encoding="cp1251", newline="\r\n") as f:
            f.write('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n')
            for sid, text in table.items():
                f.write(f'\t<string id="{sid}">\n\t\t<text>{text}</text>\n\t</string>\n')
            f.write("</string_table>\n")
    if preview:
        W = 5
        sheet = Image.new("RGB", (W * 400, ((len(views) + W - 1) // W) * 400))
        for k, v in enumerate(views):
            sheet.paste(v, ((k % W) * 400, (k // W) * 400))
        sheet.save(preview, quality=88)


if __name__ == "__main__":
    main()
