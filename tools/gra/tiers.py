"""Quality tiers by video memory: which of GRA's purely visual mods each tier gets (docs/coop/quality-tiers.md).
Data only; build_tiers.py merges the mods the way Mod Organizer does and cuts the result into components.

GRA's own presets are its Mod Organizer profiles «v_12gb», «v_6gb» and «v_4gb Средние»: one mod list, the same
order, a few mods switched. The tiers below are those three profiles, less everything that is not a picture
(scripts, configs, level geometry), less what the shader branch brings, and with the two things co-op cannot have
different from player to player made the same for all: level.details (grass hides from AI sight by it) and models.
"""

TIERS = [
    {"id": "low", "title": "4 ГБ", "vram_gb": [4, 5]},
    {"id": "mid", "title": "6–8 ГБ", "vram_gb": [6, 8]},
    {"id": "high", "title": "10–12 ГБ", "vram_gb": [10, 12]},
]
ALL = "low mid high"

# The mods in Mod Organizer's priority (GRA 2.5, the same in the three profiles), lowest first: a later mod's file wins.
# tiers: who gets the mod; group: the component its files shared by every tier go to (world, models, ui).
MODS = [
    # grass of the New Levels (grimwood, poselok_ug, promzona): level.details + build_details, the same for everyone
    {"mod": "[Локация] Gardener of the Zone", "tiers": ALL, "group": "world"},
    # models: bind poses, joints and some bone shapes differ from vanilla's, so one set for every player
    {"mod": "[Модели] Fixed_Vanilla_ModelsTextures (Light)", "tiers": ALL, "group": "models"},
    {"mod": "[Модели_в2] Мутанты KynesPeace (Medium)", "tiers": ALL, "group": "models"},  # GRA: 6 GB only
    {"mod": "[Модели] HD_Lurker (Medium)", "tiers": ALL, "group": "models"},
    {"mod": "[Модели] AltPseudogiants (Medium)", "tiers": ALL, "group": "models"},  # GRA: 12 and 6 GB
    {"mod": "[Модели] Izlom YuriVernadsky", "tiers": ALL, "group": "models"},
    # the world's textures
    {"mod": "[Ретекстур_в1] Optimized_Overhual_ATO 2к (Light)", "tiers": "low mid", "group": "world"},
    {"mod": "[Ретекстур_в2] Adega full retexture (Heavy)", "tiers": "high", "group": "world"},
    {"mod": "[Ретекстур_в2] DiolatorZoneTextures cv", "tiers": "mid high", "group": "world"},
    {"mod": "[Ретекстур_в2 и 1] Vehicle_Textures_Redux_v1.3.1", "tiers": ALL, "group": "world"},
    # grass and trees: its level.details keep vanilla's slots (the same AI sight as now), so it is the one for all;
    # GRA gives it to 4 GB only and ConsciousnessGrassTrees to the rest (see LEFT_OUT)
    {"mod": "[Трава_в3] PanceRide_Autumn_Opt (medium)", "tiers": ALL, "group": "world"},
    {"mod": "[Ретекстур_S] Misery Terrain Textures 2.8 up", "tiers": ALL, "group": "world"},
    {"mod": "[Ретекстур_в2] Штрих от Шабаша", "tiers": "mid high", "group": "world"},
    {"mod": "[Фикс] for Burnt Fuzz", "tiers": ALL, "group": "models"},
    # particles: one particles.xr replacing vanilla's (every vanilla name configs, scripts and gamemtl.xr use is in it)
    {"mod": "[Эффекты_в1] Cinem VFX 3.7 (Ex_Heavy)", "tiers": "mid high", "group": "world"},
    {"mod": "[Интерфейс] High_Resolution_PDA_Maps", "tiers": ALL, "group": "ui"},
    {"mod": "[Интерфейс] Viewport_Loading_Screens", "tiers": ALL, "group": "ui"},
]

# Paths these mods have are never packed: in GRA they stand above the mods here and their files win.
YIELD_TO = [
    # ours already (db\mods\gra_*.db, build_pack.py)
    "[Модели] Dux's Character Kit 2.0.7",
    "[Модели] FVM_Nosorog_Overhaul",
    # the shader and weather branch (gra-shaders) brings these with their textures
    "[Шейдеры] ScreenSpaceShaders 23.5",
    "[Погода] Atmospherics 2.68.93_h3",
    "[Частицы_в2 и 12] Enh_Shaders_Color_G 1.10",
]

# GRA's visual mods left out, and why (docs only; nothing reads it)
LEFT_OUT = {
    "[Трава_в1] ConsciousnessGrassTrees 0.71 (Heavy)": "its level.details change the grass slots on 21 levels: AI sight "
        "through grass (grass_occlusion.cpp) would differ between players; possible only for everyone and the host at once",
    "[Модели_в1] Мутанты S2 (Heavy)": "needs its creature configs and shaders; other bone shapes, three phantoms with other skeletons",
    "[Модели_в1] Мутанты KynesPeace (Heavy)": "the Medium set of the same models is the one for all",
    "[Текстуры_в0] HighResMutantsV (Light)": "textures for vanilla's mutant meshes, which KynesPeace replaces",
    "[Локация] Expanded_Fixed_Maps_AIO": "level geometry",
    "[Аномалии] Arrival +dmg fix (Heavy)": "anomalies: gameplay",
    "[Эффекты] Painter_of_the_Zone 21.02": "scripts, blood decals as items",
    "[Эффекты] Следы by Demonized": "scripts",
    "[Эффекты] Расчленение 0.81": "scripts, gameplay",
    "[Модели] Swm_Visible_Body": "scripts, the actor's body",
    "[Погода] Persistent Weather by Priler": "the host's weather is the world's",
}

# What a tier pack may hold; anything else in the mods (configs, scripts, desktop.ini) is left out and listed by `plan`.
ALLOWED_LEVEL_FILES = ("level.details", "build_details.dds", "build_details.thm")  # and terrain\*.dds

# Component ids by the tiers that use a file; a file every tier uses goes by its mod's group.
COMPONENTS = {
    "world": ("gfx_all", "Графика: земля, техника, трава и деревья"),
    "models": ("gfx_models", "Модели мутантов и сталкеров"),
    "ui": ("gfx_ui", "Карты КПК и экраны загрузки"),
    "low": ("gfx_low", "Текстуры мира 2K: только для 4 ГБ"),
    "low mid": ("gfx_low_mid", "Текстуры мира 2K (ATO)"),
    "mid": ("gfx_mid", "Текстуры мира: только для 6–8 ГБ"),
    "mid high": ("gfx_mid_high", "Текстуры мира ZTR и «Штрих», частицы Cinematic VFX"),
    "high": ("gfx_high", "Текстуры мира 4K (A.D.E.G.A.)"),
    "low high": ("gfx_low_high", "Текстуры мира: 4 ГБ и 10–12 ГБ"),
}

# The archives go to db\patches\: the engine reads it after db\mods\ (fsgame.ltx order, a later archive's file
# replaces an earlier one's in CLocatorAPI::Register), so a tier's texture wins over vanilla's, gra_*.db's and
# new_levels_textures.db's, as the retextures do in GRA. Loose gamedata still wins over any archive.
ARCHIVE_DIR = "db/patches"
