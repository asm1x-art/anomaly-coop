# The shelter's movable props (docs/coop/shelter.md, "Мебель"): bunker_a1's static furniture and clutter cut out of the
# level into objects Hideout Furniture places, picks up and moves. The visuals are cut into pieces (their connected
# parts: the compiler merged a material's objects into one visual and splits an object by material), and the pieces
# are put together into objects: touching pieces of one family of textures (a table's planks, legs and top; a crate's
# boards; a rack's posts and shelves). A whole crate (one closed piece) takes nothing but small things (the boxes on
# it), so stacked crates stay apart.
# Each object gets its own frame (its footprint's smallest rectangle: the longer side along x, the origin at its middle
# on its bottom); objects alike in that frame (turned round too) share a model.
#   props.py plan <level dir> <out.png> <x0 x1 z0 z1>   the objects of VISUALS in the box, listed and drawn from above
#   props.py build <level dir>                          the models (meshes\dynamics\shelter\props), their sections
#                                                      (configs\mod_system_shelter_props.ltx) and where they stand,
#                                                      what of the level they replace (configs\scripts\shelter\props.ltx)
import math
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import ConvexHull

import ogf
from levelgeom import Geom
from levelvis import level

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))

# the visuals turned into props (all their pieces: a visual is hidden whole)
VISUALS = [
    # wood: tables, crates, boards
    437, 438, 439, 440, 441, 442, 443, 449, 450, 452, 453, 454, 455, 456, 457, 458, 459, 461, 462, 463, 465, 468, 489, 490,
    492, 493, 494, 495, 496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506, 507, 508, 509,
    # metal racks, the small boxes on things
    428, 429, 430, 431, 432, 433, 434, 435, 445, 446, 447, 448, 466, 467, 444, 460, 464, 491,
    # barrels, the doors lying in the hall
    56, 282, 544, 545,
    # the top floor's ventilation ducts lying about, with their grilles
    60, 526, 527,
]  # not the cabins' desks (518-520): the laptop and the stash are on and under them; not 331, 332 (mtl_bochka_05a: the
#    bolts of the south hall's frames)
# textures whose pieces may make one object together
FAMILIES = [
    {"wood\\wood_table_01", "wood\\wood_table_02", "wood\\wood_table_03"},
    {"wood\\wood_walls8", "wood\\wood_old"},
    {"wood\\wood_fence_01", "wood\\wood_jasik", "prop\\prop_dangerbox", "wood\\wood_old"},
    {"mtl\\mtl_kreplen_pod_01", "mtl\\mtl_angar_a_b"},
    {"wood\\wood_board_01"},
    {"wood\\wood_collect"},
    {"door\\door_white_02", "door\\door_white_04"},
    {"mtl\\mtl_barrel_01"}, {"mtl\\mtl_bochka_03_r"},
    {"mtl\\mtl_tubes3b", "prop\\prop_grate_01"},
]
WHOLE = ({"wood\\wood_fence_01", "wood\\wood_jasik"}, 100)  # a crate in one piece: its textures, triangles at least
SMALL = 0.2  # a piece no bigger than this (m) is a small thing on something
TOUCH = 0.015  # pieces whose bounds come this close touch
# things of these textures that touch one another (stacked pallets, tables on them): split at their bodies (the pieces
# of this many triangles at least), each other piece to the nearest body (its height counting double)
SEEDED = ({"wood\\wood_board_01"}, 90)
# wood_board_01's things by their body's triangles: a pallet (deck, boards, blocks), a tall crate; the rest are tables
BOARD_KINDS = {92: "pallet", 143: "crate"}

