r"""The Grim Raid Addon's weapons, armour looks and hands (its Mod Organizer setup, X:\GRA2.5\MO2) brought into this
project without Mod Organizer: the mods merged as MO2 merges them (a later mod's file wins), then split. Configs,
scripts and shaders go into this repo's gamedata; meshes, textures, sounds and animations are packed into .db
archives kept outside git (the game loads them from db\mods\).
  build_pack.py manifest                 which mod gives each file, where it goes, what collides with the repo
  build_pack.py code                     copy the code part into gamedata (files the repo has already: tools\gra\merge),
                                         list it in the pack's file list, remove what an earlier run put there and is gone
  build_pack.py assets <stage> <out>     stage the assets under <stage>, pack them into <out>\gra_*.db
  build_pack.py header <out> [size]      rewrite the header of the archives in <out> (HEADER below), its size kept
  --pack <name> before the command: which pack (PACKS below), the weapons by default
"""
import os
import shutil
import struct
import subprocess
import sys

MO2 = r"X:\GRA2.5\MO2\mods"
CONVERTER = r"X:\Anomaly\tools\converter.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
MERGE_DIR = os.path.join(HERE, "merge")
ARCHIVE_SIZE = 1 << 30  # an archive's assets at most: the format's offsets are 32 bit, vanilla's run 0.5 GB

# the mods, in Mod Organizer's priority (the profile "1v2(DX11) (v_12gb) 2.5, Все включено (168)"), lowest first
MODS = [
    "[Руки] T.H.A.P. Rework 2.3.0 (Light)",  # hands per suit
    "[Руки] I.W.P. exos and animations",
    "[Геймплей] Навесные модули upgrade",  # armour inserts, artefact slots, camelbak
    "[Геймплей] Weapons & Helmets Parts demonized",
    "[Геймплей] GRA Armor Rebalance 1.2",
    "[Оружие] Anomaly_WPO_детали",  # weapon parts, jamming, overheating
    "[Оружие] RSH-12+",
    "[Оружие] RPG26_2.2.2.3",
    "[Оружие] Boomsticks_02-Oct-2022",  # BaS
    "[Оружие] BaS Patch 25-Oct-2022",
    "[Оружие] КС-23 фикс анимации",
    "[Оружие] Бинокль из Gunslinger",
    "[Баллистика] Grok's Ballistics System 1.7.1",
    "[Баллистика] Grok's Ballistics System + BaS",
    "[Баллистика] Enh_Recoil_Rev v4",
    "[Оружие] weap_inertia_exp_v Dec6",
    "[Оружие_S] TCO Kriss Vector v1.0 (3dss)",
    "[Геймплей_S] HeatVision_v1.3",
    "[Прицелы] Mark_switch_14",
    "[Прицелы 3д] Modular_Attachment_System 26.01",  # MAS
    "[Прицелы 3д] Shader_3d_Scopes v44",
    "[Оружие] MRAA_Reposition_base",
    "[Оружие] MRAA_Reposition_upd 3.9.4",
    "[Оружие_S] AShey 'n ShAKky (3dss)",
    "[Прицелы 3д] 3DSS MRAA 1.3",
    "[Прицелы 3д] MRAA_1_4_3DSS_Meshes",
    "[Прицелы 3д] 3DSS BaS",
    "[Фикс] Remove_BaS_Label v09.10",
    "[Прицелы 3д] MAS BaS",
    "[Прицелы 3д] MAS BaS 3DSS",
    "[Прицелы 3д] Pizza's Ultimate Sight 18.02",
    "[Оружие] Weapon_Cover_Tilt 15.1",
    "[Прицелы] Focused_Zoom_v0.41",
    "[Модели] Dux's Character Kit 2.0.7",  # NPCs' and suits' looks
    "[Модели] FVM_Nosorog_Overhaul",
    "[Графика_фикс] Overheat Gunsmoke by party_50",
    "[Звук] DLTX_JSRS",
    "[Интерфейс] Momopate's Detailed Weapon Stats",
    "[Интерфейс_детали] Parts_color_WPO",
    "[Интерфейс_детали] Parts_In_Tooltip_bas [🔗5]",
    "[Интерфейс] Shows_Part_Condition",
    "[Интерфейс] Inspect Weapons 1.9",
    "[Мод] Трассеры",
    "[Тех_настройки] Anomaly-MCM 1.7.2",  # the mods' settings menu: several of them call it unguarded
]
# single files taken from mods otherwise left out (GRA Bolt is the raid framework itself): GRA's final names and
# descriptions of the ammo
EXTRA = {
    "configs/text/eng/st_items_ammo.xml": "GRA Bolt",
    "configs/text/rus/st_items_ammo.xml": "GRA Bolt",
    "configs/text/eng/st_items_ammo_bas_eng.xml": "GRA Bolt",
    "configs/text/rus/st_items_ammo_bas_rus.xml": "GRA Bolt",
    # the helmets' balance, and the values of the head protection sections GRA Armor Rebalance's suits inherit
    "configs/mod_system_xraids_helmet.ltx": "GRA Bolt",
    # the traders' restock hook WPO's parts (wpo_loot) and Hideout Furniture's trade need; GRA's latest version
    "scripts/trader_autoinject.script": "[Геймплей] GRA бартер",
    # the new game screen: MCM's layout of it (GRA's) is drawn on UI Rework Sota's frames, buttons and checkboxes
    "configs/ui/textures_descr/z_ui_new_game.xml": "[Интерфейс_инвент] UI Rework Sota + Шабаш",
    **{f"textures/ui/new_game/{name}.dds": "[Интерфейс_инвент] UI Rework Sota + Шабаш"
       for name in ("ui_actor_icon_no_data", "ui_new_game_back_f", "ui_new_game_back_t", "ui_new_game_main",
                    "ui_new_game_maps_3", "ui_new_game_popup")},
    "textures/ui/ui_actor_multiplayer_game_menu.dds": "[Интерфейс_инвент] UI Rework Sota + Шабаш",
}


