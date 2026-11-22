"""Small textures of the Spectrum-X HUD model: the screen switched off (near-black glass, a faint diagonal sheen; no
grid, no marks - the on-device interface draws over it later) and the coiled cable (black rubber).
python make_flat_textures.py <out_dir>"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
W = H = 512
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
base = np.array((7, 9, 11), np.float32)
# a soft band of reflection across the glass (top left to bottom right) and a darker rim
t = (xx / W * 0.8 + yy / H * 0.55)
sheen = np.exp(-((t - 0.55) / 0.16) ** 2) * 7.0 + np.exp(-((t - 0.95) / 0.05) ** 2) * 3.0
r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
a = base[None, None, :] + sheen[..., None] * np.array((0.8, 0.9, 1.0))[None, None, :]
a *= (1.0 - 0.25 * np.clip(r - 0.7, 0, 1))[..., None]
im = Image.fromarray(a.clip(0, 255).astype(np.uint8))
im.save(os.path.join(out, "screen.png"))
rng = np.random.default_rng(1)
c = np.full((64, 64, 3), 22, np.float32) + rng.normal(0, 2.0, (64, 64, 1))
Image.fromarray(c.clip(0, 255).astype(np.uint8)).save(os.path.join(out, "cable.png"))
print("ok")
