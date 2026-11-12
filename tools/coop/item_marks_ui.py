# The lock in the corner of a pinned thing's inventory cell (gamedata/scripts/item_marks.script, texture id
# ui_item_marks_pin in configs/ui/textures_descr/ui_item_marks.xml): a light padlock with a dark rim, readable on
# any icon. Drawn four times over and scaled down. Our own drawing.
#   python tools\coop\item_marks_ui.py   -> gamedata\textures\ui\coop\item_pin.dds
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "textures", "ui", "coop"))
SIZE = 32
SS = 4


def lock():
    n = SIZE * SS
    k = n / 32.0
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rim = (20, 18, 16, 235)
    body = (236, 226, 200, 255)
    # the shackle: a dark arc under a light one
    d.arc([9 * k, 2 * k, 23 * k, 18 * k], 180, 360, fill=rim, width=int(6 * k))
    d.line([9 * k + 3 * k, 10 * k, 9 * k + 3 * k, 15 * k], fill=rim, width=int(6 * k))
    d.line([23 * k - 3 * k, 10 * k, 23 * k - 3 * k, 15 * k], fill=rim, width=int(6 * k))
    d.arc([10.5 * k, 3.5 * k, 21.5 * k, 16.5 * k], 180, 360, fill=body, width=int(3 * k))
    d.line([12 * k, 10 * k, 12 * k, 15 * k], fill=body, width=int(3 * k))
    d.line([20 * k, 10 * k, 20 * k, 15 * k], fill=body, width=int(3 * k))
    # the body with its keyhole
    d.rounded_rectangle([4 * k, 13 * k, 28 * k, 31 * k], radius=4 * k, fill=rim)
    d.rounded_rectangle([6 * k, 15 * k, 26 * k, 29 * k], radius=3 * k, fill=body)
    d.ellipse([14 * k, 18 * k, 18 * k, 22 * k], fill=rim)
    d.rectangle([15 * k, 21 * k, 17 * k, 26 * k], fill=rim)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "item_pin.dds")
    lock().save(path)  # plain RGBA, as our other UI art
    print(path)