# GRA's sounds of a suit climbing a ledge: NPC Movement Sound (RMS) replaces Ledge Grabbing's own
MANTLING_SOUNDS = {f"sounds/ledge_grabbing/vaulting/{kind_}/{kind_}{n}.ogg": "[Шаги_в1] NPC Movement Sound [ RMS ]"
                   for kind_, count in (("exo", 3), ("heavy", 3), ("light", 3), ("medium", 3), ("naked", 2))
                   for n in range(1, count + 1)}


# GRA's look: its shader block, in Mod Organizer's priority (the same in the profiles 12 GB, 6 GB and 4 GB "Средние"),
# lowest first. A mod is added here only together with its files (one commit a mod)
GFX_MODS = [
    "[Частицы_в2 и 12] Enh_Shaders_Color_G 1.10",  # Enhanced Shaders and Color Grading: light, tonemapping, bloom
    "[ПНВ] Beefs_NVGs",  # Beef's shader based night vision
    "[Шейдеры] ScreenSpaceShaders 23.5",  # SSS update 23.5 (the archive of 2025-12-20)
    "[Погода] Atmospherics 2.68.93_h3",  # weathers, skies, suns; its settings of SSS. No scripts that drive the weather
    "[Эффект_в4] Emergent Zone 2 Flare",  # the colour table (LUT) GRA has on, of the Emergent Zone 2 pack's five
]
# left out of the look's mods
GFX_SKIP_PREFIX = ("scripts/orig/",)  # Beef's NVG: the mod's untouched copies
GFX_SKIP = {
    "scripts/item_device.script.bak",
    "scripts/raid_lamp_color_change.script",  # GRA's own, lying in its ScreenSpaceShaders folder: raid gameplay
}
GFX_EXTRA = {
    # Beef's own script: GRA's copy of it plays the goggles' animation through FDDA Redone (lam2), a mod not taken
    "scripts/z_beefs_nvgs.script": ("[ПНВ] Beefs_NVGs", "gamedata/scripts/orig/z_beefs_nvgs.script"),
}
# archives the mods bring ready made: copied next to the pack's own (the sounds of steps in the rain)
GFX_ARCHIVES = [("[Шейдеры] ScreenSpaceShaders 23.5", "db/mods/ssfx_rain_footsteps.db0")]


