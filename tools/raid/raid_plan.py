r"""A plan for the raid app of a level with no PDA map (the Sarcophagus): its AI map seen from above, each floor (a band
of heights) in a shade of the laptop's colours, the higher over the lower, every floor's edges drawn over all, so a
lower floor still shows under a higher one. North up, as the PDA's maps.
  raid_plan.py <levels dir> <level> [<px per metre>]
Writes gamedata\textures\ui\raid\plan_<level>.dds (DXT1) and prints the line for [raid_plans] in mod_system_raid.ltx:
"<level> = ui\raid\plan_<level> | x1, z1, x2, z2" (the world's box the texture spans).
"""
import os
import sys

import numpy as np
from PIL import Image

from raid_posts import nodes_of

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
CELL = 0.7  # the AI map's node size (m)
MARGIN = 4.0  # metres round the nodes
BG = (19, 21, 25)
# floors (lowest first): from this height up, fill and edge colours
FLOORS = [(-1e9, (38, 52, 58), (90, 130, 140)), (10.0, (40, 66, 70), (110, 180, 170)), (30.0, (52, 92, 88), (176, 214, 206))]


def main():
    levels, level = sys.argv[1], sys.argv[2]
    s = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    nodes = np.array([p for _, p in nodes_of(levels, level)])
    x1, z1 = nodes[:, 0].min() - MARGIN, nodes[:, 2].min() - MARGIN
    x2, z2 = nodes[:, 0].max() + MARGIN, nodes[:, 2].max() + MARGIN
    w, h = int(np.ceil((x2 - x1) * s / 4)) * 4, int(np.ceil((z2 - z1) * s / 4)) * 4  # DXT: blocks of 4
    x2, z1 = x1 + w / s, z2 - h / s
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = BG
    edges = []
    for i, (lo, fill, edge) in enumerate(FLOORS):
        hi = FLOORS[i + 1][0] if i + 1 < len(FLOORS) else 1e9
        band = nodes[(nodes[:, 1] >= lo) & (nodes[:, 1] < hi)]
        mask = np.zeros((h, w), bool)
        for x, _, z in band:
            c0, c1 = int((x - CELL / 2 - x1) * s), int(np.ceil((x + CELL / 2 - x1) * s))
            r0, r1 = int((z2 - z - CELL / 2) * s), int(np.ceil((z2 - z + CELL / 2) * s))
            mask[max(0, r0):r1, max(0, c0):c1] = True
        img[mask] = fill
        inner = mask.copy()
        inner[1:, :] &= mask[:-1, :]
        inner[:-1, :] &= mask[1:, :]
        inner[:, 1:] &= mask[:, :-1]
        inner[:, :-1] &= mask[:, 1:]
        edges.append((mask & ~inner, edge))
    for e, color in edges:
        img[e] = color
    out = os.path.join(GAMEDATA, "textures", "ui", "raid", "plan_%s.dds" % level)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    Image.fromarray(img, "RGB").save(out, pixel_format="DXT1")
    print(out, (w, h))
    print("%s = ui\\raid\\plan_%s | %.1f, %.1f, %.1f, %.1f" % (level, level, x1, z1, x2, z2))


if __name__ == "__main__":
    main()
