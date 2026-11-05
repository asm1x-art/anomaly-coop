# The shelter's entrance (scripts\shelter_entrance.script): unseen models laid over the doors the levels already have,
# so that looking at a door and pressing use reaches the entrance's object (as chamber_panel.py does for the panels).
#   door_in:  bunker_a1, the metal door behind point 1 (x -7.93, z -28.05..-26.5, 3 m high)
#   door_out: l10_radar, the half-open gate at the end of the tunnel east of the concrete yard (x 654.7, z 180.8..183.8):
#             the box also fills the gap, so one doesn't walk into the dead end behind it
# A box for the collision just out of the wall; what's drawn is a speck inside the wall. The model's +z goes into the
# wall, its origin on the wall at the door's middle, on the floor.
#   entrance_door.py   -> gamedata\meshes\dynamics\shelter\entrance_door_in.ogf, entrance_door_out.ogf
import os

import numpy as np

import ogf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "meshes", "dynamics", "shelter"))

DOORS = {  # width, height, depth out of the wall (m)
    "entrance_door_in": (1.6, 2.7, 0.06),
    "entrance_door_out": (3.2, 3.4, 0.3),
}
SPECK = 0.005  # the drawn quad's half size, 4 cm inside the wall

P = np.array([[-SPECK, 1 - SPECK, 0.04], [SPECK, 1 - SPECK, 0.04], [SPECK, 1 + SPECK, 0.04], [-SPECK, 1 + SPECK, 0.04]])
N = np.tile([0.0, 0.0, -1.0], (4, 1))
UV = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]])
I = np.array([[0, 2, 1], [0, 3, 2]])
for name, (w, h, d) in DOORS.items():
    path = os.path.join(OUT, name + ".ogf")
    size = ogf.write(path, [("mtl\\mtl_rja_01", P, N, UV, I)],
                     [(np.array([0.0, h / 2, -d / 2]), np.array([w / 2, h / 2, d / 2]), 10.0)], "shelter " + name,
                     "objects\\large_metal_trash")
    print(f"{path}: {size} bytes")