# the packs: each puts its code into gamedata, listed in its own file list (another pack's files count as the repo's:
# a file two packs have goes to tools\gra\merge), and its assets into <prefix>_*.db
PACKS = {
    "weapons": {"mods": MODS, "extra": EXTRA, "files": "pack_files.txt", "prefix": "gra"},
    # the shelter's furniture: placing, moving and picking up objects in a hideout
    "hf": {"mods": ["[Убежище] Hideout Furniture"], "extra": {}, "files": "pack_files_hf.txt", "prefix": "gra_hf"},
    # climbing onto ledges (demonized's Ledge Grabbing): its suit sounds as GRA has them (RMS's), its two shared scripts
    # left to the weapons pack (the same files), its 0.8 MB of assets in gamedata (no archive to hand round)
    "mantling": {"mods": ["[Паркур] Mantling v4.4"], "extra": MANTLING_SOUNDS, "files": "pack_files_mantling.txt",
                 "prefix": "gra_mantling", "assets_in_gamedata": True,
                 "skip": {"scripts/demonized_geometry_ray.script", "scripts/demonized_randomizing_functions.script",
                          "scripts/demonized_ledge_grabbing_animation_data_blender_script.py",  # Blender's, not the game's
                          "anims/camera_effects/climbing_in.anm"}},  # unused: a script moves the camera
    # GRA's look (docs/coop/graphics.md): shaders, weathers and their scripts into gamedata, skies and the other textures
    # and sounds into gra_gfx_*.db. The repo's own files the mods replace are merged by hand (tools/gra/merge)
    "gfx": {"mods": GFX_MODS, "extra": GFX_EXTRA, "files": "pack_files_gfx.txt", "prefix": "gra_gfx", "skip": GFX_SKIP,
            "skip_prefix": GFX_SKIP_PREFIX, "archives": GFX_ARCHIVES},
}
PACK = PACKS["weapons"]  # the one at work, --pack


def skipped(rel):
    """files of the taken mods left out"""
    return (rel in PACK.get("skip", ())
            or rel.startswith(PACK.get("skip_prefix", ("//",)))
            or rel.startswith("scripts/это что такое/")  # a stray copy of MRAA's scripts; the engine doesn't read subfolders
            or rel == "scripts/raid_auto_cmd_graphics_parametrs.script"  # GRA's: forces graphics settings every start
            or rel == "particles.xr"  # BaS's is the same as vanilla's
            or os.path.basename(rel).startswith("не нужно")  # GRA's way of turning a file off ("not needed")
            # the weapons pack only (the look's pack brings ScreenSpaceShaders' own depth_of_field.ps):
            or (PACK["prefix"] == "gra" and rel in INSPECT_DOF)  # Inspect Weapons' depth of field is ScreenSpaceShaders'; inspecting works
            or (PACK["prefix"] == "gra" and rel in IWP_FDDA))  # I.W.P.'s add-on to FDDA (not here): its exo hands stay


# Inspect Weapons' blur behind the weapon: built on ScreenSpaceShaders' headers, which this project hasn't
INSPECT_DOF = {"shaders/r3/depth_of_field.ps", "shaders/r3/post_processing.ps", "shaders/r3/betterbeefsnvg_ssfx_dof_nvg.h",
               "shaders/r3/inspectweapon_dof.h", "shaders/r3/inspectweapon_dof_defines.h", "shaders/r3/inspectweapon_dof_denoise.h",
               "shaders/r3/inspectweapon_dof_settings.h", "shaders/r3/inspectweapon_dof_utils.h"}
