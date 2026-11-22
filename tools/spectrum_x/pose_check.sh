# Spectrum-X look check of the tablet and the grips, before the animations are rebuilt: the landscape tablet
# (make_tablet.py), three still poses (build_hud.py --poses: one-hand hold, profile switch = thumb on P1, two-hand
# menu hold), the intersection check with both arms models (the default gloves and the exoskeleton's thick sleeves),
# previews at both HUD fovs (0.45 = the game's default console value here, 0.64 = the engine's default) and close-ups.
# Nothing goes into the game's gamedata: the poses are exported into $O.
#   bash tools/spectrum_x/pose_check.sh [--no-tablet]
set -e
B=/x/coop/yantar-tools/blender/blender-4.5.16-windows-x64/blender.exe
T=$(cd "$(dirname "$0")" && pwd); A=X:/coop/assets/spectrum-x; V=X:/coop/yantar-tools/work/gamedata/meshes
O=$A/hud/redesign_out; P=$A/hud/previews/redesign; mkdir -p $O $P/frames $P/model
[ "$1" = --no-tablet ] || "$B" -b --factory-startup -P $T/make_tablet.py -- $A/bake/tablet_v2 | grep "LOW tris"
"$B" -b $A/bake/tablet_v2/tablet_bake.blend -P $T/render_tablet.py -- $P/model/tablet_model.png > /dev/null
"$B" -b -P $T/build_hud.py -- --meshes $V --assets $A --out $O --poses > $O/build.log 2>&1
grep "FIT\|GRIP\|TWO-HAND" $O/build.log
for h in wpn_hand_01 wpn_hand_exo; do
  "$B" -b -P $T/check_hud.py -- $V $O $P/check_$h.txt --hands $h.ogf > /dev/null 2>&1
  echo "== $h"; sed -n '/PROBLEMS/,$p' $P/check_$h.txt
  for fov in 0.45 0.64; do
    "$B" -b -P $T/preview_hud.py -- $V $O $P/frames spectrum_x_pose_hold:0 spectrum_x_pose_switch:0 spectrum_x_pose_menu:0 \
      --res 1280x720 --fov $fov --hands $h.ogf --tag "${h}_fov${fov}_" > /dev/null 2>&1
  done
  # close-ups (HUD camera space): the thumb on P1, the left grip from below, the menu's fingers from behind
  for c in "thumb:spectrum_x_pose_switch:-0.03,0.32,0.03,-0.13,0.47,-0.06,30" "hold_back:spectrum_x_pose_hold:-0.05,0.75,0.05,-0.10,0.47,-0.06,35" "menu_front:spectrum_x_pose_menu:-0.05,0.18,0.0,-0.08,0.34,-0.06,40" \
           "menu_behind:spectrum_x_pose_menu:-0.12,0.62,0.02,-0.06,0.34,-0.05,35" "menu_under:spectrum_x_pose_menu:0.0,0.25,-0.45,0.0,0.30,-0.15,50"; do
    IFS=: read n m cam <<< "$c"
    "$B" -b -P $T/preview_hud.py -- $V $O $P/frames $m:0 --res 960x720 --cam $cam --hands $h.ogf --tag "${h}_cu_${n}_" > /dev/null 2>&1
  done
done
python - "$P" <<'EOF'
import sys, os
from PIL import Image, ImageDraw
P = sys.argv[1]; F = os.path.join(P, "frames")
def lab(im, t):
    d = ImageDraw.Draw(im); d.rectangle((0, 0, 9 * len(t) + 10, 22), fill=(0, 0, 0)); d.text((5, 5), t, fill=(255, 255, 255)); return im
for h in ("wpn_hand_01", "wpn_hand_exo"):
    for fov in ("0.45", "0.64"):
        ims = [lab(Image.open(os.path.join(F, "%s_fov%s_spectrum_x_pose_%s_000.png" % (h, fov, p))).convert("RGB"), "%s  hud_fov %s  %s" % (h, fov, p))
               for p in ("hold", "switch", "menu")]
        S = Image.new("RGB", (1280 * 2, 720 * 2), (40, 40, 40))
        for i, im in enumerate(ims): S.paste(im, ((i % 2) * 1280, (i // 2) * 720))
        cu = [lab(Image.open(os.path.join(F, "%s_cu_%s_spectrum_x_pose_%s_000.png" % (h, n, m))).convert("RGB").resize((480, 360)), n)
              for n, m in (("thumb", "switch"), ("hold_back", "hold"), ("menu_front", "menu"), ("menu_behind", "menu"))]
        for i, im in enumerate(cu): S.paste(im, (1280 + (i % 2) * 640 + 80, 720 + (i // 2) * 360))
        S.save(os.path.join(P, "poses_%s_fov%s.png" % (h.replace("wpn_hand_", "arms_"), fov)))
print("sheets in", P)
EOF
