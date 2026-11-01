# The shelter's lighting on the workbench (docs/coop/shelter.md, "Свет"): a ceiling lamp, the same as the shelter's own, and the
# recipes of Hideout Furniture's lamps: known from the start.
#   lights_set.py <unpacked meshes> <texture root>...
#     -> gamedata\configs\mod_system_shelter_lights.ltx, gamedata\configs\items\settings\mod_craft_shelter_lights.ltx,
#        gamedata\configs\text\<lang>\st_shelter_lights.xml, gamedata\textures\ui\shelter\lamp_icon.dds
import os
import sys

import numpy as np

import ogfview
import packs

GAMEDATA = packs.GAMEDATA
VISUAL = "dynamics\\light\\light_galogen_1_glass"
# what's made: section, materials (section, how many) twice
RECIPES = [
    ("shelter_item_lamp", ("prt_i_glass", 2), ("prt_i_copper", 3)),
    ("decor_light1", ("prt_i_glass", 1), ("prt_i_copper", 2)),
    ("decor_light2", ("prt_i_glass", 2), ("prt_i_copper", 3)),
    ("decor_light3", ("prt_i_glass", 1), ("prt_i_copper", 2)),
    ("decor_light4", ("prt_i_glass", 1), ("prt_i_copper", 1)),
    ("decor_light5", ("prt_i_glass", 3), ("prt_i_copper", 3)),
    ("decor_light6", ("prt_i_glass", 1), ("prt_i_copper", 2)),
    ("decor_light7", ("prt_i_glass", 1), ("prt_i_copper", 2)),
    ("device_gas_lamp", ("prt_i_glass", 1), ("prt_i_scrap", 2)),
    ("device_light_altar", ("prt_i_wood", 2), ("prt_i_scrap", 2)),
]
LTX = """; The shelter's own ceiling lamp: written by tools\\shelter\\lights_set.py. Its light is that of the shelter's lamps (a corridor's
; one, read in the game), set as it's placed (shelter_furniture.script); it needs the generator (shelter_power), F turns it off,
; it goes on the ceiling (hang_offset: how far its origin is under it; placeable_furniture.script turns it over).
[shelter_item_lamp]:tch_junk
class                   = II_ATTCH
kind                    = i_tool
visual                  = {visual}.ogf
description             = st_shelter_item_lamp_descr
inv_name                = st_shelter_item_lamp
inv_name_short          = st_shelter_item_lamp
icons_texture           = ui\\shelter\\lamp_icon
inv_grid_x              = 0
inv_grid_y              = 0
inv_grid_width          = 2
inv_grid_height         = 2
cost                    = 300
inv_weight              = 1.5
use1_functor            = placeable_furniture.place_item
use1_action_functor     = placeable_furniture.func_place_item
placeable_type          = light
placeable_section       = placeable_shelter_lamp
shelter_category        = light

[placeable_shelter_lamp]
class                   = SO_HLAMP
visual                  = {visual}
script_binding          = bind_light_furniture.init
ui_on_interaction       = ui_furniture_light.start_dialog
ui_on_simple_interaction = ui_furniture_light.toggle_light
fuel_duration           = 336
fuel_section            = batteries_dead
item_section            = shelter_item_lamp
light_section           = definition_shelter_lamp
placeable_type          = light
base_rotation           = 0
bounding_box_size       = 0.32, 1.24, 0.32
bounding_box_origin     = 0, 0.16, 0
snd_turn_on             = ambient\\special\\light_buzz_1
snd_turn_off            = ambient\\special\\light_sizzles_1
shelter_power           = true
hang_offset             = 0.08
ui_texture              = ui_inGame2_placeable_metal_torch

[definition_shelter_lamp]
type                    = 2
color                   = 1, 1, 1, 1
range                   = 8
cone_angle              = 2.0943949
main_bone               = bone_lamp
color_animator          = light\\light_galogen_idle
has_shadows             = true
"""
TEXTS = {
    "rus": {"st_shelter_craft_lights": "Освещение", "st_shelter_item_lamp": "Потолочная лампа убежища",
            "st_shelter_item_lamp_descr": "Такая же, как в комнатах убежища. Вешается на потолок, горит от генератора; F выключает."},
    "eng": {"st_shelter_craft_lights": "Lighting", "st_shelter_item_lamp": "The shelter's ceiling lamp",
            "st_shelter_item_lamp_descr": "The same as in the shelter's rooms. Goes on the ceiling, runs on the generator; F turns it off."},
}


def main():
    meshes_root, tex_roots = sys.argv[1], sys.argv[2:]
    meshes = ogfview.read_ogf(os.path.join(meshes_root, *VISUAL.split("\\")) + ".ogf")["meshes"]
    meshes = [dict(m, P=m["P"] * np.array([1, -1, 1]), I=m["I"][:, ::-1]) for m in meshes]  # as it hangs
    packs.icon_of(meshes, tex_roots).save(os.path.join(GAMEDATA, "textures", "ui", "shelter", "lamp_icon.dds"))
    with open(os.path.join(GAMEDATA, "configs", "mod_system_shelter_lights.ltx"), "w", encoding="cp1251", newline="\r\n") as f:
        f.write(LTX.format(visual=VISUAL))
    lines = ["; Lighting on the workbench: known from the start (tools\\shelter\\lights_set.py)", "[8]", "title = st_shelter_craft_lights"]
    for sec, (a, an), (b, bn) in RECIPES:
        lines.append(f"x_{sec} = 1, recipe_basic_0, {a},{an},{b},{bn}")
    with open(os.path.join(GAMEDATA, "configs", "items", "settings", "mod_craft_shelter_lights.ltx"), "w", encoding="cp1251", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    for lang, table in TEXTS.items():
        with open(os.path.join(GAMEDATA, "configs", "text", lang, "st_shelter_lights.xml"), "w", encoding="cp1251", newline="\r\n") as f:
            f.write('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n')
            for sid, text in table.items():
                f.write(f'\t<string id="{sid}">\n\t\t<text>{text}</text>\n\t</string>\n')
            f.write("</string_table>\n")


if __name__ == "__main__":
    main()