# I.W.P.'s exo medkit animation for FDDA, with its copy of FDDA's core script that reads FDDA's settings (crashes
# without them), and an r1 common.h this project doesn't need
IWP_FDDA = {"scripts/enhanced_animations.script", "configs/items/items/ea_addon_exo.ltx", "configs/items/items/items_anm_exo.ltx",
            "anims/itemuse_anm_effects/medkit_exo.anm", "meshes/anomaly_weapons/hud_hands_animation/medkitexohands.omf",
            "meshes/dynamics/weapons/wpn_eat/exo_anims/medkitexoobject.omf", "sounds/interface/item_usage/medkit_exo.ogg",
            "shaders/r1/shared/common.h"}


def kind(rel):
    top = rel.split("/", 1)[0]
    if top in ("configs", "scripts", "shaders"):
        return "code"
    if top in ("meshes", "textures", "sounds", "anims", "particles"):
        return "asset"
    return "other"


def manifest():
    """{gamedata path (lower case, /): (mod, real path)}, later mods winning"""
    files = {}
    for mod in PACK["mods"]:
        root = os.path.join(MO2, mod, "gamedata")
        assert os.path.isdir(root), root
        for dirpath, _, names in os.walk(root):
            for name in names:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/").lower()
                if not skipped(rel):
                    files[rel] = (mod, full)
    for rel, mod in PACK["extra"].items():
        if isinstance(mod, tuple):  # (mod, the file's path inside the mod): taken from another place than its own
            mod, source = mod
            full = os.path.join(MO2, mod, *source.split("/"))
        else:
            full = os.path.join(MO2, mod, "gamedata", *rel.split("/"))
        assert os.path.isfile(full), full
        files[rel] = (mod, full)
    return files


def pack_files_path():
    """the pack's code files `code` put into gamedata (gamedata paths)"""
    return os.path.join(HERE, PACK["files"])


def pack_files():
    if not os.path.isfile(pack_files_path()):
        return set()
    return {line.strip() for line in open(pack_files_path(), encoding="utf-8") if line.strip()}


def repo_files():
    """the repo's own gamedata files: tracked by git (or not yet), less those the pack put there (another pack's count)"""
    ours = pack_files()
    out = {}
    for dirpath, _, names in os.walk(REPO_GAMEDATA):
        for name in names:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, REPO_GAMEDATA).replace("\\", "/").lower()
            if rel not in ours:
                out[rel] = full
    return out


def cmd_manifest():
    files, repo = manifest(), repo_files()
    by_kind, size = {}, {}
    for rel, (mod, full) in files.items():
        k = kind(rel)
        by_kind[k] = by_kind.get(k, 0) + 1
        size[k] = size.get(k, 0) + os.path.getsize(full)
    for k in sorted(by_kind):
        print(f"{k}: {by_kind[k]} files, {size[k] / 2**30:.2f} GB")
    for rel in sorted(r for r in files if kind(r) == "other"):
        print("  other:", rel, "<-", files[rel][0])
    clash = sorted(r for r in files if kind(r) == "code" and r in repo)
    print("code the repo has already (merged by hand):", ", ".join(clash) or "none")