# kinds of props: their name (text id), icon (Hideout Furniture's: texture, x, y, w, h), physics material, mass
KINDS = {
    "table": ("st_shelter_prop_table", ("ui\\ui_maid_efp_props", 4, 4, 3, 3), "objects\\large_furniture", 25),
    "crate": ("st_shelter_prop_crate", ("ui\\ui_decor", 2, 8, 2, 2), "objects\\large_furniture", 20),
    "rack": ("st_shelter_prop_rack", ("ui\\ui_decor", 18, 0, 2, 3), "objects\\large_metal_trash", 30),
    "boards": ("st_shelter_prop_boards", ("ui\\ui_decor", 3, 0, 4, 2), "objects\\large_furniture", 8),
    "barrel": ("st_shelter_item_barrel", ("ui\\ui_decor", 5, 2, 1, 2), "objects\\barrel", 30),
    "door": ("st_shelter_prop_door", ("ui\\ui_doors", 2, 0, 2, 3), "objects\\large_furniture", 25),
    "pallet": ("st_shelter_prop_pallet", ("ui\\ui_decor", 3, 0, 4, 2), "objects\\large_furniture", 15),
    "duct": ("st_shelter_prop_duct", ("ui\\ui_decor", 18, 0, 2, 3), "objects\\large_metal_trash", 12),
}


class Piece:
    def __init__(self, n, visual, texture, P, N, UV, I):
        self.n, self.visual, self.texture = n, visual, texture
        self.P, self.N, self.UV, self.I = P, N, UV, I  # its own vertices and triangles
        self.lo, self.hi = P.min(0), P.max(0)
        self.whole = texture in WHOLE[0] and len(I) >= WHOLE[1]
        self.small = float((self.hi - self.lo).max()) <= SMALL


