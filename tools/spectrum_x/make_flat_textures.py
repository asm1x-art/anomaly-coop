"""Small textures of the Spectrum-X HUD model: the screen switched off (plain near-black glass, one flat colour; no
grid, no marks - the on-device interface draws over it later) and the coiled cable (black rubber).
python make_flat_textures.py <out_dir>"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
W = H = 512
# one flat colour: a gradient this dark bands into blue / green blotches once DXT1 (5:6:5) and the HUD's lighting have
# had it (in game the old diagonal "sheen" showed as big blue-green streaks). Any sheen comes from the engine's light.
a = np.zeros((H, W, 3), np.float32) + np.array((9, 10, 12), np.float32)[None, None, :]
im = Image.fromarray(a.clip(0, 255).astype(np.uint8))
im.save(os.path.join(out, "screen.png"))
rng = np.random.default_rng(1)
c = np.full((64, 64, 3), 22, np.float32) + rng.normal(0, 2.0, (64, 64, 1))
Image.fromarray(c.clip(0, 255).astype(np.uint8)).save(os.path.join(out, "cable.png"))
print("ok")