def cmd_code():
    files, repo = manifest(), repo_files()
    placed = set()
    in_gamedata = ("code", "asset") if PACK.get("assets_in_gamedata") else ("code",)
    for rel, (mod, full) in sorted(files.items()):
        if kind(rel) not in in_gamedata:
            continue
        if rel in repo:
            dest = os.path.join(MERGE_DIR, *rel.split("/"))  # the mod's version, next to the repo's, to merge
        else:
            dest = os.path.join(REPO_GAMEDATA, *rel.split("/"))
            placed.add(rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(full, dest)
    # files of an earlier build no longer in the pack
    stale = pack_files() - placed
    for rel in stale:
        path = os.path.join(REPO_GAMEDATA, *rel.split("/"))
        if os.path.isfile(path):
            os.remove(path)
    open(pack_files_path(), "w", encoding="utf-8", newline="\n").write("".join(f"{r}\n" for r in sorted(placed)))
    print(f"{len(placed)} files in gamedata, {len(files) - len(placed) - sum(kind(r) not in in_gamedata for r in files)} to merge "
          f"by hand (tools\\gra\\merge), {len(stale)} stale removed")


# as vanilla's: the engine asks every archive not open at the moment for its level_name and level_ver
HEADER = """[header]
auto_load = true
entry_point = $fs_root$\\gamedata\\
level_name = anomaly
level_ver = 1.8
"""


def write_header(db, size=None):
    """put HEADER into an archive already packed, as its first chunk. The archive's files are found by offsets from its
    start, so the header must stay the size it was packed with: padded with a comment to it. size: that size, when an
    earlier rewrite changed it (the files after it are moved back into place)"""
    head = HEADER.replace("\n", "\r\n").encode("cp1251")
    tmp = db + ".tmp"
    with open(db, "rb") as src, open(tmp, "wb") as dst:
        cid, old = struct.unpack("<II", src.read(8))
        assert cid == 666, (db, cid)
        size = size or old
        pad = size - len(head)
        assert pad == 0 or pad >= 3, (db, size, len(head))  # room for ";\r\n" at least
        if pad:
            head += b";" + b" " * (pad - 3) + b"\r\n"
        src.seek(old, 1)
        dst.write(struct.pack("<II", 666, len(head)) + head)
        shutil.copyfileobj(src, dst, 64 << 20)
    os.replace(tmp, db)


def cmd_assets(stage, out):
    files = manifest()
    assets = sorted((rel, full) for rel, (mod, full) in files.items() if kind(rel) == "asset")
    # archives by kind (meshes, textures, ...), each up to ARCHIVE_SIZE
    groups, current = [], None
    for rel, full in assets:
        top = rel.split("/", 1)[0]
        size = os.path.getsize(full)
        if current is None or current[0] != top or current[2] + size > ARCHIVE_SIZE:
            current = [top, [], 0]
            groups.append(current)
        current[1].append((rel, full))
        current[2] += size
    os.makedirs(out, exist_ok=True)
    header = os.path.join(stage, "header.ltx")
    os.makedirs(stage, exist_ok=True)
    open(header, "w", newline="\r\n").write(HEADER)
    counters = {}
    for top, items, size in groups:
        n = counters.get(top, 0)
        counters[top] = n + 1
        name = f"{PACK['prefix']}_{top}_{n:02d}"
        folder = os.path.join(stage, name)
        if os.path.isdir(folder):
            shutil.rmtree(folder)
        for rel, full in items:
            dest = os.path.join(folder, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(full, dest)
        db = os.path.join(out, name + ".db")
        print(f"{name}: {len(items)} files, {size / 2**20:.0f} MB -> {db}", flush=True)
        subprocess.run([CONVERTER, "-pack", folder, "-out", db, "-xdb", "-xdb_ud", header], check=True,
                       stdout=subprocess.DEVNULL)
        shutil.rmtree(folder)
    for mod, source in PACK.get("archives", ()):
        shutil.copyfile(os.path.join(MO2, mod, *source.split("/")), os.path.join(out, os.path.basename(source)))
        print("as it is:", os.path.basename(source), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--pack":
        PACK = PACKS[sys.argv[2]]
        del sys.argv[1:3]
    cmd = sys.argv[1] if len(sys.argv) > 1 else "manifest"
    if cmd == "manifest":
        cmd_manifest()
    elif cmd == "code":
        cmd_code()
    elif cmd == "assets":
        cmd_assets(sys.argv[2], sys.argv[3])
    elif cmd == "header":  # header <out> [the size it was packed with]
        for name in sorted(os.listdir(sys.argv[2])):
            if name.startswith("gra_") and name.endswith(".db"):
                write_header(os.path.join(sys.argv[2], name), int(sys.argv[3]) if len(sys.argv) > 3 else None)
                print("header:", name, flush=True)
    else:
        sys.exit(__doc__)