def pieces_of(P, N, UV, I):
    """the connected parts of a mesh, vertices welded by position (a millimetre)"""
    key = {}
    weld = np.array([key.setdefault(tuple(k), len(key)) for k in np.round(P * 1000).astype(np.int64)])
    parent = list(range(len(key)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for t in weld[I]:
        a = find(t[0])
        for b in t[1:]:
            b = find(b)
            if a != b:
                parent[b] = a
    root = np.array([find(weld[t[0]]) for t in I])
    for r in np.unique(root):
        tris = I[root == r]
        used = np.unique(tris)
        remap = np.full(len(P), -1)
        remap[used] = np.arange(len(used))
        yield P[used], N[used], UV[used], remap[tris]


def load(level_dir, ids):
    d, shaders, visuals = level(level_dir)
    g = Geom(level_dir + "/level.geom")
    out = []
    for v in ids:
        texture = shaders[visuals[v]["shader"]].split("/")[-1].split(",")[0]
        for P, N, UV, I in pieces_of(*g.mesh(d, visuals[v])):
            out.append(Piece(len(out) + 1, v, texture, P, N, UV, I))
    return out, (d, visuals, g)


def touch(a, b):
    return bool(np.all(a.lo - TOUCH <= b.hi) and np.all(b.lo - TOUCH <= a.hi))


def assemble(pieces):
    """the pieces put together into objects: lists of pieces"""
    groups = [[p] for p in pieces]
    owner = {p.n: i for i, p in enumerate(pieces)}

    def may_join(ga, gb):
        if not any(any(pa.texture in f and pb.texture in f for f in FAMILIES) for pa in ga for pb in gb):
            return False
        wa, wb = any(p.whole for p in ga), any(p.whole for p in gb)
        if wa and wb:
            return False
        if wa or wb:  # a whole crate takes small things only
            return all(p.small for p in (gb if wa else ga))
        return True

    changed = True
    while changed:
        changed = False
        for a in pieces:
            for b in pieces:
                ga, gb = owner[a.n], owner[b.n]
                if ga == gb or not touch(a, b) or not may_join(groups[ga], groups[gb]):
                    continue
                for p in groups[gb]:
                    owner[p.n] = ga
                groups[ga] += groups[gb]
                groups[gb] = []
                changed = True
    out = []
    for g in groups:
        bodies = [p for p in g if p.texture in SEEDED[0] and len(p.I) >= SEEDED[1]]
        if len(bodies) < 2:
            if g:
                out.append(g)
            continue
        parts = {b.n: [b] for b in bodies}
        centre = lambda p: (p.lo + p.hi) / 2 * [1, 2, 1]  # noqa: E731
        for p in g:
            if p.n not in parts:
                nearest = min(bodies, key=lambda b: np.linalg.norm(centre(p) - centre(b)))
                parts[nearest.n].append(p)
        out += parts.values()
    return out


def kind_of(obj):
    textures = {p.texture for p in obj}
    if textures == {"wood\\wood_board_01"}:
        return BOARD_KINDS.get(max(len(p.I) for p in obj), "table")
    if textures & FAMILIES[0] or "wood\\wood_walls8" in textures:
        return "table"
    if textures & FAMILIES[3]:
        return "rack"
    if textures & {"wood\\wood_fence_01", "wood\\wood_jasik"}:
        return "crate"
    if textures & {"mtl\\mtl_barrel_01", "mtl\\mtl_bochka_03_r"}:
        return "barrel"
    if textures & {"door\\door_white_02", "door\\door_white_04"}:
        return "door"
    if "mtl\\mtl_tubes3b" in textures:
        return "duct"
    return "boards"


def frame(obj):
    """the object's heading (the engine's: local x = (cos h, 0, sin h), z = (-sin h, 0, cos h)) and origin: its
    footprint's smallest rectangle, the longer side along x, the origin at its middle on the object's bottom"""
    P = np.concatenate([p.P for p in obj])
    xz = P[:, [0, 2]]
    hull = xz[ConvexHull(xz).vertices]
    best = None
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        a = math.atan2(e[1], e[0])
        c, s = math.cos(a), math.sin(a)
        u, v = hull @ [c, s], hull @ [-s, c]
        area = (u.max() - u.min()) * (v.max() - v.min())
        if best is None or area < best[0]:
            best = (area, a, u, v)
    _, a, u, v = best
    if v.max() - v.min() > u.max() - u.min():  # the longer side along x
        a += math.pi / 2
        u, v = v, -u
    c, s = math.cos(a), math.sin(a)
    mid = np.array([(u.max() + u.min()) / 2, (v.max() + v.min()) / 2])
    centre = mid[0] * np.array([c, s]) + mid[1] * np.array([-s, c])
    origin = np.array([centre[0], P[:, 1].min(), centre[1]])
    # x along (c, s) in (x, z), which is the engine's heading a (checked in the game: a prop's footprint on its original)
    return a, origin


def to_local(P, h, origin):
    c, s = math.cos(h), math.sin(h)
    w = P - origin
    return np.stack([w[:, 0] * c + w[:, 2] * s, w[:, 1], -w[:, 0] * s + w[:, 2] * c], 1)


def to_local_dir(N, h):
    c, s = math.cos(h), math.sin(h)
    return np.stack([N[:, 0] * c + N[:, 2] * s, N[:, 1], -N[:, 0] * s + N[:, 2] * c], 1)


def meshes_of(obj, h, origin):
    """its pieces in its frame, one mesh per texture: (texture, P, N, UV, I)"""
    out = {}
    for p in obj:
        m = out.setdefault(p.texture, [[], [], [], [], 0])
        m[0].append(to_local(p.P, h, origin))
        m[1].append(to_local_dir(p.N, h))
        m[2].append(p.UV)
        m[3].append(p.I + m[4])
        m[4] += len(p.P)
    return [(t, np.concatenate(m[0]), np.concatenate(m[1]), np.concatenate(m[2]), np.concatenate(m[3]))
            for t, m in sorted(out.items())]


def signature(meshes):
    """the shape in its frame, a centimetre's precision"""
    return tuple((t, tuple(sorted(map(tuple, np.round(P, 2).tolist())))) for t, P, *_ in meshes)


def turned(meshes):
    """the same, turned half round"""
    return [(t, P * [-1, 1, -1], N * [-1, 1, -1], UV, I) for t, P, N, UV, I in meshes]


def collision(d, visuals, g, cform, ids, eps=0.015):
    """the level's collision triangles of the visuals: all three corners on one of their triangles (near its plane,
    inside its bounds)"""
    verts, faces = cform
    found = set()
    for v in ids:
        T = g.triangles(d, visuals[v])
        A = T[:, 0]
        N = np.cross(T[:, 1] - A, T[:, 2] - A)
        ln = np.linalg.norm(N, axis=1)
        keep = ln > 1e-9
        A, N, T = A[keep], N[keep] / ln[keep, None], T[keep]
        lo, hi = T.min(1) - eps, T.max(1) + eps
        blo, bhi = T.reshape(-1, 3).min(0) - eps, T.reshape(-1, 3).max(0) + eps
        cand = np.nonzero(np.all((verts[faces] >= blo) & (verts[faces] <= bhi), axis=(1, 2)))[0]
        vids = np.unique(faces[cand])
        on = {}
        for s in range(0, len(vids), 256):
            Pp = verts[vids[s:s + 256]]
            dist = np.abs(np.einsum("kmj,mj->km", Pp[:, None, :] - A[None], N))
            inside = np.all((Pp[:, None, :] >= lo[None]) & (Pp[:, None, :] <= hi[None]), axis=2)
            for vid, ok in zip(vids[s:s + 256], np.any((dist < eps) & inside, axis=1)):
                on[vid] = ok
        found |= {int(t) for t in cand if all(on[i] for i in faces[t])}
    return sorted(found)


def ranges(idx):
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append(f"{start}-{prev}" if prev > start else str(start))
            start = prev = i
    if start is not None:
        out.append(f"{start}-{prev}" if prev > start else str(start))
    return out


def cmd_plan(level_dir, out, box):
    X0, X1, Z0, Z1 = box
    pieces, _ = load(level_dir, VISUALS)
    objects = assemble(pieces)
    K = 90
    img = Image.new("RGB", (int((X1 - X0) * K), int((Z1 - Z0) * K)), (20, 20, 20))
    dr = ImageDraw.Draw(img, "RGBA")
    rng = np.random.default_rng(3)
    for i, obj in enumerate(objects, 1):
        lo = np.min([p.lo for p in obj], 0)
        hi = np.max([p.hi for p in obj], 0)
        textures = sorted({p.texture.split("\\")[-1] for p in obj})
        print(f"object {i:2d} {kind_of(obj):6s}: {len(obj):2d} pieces ({', '.join(textures)})  x {lo[0]:6.2f}..{hi[0]:6.2f}"
              f"  y {lo[1]:5.2f}..{hi[1]:5.2f}  z {lo[2]:6.2f}..{hi[2]:6.2f}")
        c = tuple(int(x) for x in rng.integers(70, 255, 3))
        for p in obj:
            for t in p.I:
                dr.polygon([((p.P[k, 0] - X0) * K, (Z1 - p.P[k, 2]) * K) for k in t], fill=c + (60,), outline=c + (170,))
        dr.text((((lo[0] + hi[0]) / 2 - X0) * K - 5, (Z1 - (lo[2] + hi[2]) / 2) * K - 6), str(i), fill=(255, 255, 255))
    img.save(out)


def cmd_build(level_dir):
    pieces, (d, visuals, g) = load(level_dir, VISUALS)
    objects = assemble(pieces)
    models = []  # (name, kind, meshes, signature)
    places = []  # (model name, origin, heading, the level's visuals it comes of)
    for obj in objects:
        kind = kind_of(obj)
        h, origin = frame(obj)
        of = sorted({p.visual for p in obj})
        meshes = meshes_of(obj, h, origin)
        sig, sig_turned = signature(meshes), signature(turned(meshes))
        for name, k, m, s in models:
            if k == kind and s in (sig, sig_turned):
                places.append((name, origin, h if s == sig else h + math.pi, of))
                break
        else:
            name = f"{kind}_{sum(1 for m in models if m[1] == kind) + 1}"
            models.append((name, kind, meshes, sig))
            places.append((name, origin, h, of))
    os.makedirs(os.path.join(GAMEDATA, "meshes", "dynamics", "shelter", "props"), exist_ok=True)
    sections = ["; The shelter's movable props (tools\\shelter\\props.py builds this file and the models): each a model cut out",
                "; of bunker_a1, placed by Hideout Furniture (shelter_prop_*) and kept in the stash as an item (shelter_item_prop_*)", ""]
    for name, kind, meshes, _ in models:
        text, (tex, gx, gy, gw, gh), material, mass = KINDS[kind]
        allP = np.concatenate([m[1] for m in meshes])
        lo, hi = allP.min(0), allP.max(0)
        centre, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 0.02)
        path = os.path.join(GAMEDATA, "meshes", "dynamics", "shelter", "props", name + ".ogf")
        size = ogf.write(path, meshes, [(centre, half, mass)], f"shelter prop {name}", material)
        print(f"{name}: {sum(len(m[4]) for m in meshes)} triangles, {hi[0]-lo[0]:.2f}x{hi[1]-lo[1]:.2f}x{hi[2]-lo[2]:.2f}, {size} bytes")
        visual = f"dynamics\\shelter\\props\\{name}.ogf"
        sections += [
            f"[shelter_item_prop_{name}]:tch_junk",
            "class                   = II_ATTCH",
            "kind                    = i_tool",
            f"visual                  = {visual}",
            f"description             = {text}_descr",
            f"inv_name                = {text}",
            f"inv_name_short          = {text}",
            f"icons_texture           = {tex}",
            f"inv_grid_x              = {gx}",
            f"inv_grid_y              = {gy}",
            f"inv_grid_width          = {gw}",
            f"inv_grid_height         = {gh}",
            "cost                    = 20",
            f"inv_weight              = {mass}",
            "use1_functor            = placeable_furniture.place_item",
            "use1_action_functor     = placeable_furniture.func_place_item",
            "placeable_type          = prop",
            f"placeable_section       = shelter_prop_{name}",
            "",
            f"[shelter_prop_{name}]:physic_object",
            f"visual                  = {visual}",
            "placeable_type          = prop",
            "base_rotation           = 0",
            "script_binding          = bind_hf_base.init",
            f"item_section            = shelter_item_prop_{name}",
            f"bounding_box_size       = {hi[0]-lo[0]:.3f}, {hi[2]-lo[2]:.3f}, {hi[1]-lo[1]:.3f}",
            f"bounding_box_origin     = {centre[0]:.3f}, {centre[1]:.3f}, {centre[2]:.3f}",
            ""]
    open(os.path.join(GAMEDATA, "configs", "mod_system_shelter_props.ltx"), "w", encoding="cp1251", newline="\r\n").write("\n".join(sections))
    cf = open(level_dir + "/level.cform", "rb").read()
    _, vc, fc = struct.unpack_from("<III", cf, 0)
    verts = np.frombuffer(cf, "<f4", vc * 3, 36).reshape(vc, 3).astype(np.float64)
    faces = np.frombuffer(cf, "<u4", fc * 4, 36 + vc * 12).reshape(fc, 4)[:, :3].astype(np.int64)
    tris = collision(d, visuals, g, (verts, faces), VISUALS)
    lines = ["; The shelter's movable props (scripts\\shelter_furniture.script; tools\\shelter\\props.py builds this file):",
             "; the level's visuals they replace (hidden, their collision taken out, on every load) and where each stands",
             "; (spawned once: section, x, y, z, heading, the visuals it comes of, joined by +: the ini drops spaces).",
             "; The indices only fit these level files.", "",
             "[replaced]",
             "visuals = " + ", ".join(map(str, VISUALS)),
             "triangles = " + ",".join(ranges(tris)), "",
             "[places]"]
    for i, (name, o, h, of) in enumerate(places, 1):
        h = (h + math.pi) % (2 * math.pi) - math.pi
        lines.append(f"{i} = shelter_prop_{name}, {o[0]:.3f}, {o[1]:.3f}, {o[2]:.3f}, {h:.4f}, {'+'.join(map(str, of))}")
    path = os.path.join(GAMEDATA, "configs", "scripts", "shelter", "props.ltx")
    open(path, "w", encoding="cp1251", newline="\r\n").write("\n".join(lines) + "\n")
    print(f"{len(objects)} objects, {len(models)} models, {len(tris)} collision triangles")


if __name__ == "__main__":
    if sys.argv[1] == "plan":
        cmd_plan(sys.argv[2], sys.argv[3], [float(v) for v in sys.argv[4:8]])
    elif sys.argv[1] == "build":
        cmd_build(sys.argv[2])
