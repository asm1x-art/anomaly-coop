# Spectrum-X prototype pipeline, in order (Blender 4.5 portable with blender-xray; sources and work files in
# X:\coop\assets\spectrum-x, game files into this worktree's gamedata). Each step's script says more in its docstring.
set -e
B=/x/coop/yantar-tools/blender/blender-4.5.16-windows-x64/blender.exe
T=$(cd "$(dirname "$0")" && pwd); A=X:/coop/assets/spectrum-x; V=X:/coop/yantar-tools/work/gamedata/meshes
GD=$(cd "$T/../.." && pwd)/gamedata
# 1. the probe: retopology (Blender Decimate + Smart UV), the Tripo cable stubs cut off
"$B" -b --factory-startup -P $T/retopo_blender.py -- $A/tripo/pistol_v31.glb $A/retopo/blender/pistol_low.blend --tris 12000 \
    --cut "-1 0.37 -1 1 1 1" --cut "-1 0.255 -1 1 1 0.12"
# 2. the tablet: the landscape rugged tablet modelled and baked by script (make_tablet.py, prints by tablet_prints.py).
#    The first prototype's Tripo tablet went through retopo_blender.py + height_probe.py + tablet_decal.py + bake.py.
"$B" -b --factory-startup -P $T/make_tablet.py -- $A/bake/tablet_v2
# 3. bake high -> low (2K colour, normal, roughness)
"$B" -b $A/retopo/blender/pistol_low.blend -P $T/bake.py -- $A/bake/pistol_blender pistol --glb $A/bake/pistol_blender/pistol_blender.glb
# (look check of the tablet and the grips before the animations: tools/spectrum_x/pose_check.sh, nothing into gamedata)
# 4. textures in X-Ray form (dds + bump pair + thm), screen / cable placeholders; the 3D screen's glyph atlas
python $T/make_flat_textures.py $A/hud/tex
python $T/make_xray_textures.py
python $T/make_screen_atlas.py
# 5. HUD scene: grips solved on the meshes, animations (hud_anims.py, IK in hud_rig.py), the cable's bone chain, export;
#    the measured numbers into the .ltx; every frame checked for intersections; previews of the exported files
"$B" -b -P $T/build_hud.py -- --meshes $V --assets $A --out $GD
python $T/apply_numbers.py --assets $A
"$B" -b -P $T/check_hud.py -- $V $GD $A/hud/previews/check_report.txt
"$B" -b -P $T/preview_hud.py -- $V $GD $A/hud/previews/frames --ui $A/hud/tex/ui_mock_panel.png --res 640x360     spectrum_x_idle:0 spectrum_x_aim:30 spectrum_x_bore:44 spectrum_x_menu_idle:45 spectrum_x_switch:7 spectrum_x_draw:0,8,12,24
# 6. inventory icon
"$B" -b $A/hud/spectrum_x_hud.blend -P $T/render_icon.py -- $A/hud/icon/icon_512.png
python $T/make_icon.py $A/hud/icon/icon_512.png
