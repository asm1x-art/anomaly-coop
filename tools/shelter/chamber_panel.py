# The synthesis chambers' panels (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Камеры синтеза"): an unseen model laid over a cell's panel on
# the entrance corridor's wall (its monitors and console, prop_komp over prop_pult5: 0.67 x 0.52 m), so that looking at
# the panel and pressing use reaches the chamber's object. A box for the collision just out of the wall; what's drawn
# is a speck inside the wall. The model's +z goes into the wall, its origin on the wall at the panel's centre.
#   chamber_panel.py   -> gamedata\meshes\dynamics\shelter\chamber_panel.ogf
import os

import numpy as np

import ogf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "meshes", "dynamics", "shelter", "chamber_panel.ogf"))

HALF = (0.36, 0.30, 0.025)  # the panel with a margin; its depth out of the wall
OUT_OF_WALL = 0.03  # the box's centre this far out of the wall (-z)
SPECK = 0.005  # the drawn quad's half size, 4 cm inside the wall

P = np.array([[-SPECK, -SPECK, 0.04], [SPECK, -SPECK, 0.04], [SPECK, SPECK, 0.04], [-SPECK, SPECK, 0.04]])
N = np.tile([0.0, 0.0, -1.0], (4, 1))
UV = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]])
I = np.array([[0, 2, 1], [0, 3, 2]])
size = ogf.write(OUT, [("mtl\\mtl_rja_01", P, N, UV, I)],
                 [(np.array([0.0, 0.0, -OUT_OF_WALL]), np.array(HALF), 10.0)], "shelter chamber panel", "objects\\large_metal_trash")
print(f"{OUT}: {size} bytes")
