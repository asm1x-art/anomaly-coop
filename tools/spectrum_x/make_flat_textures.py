"""Small textures of the Spectrum-X HUD model: the screen placeholder (dark, faint grid; the UI goes there later)
and the coiled cable (black rubber). python make_flat_textures.py <out_dir>"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
W = H = 512
im = Image.new("RGB", (W, H), (14, 20, 30)); d = ImageDraw.Draw(im)
# soft vignette
a = np.asarray(im).astype(np.float32); yy, xx = np.mgrid[0:H, 0:W]
r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)); a *= (1.0 - 0.35 * np.clip(r - 0.4, 0, 1))[..., None]
im = Image.fromarray(a.clip(0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
for k in range(1, 8):
    c = (30, 48, 62) if k % 2 else (40, 64, 82)
    d.line((k * W // 8, 0, k * W // 8, H), fill=c, width=1); d.line((0, k * H // 8, W, k * H // 8), fill=c, width=1)
im.save(os.path.join(out, "screen.png"))
rng = np.random.default_rng(1)
c = np.full((64, 64, 3), 22, np.float32) + rng.normal(0, 2.0, (64, 64, 1))
Image.fromarray(c.clip(0, 255).astype(np.uint8)).save(os.path.join(out, "cable.png"))
print("ok")
