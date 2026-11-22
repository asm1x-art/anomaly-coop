# Spectrum-X prototype pipeline, in order (Blender 4.5 portable with blender-xray; sources and work files in
# X:\coop\assets\spectrum-x, game files into this worktree's gamedata). Each step's script says more in its docstring.
set -e
B=/x/coop/yantar-tools/blender/blender-4.5.16-windows-x64/blender.exe
T=$(cd "$(dirname "$0")" && pwd); A=X:/coop/assets/spectrum-x; V=X:/coop/yantar-tools/work/gamedata/meshes
GD=$(cd "$T/../.." && pwd)/gamedata
# 1. retopology (Blender Decimate + Smart UV), the Tripo cable stubs cut off; the tablet stands tilted in Tripo's file
"$B" -b --factory-startup -P $T/retopo_blender.py -- $A/tripo/pistol_v31.glb $A/retopo/blender/pistol_low.blend --tris 12000 \
    --cut "-1 0.37 -1 1 1 1" --cut "-1 0.255 -1 1 1 0.12"
"$B" -b --factory-startup -P $T/retopo_blender.py -- $A/tripo/screen_v31_retex_text_style.glb $A/retopo/blender/tablet_low.blend \
    --tris 8000 --rot-y -9.66 --cut "0.285 -0.07 -1 1 0.07 1" --front-uv +z 2.0
# 2. the tablet's buttons and radiation sign: found on the high-poly's height map, drawn as a decal
"$B" -b --factory-startup -P $T/height_probe.py -- $A/tripo/screen_v31.glb $A/retopo/screen_height.npy -0.40 0.30 -0.25 0.25 4000 --rot-y -9.66
python $T/tablet_decal.py $A/retopo/screen_height.npy $A/retopo/screen_decal.png
# 3. bake high -> low (2K colour, normal, roughness)
"$B" -b $A/retopo/blender/pistol_low.blend -P $T/bake.py -- $A/bake/pistol_blender pistol --glb $A/bake/pistol_blender/pistol_blender.glb
"$B" -b $A/retopo/blender/tablet_low.blend -P $T/bake.py -- $A/bake/tablet_blender tablet --decal $A/retopo/screen_decal.png \
    --decal-box "+y -x -0.20 -0.20 0.20 -0.07" --decal-normal +z --glb $A/bake/tablet_blender/tablet_blender.glb
# 4. textures in X-Ray form (dds + bump pair + thm), screen / cable placeholders
python $T/make_flat_textures.py $A/hud/tex
python $T/make_xray_textures.py
# 5. HUD scene: hands animations (.omf), HUD and world models (.ogf), previews of the exported files
"$B" -b -P $T/build_hud.py -- --meshes $V --assets $A --out $GD
"$B" -b -P $T/preview_hud.py -- $V $GD $A/hud/previews spectrum_x_idle:0 spectrum_x_aim:0 spectrum_x_bore:45 spectrum_x_draw:0,8,16,22
# 6. inventory icon
"$B" -b $A/hud/spectrum_x_hud.blend -P $T/render_icon.py -- $A/hud/icon/icon_512.png
python $T/make_icon.py $A/hud/icon/icon_512.png
