# The quick item wheel's own art (gamedata/scripts/ui_quick_wheel.script): only the mark of a player's own set (a
# star), a white line icon as the co-op wheel's (wheel_ui.py), tinted grey or amber by the script. The rest of the
# wheel is the game's textures, the co-op wheel's discs and the items' own icons. Drawn four times over and scaled
# down, so the edges are smooth. Our own drawing, no assets of other games.
#   python tools\coop\quick_wheel_ui.py   -> gamedata\textures\ui\coop\qwheel_set.dds
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "coop"))
SS = 4
SIZE = 64
INK = (255, 255, 255, 255)


def star():
    n = SIZE * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    c = n / 2
    outer, inner = 27 * SS, 11.5 * SS
    pts = []
    for i in range(10):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((c + r * math.cos(a), c + 1.5 * SS + r * math.sin(a)))
    d = ImageDraw.Draw(img)
    d.line(pts + [pts[0], pts[1]], fill=INK, width=int(4.5 * SS), joint="curve")
    return img.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    path = os.path.join(OUT, "qwheel_set.dds")
    star().save(path)  # plain RGBA, as the co-op wheel's icons
    print(path)
