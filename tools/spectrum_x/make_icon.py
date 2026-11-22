r"""Spectrum-X inventory icon: render_icon.py's PNG -> its own atlas gamedata/textures/ui/ui_icon_spectrum_x.dds
(uncompressed BGRA as tools/artifact_icons does; 50 px a grid cell, the item is 2x2 cells at 0,0).
python tools/spectrum_x/make_icon.py <icon_512.png> [--tools H:\stalker-test\tools-ext]"""
import os, sys, subprocess, shutil
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
src = sys.argv[1]
tools = sys.argv[sys.argv.index("--tools") + 1] if "--tools" in sys.argv else r"H:\stalker-test\tools-ext"
CELL, W, H = 50, 2, 2
icon = Image.open(src).convert("RGBA")
icon.thumbnail((CELL * W - 4, CELL * H - 4), Image.LANCZOS)
atlas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
atlas.alpha_composite(icon, ((CELL * W - icon.width) // 2, (CELL * H - icon.height) // 2))
work = os.path.dirname(os.path.abspath(src)); png = os.path.join(work, "ui_icon_spectrum_x.png"); atlas.save(png)
out = os.path.join(ROOT, "gamedata", "textures", "ui"); os.makedirs(out, exist_ok=True)
r = subprocess.run([os.path.join(tools, "texconv", "texconv.exe"), "-nologo", "-y", "-dx9", "-m", "1", "-f", "B8G8R8A8_UNORM",
                    "--ignore-srgb", "-o", work, png], capture_output=True, text=True)
if r.returncode: sys.exit(r.stdout + r.stderr)
shutil.move(os.path.join(work, "ui_icon_spectrum_x.dds"), os.path.join(out, "ui_icon_spectrum_x.dds"))
print(os.path.join(out, "ui_icon_spectrum_x.dds"))
