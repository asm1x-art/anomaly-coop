# What the top floor's cleaning needs in place of the debris it takes (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Ярусы и лифт"): the debris hid a
# torn column and the gaps round a sagging slab of the ceiling, so a whole column goes round the one and a plate under the
# other.
#   top_patch.py   -> gamedata\meshes\dynamics\shelter\top_column.ogf, top_plate.ogf
import os

import numpy as np

import ogf

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata", "meshes", "dynamics", "shelter"))
COLUMN = dict(half=0.36, height=3.33)  # round the column at (2.215, 18.055), floor 19.35 to the ceiling 22.68
PLATE = dict(half_x=1.525, half_z=2.1, thick=0.36)  # under the slab, x 1.2..4.25, z 24.9..29.1, up to the ceiling: thin, its gaps show past it


def quad(corners, normal, tile):
    P = np.array(corners, dtype=float)
    lu, lv = np.linalg.norm(P[1] - P[0]) / tile, np.linalg.norm(P[3] - P[0]) / tile
    UV = np.array([[0, lv], [lu, lv], [lu, 0], [0, 0]], dtype=float)
    return P, np.tile(np.array(normal, dtype=float), (4, 1)), UV, np.array([[0, 1, 2], [0, 2, 3]])


def join(quads):
    Ps, Ns, UVs, Is, base = [], [], [], [], 0
    for P, N, UV, I in quads:
        Ps.append(P)
        Ns.append(N)
        UVs.append(UV)
        Is.append(I + base)
        base += len(P)
    return np.concatenate(Ps), np.concatenate(Ns), np.concatenate(UVs), np.concatenate(Is)


def column():
    a, h = COLUMN["half"], COLUMN["height"]
    sides = [
        quad([(-a, 0, -a), (a, 0, -a), (a, h, -a), (-a, h, -a)], (0, 0, -1), 2.0),
        quad([(a, 0, a), (-a, 0, a), (-a, h, a), (a, h, a)], (0, 0, 1), 2.0),
        quad([(-a, 0, a), (-a, 0, -a), (-a, h, -a), (-a, h, a)], (-1, 0, 0), 2.0),
        quad([(a, 0, -a), (a, 0, a), (a, h, a), (a, h, -a)], (1, 0, 0), 2.0),
    ]
    box = (np.array([0.0, h / 2, 0.0]), np.array([a, h / 2 - 0.05, a]), 200.0)
    return ogf.write(os.path.join(OUT, "top_column.ogf"), [("wall\\wall_stucco_04",) + join(sides)], [box], "shelter top column",
                     "objects\\small_box")


def plate():
    x, z, t = PLATE["half_x"], PLATE["half_z"], PLATE["thick"]
    faces = [
        quad([(-x, 0, -z), (x, 0, -z), (x, 0, z), (-x, 0, z)], (0, -1, 0), 2.0),
        quad([(-x, 0, -z), (x, 0, -z), (x, t, -z), (-x, t, -z)], (0, 0, -1), 2.0),
        quad([(x, 0, z), (-x, 0, z), (-x, t, z), (x, t, z)], (0, 0, 1), 2.0),
        quad([(-x, 0, z), (-x, 0, -z), (-x, t, -z), (-x, t, z)], (-1, 0, 0), 2.0),
        quad([(x, 0, -z), (x, 0, z), (x, t, z), (x, t, -z)], (1, 0, 0), 2.0),
    ]
    box = (np.array([0.0, t / 2, 0.0]), np.array([x, t / 2, z]), 100.0)
    return ogf.write(os.path.join(OUT, "top_plate.ogf"), [("wall\\wall_ceiling_01",) + join(faces)], [box], "shelter top plate",
                     "objects\\small_box")


print("column", column(), "plate", plate())
