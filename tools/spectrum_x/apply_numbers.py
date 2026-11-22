"""Write build_hud.py's measured numbers (<assets>\hud\build_numbers.json) into configs/mod_system_spectrum_x.ltx:
custom_ui_pos / custom_ui_rot (the 3D screen on the tablet bone), screen_size and menu_screen_corners.
  python tools/spectrum_x/apply_numbers.py [--assets X:\coop\assets\spectrum-x]"""
import json, os, re, sys
A = sys.argv[sys.argv.index("--assets") + 1] if "--assets" in sys.argv else r"X:\coop\assets\spectrum-x"
N = json.load(open(os.path.join(A, "hud", "build_numbers.json")))
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gamedata", "configs", "mod_system_spectrum_x.ltx")
b = open(p, "rb").read()
vals = {"custom_ui_pos": ", ".join("%.6f" % x for x in N["custom_ui_pos"]),
        "custom_ui_rot": ", ".join("%.3f" % x for x in N["custom_ui_rot"]),
        "screen_size": ", ".join("%.4f" % x for x in N["screen_size"]),
        "menu_screen_corners": ", ".join("%.4f" % x for x in N["menu_screen_corners"])}
for k, v in vals.items():
    b, n = re.subn(rb"(?m)^(" + k.encode() + rb"\s*=\s*)[-0-9., ]+?(\s*(;|\r?$))", lambda m: m.group(1) + v.encode() + m.group(2), b)
    print(k, "=", v, "(%d line)" % n)
open(p, "wb").write(b)
