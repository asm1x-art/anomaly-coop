"""The things in levels' static geometry: visuals cut into connected pieces, touching pieces put together, duplicates dropped, each
drawn. levelscan.py <level name>...  -> out_levels/<level>.json, thumbs in out_levels/thumbs. Runs at idle priority."""
import ctypes
import json
import multiprocessing as mp
import os
import pickle
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, r"H:\stalker-test\xray-monolith-shelter\tools\shelter")
import ogfview  # noqa: E402
from levelgeom import Geom  # noqa: E402
from levelvis import level  # noqa: E402

SCRATCH = os.path.dirname(HERE)
LEVELS = os.path.join(SCRATCH, "assets", "levels")
OUT = os.path.join(HERE, "out_levels")
TEX = [os.path.join(SCRATCH, "assets", "tex", "textures")]
KEEP = re.compile(r"^(prop|wood|mtl|door|el|furn|kitchen|med|lab|glass|fur|sign)\\", re.I)
DROP = re.compile(r"lampa|glow|provod|fake|grate_01$|terrain|flora|trees|grnd|wire|cable|rails?|truba|barrel_big|rja|walls?|roof|ceil|pod_0|kreplen|arm_|tubes|luk_|bochka_0|ventil|angar|fence", re.I)
MIN_SIZE, MAX_SIZE, MIN_TRIS = 0.3, 4.5, 16
LIMIT = np.array([4.2, 2.8, 4.2])  # a thing put together no bigger than this
TOUCH = 0.012


def low():
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)  # idle


def weld_parts(P, N, UV, I):
    key = {}
    weld = np.array([key.setdefault(tuple(k), len(key)) for k in np.round(P * 500).astype(np.int64)])
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
    order = np.argsort(root, kind="stable")
    rs, starts = np.unique(root[order], return_index=True)
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(order)
        tris = I[order[s:e]]
        used = np.unique(tris)
        remap = np.full(len(P), -1)
        remap[used] = np.arange(len(used))
        yield P[used], N[used], UV[used], remap[tris]


def scan(name):
    level_dir = os.path.join(LEVELS, "level_" + name, "levels", name)
    d, shaders, visuals = level(level_dir)
    g = Geom(level_dir + "/level.geom")
    pieces = []
    for v in visuals:
        sh = shaders[v["shader"]] if v["shader"] < len(shaders) else ""
        tex = sh.split("/")[-1].split(",")[0]
        if not KEEP.match(tex) or DROP.search(tex) or v["type"] not in (0, 2):
            continue
        try:
            mesh = g.mesh(d, v)
        except Exception:
            continue
        P, N, UV, I = mesh[:4]
        if len(I) > 60000:
            continue
        for p, n, uv, i in weld_parts(P, N, UV, I):
            lo, hi = p.min(0), p.max(0)
            if (hi - lo).max() > MAX_SIZE:
                continue
            pieces.append(dict(v=v["idx"], tex=tex, P=p, N=n, UV=uv, I=i, lo=lo, hi=hi))
    print(name, "pieces", len(pieces), flush=True)
    # touching pieces into things: a grid to look only at neighbours
    parent = list(range(len(pieces)))
    box = [(p["lo"].copy(), p["hi"].copy()) for p in pieces]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    cells = {}
    for i, p in enumerate(pieces):
        a = np.floor(p["lo"] / 2).astype(int)
        b = np.floor(p["hi"] / 2).astype(int)
        for x in range(a[0], b[0] + 1):
            for y in range(a[1], b[1] + 1):
                for z in range(a[2], b[2] + 1):
                    cells.setdefault((x, y, z), []).append(i)
    tried = set()
    for lst in cells.values():
        for ii, i in enumerate(lst):
            for j in lst[ii + 1:]:
                if (i, j) in tried:
                    continue
                tried.add((i, j))
                ri, rj = find(i), find(j)
                if ri == rj:
                    continue
                a, b = box[ri], box[rj]
                if np.all(a[0] - TOUCH <= b[1]) and np.all(b[0] - TOUCH <= a[1]):
                    lo, hi = np.minimum(a[0], b[0]), np.maximum(a[1], b[1])
                    if np.all(hi - lo <= LIMIT):
                        parent[rj] = ri
                        box[ri] = (lo, hi)
    groups = {}
    for i in range(len(pieces)):
        groups.setdefault(find(i), []).append(i)
    seen, things = set(), []
    for idx in groups.values():
        lo = np.min([pieces[i]["lo"] for i in idx], axis=0)
        hi = np.max([pieces[i]["hi"] for i in idx], axis=0)
        size = hi - lo
        tris = sum(len(pieces[i]["I"]) for i in idx)
        if size.max() < MIN_SIZE or tris < MIN_TRIS or size[1] < 0.05:
            continue
        # flat sheets on a wall or floor are no things
        if sorted(size)[1] < 0.06:
            continue
        texs = sorted({pieces[i]["tex"] for i in idx})
        sig = (tuple(texs), tuple(sorted(np.round(size / 0.1).astype(int).tolist())), tris // 8)
        if sig in seen:
            continue
        seen.add(sig)
        centre = (lo + hi) / 2
        foot = np.array([centre[0], lo[1], centre[2]])
        meshes = []
        for tex in texs:
            ps = [pieces[i] for i in idx if pieces[i]["tex"] == tex]
            base, Ps, Ns, UVs, Is = 0, [], [], [], []
            for p in ps:
                Ps.append(p["P"] - foot)
                Ns.append(p["N"])
                UVs.append(p["UV"])
                Is.append(p["I"] + base)
                base += len(p["P"])
            meshes.append(dict(tex=tex, shader="models\\model", P=np.concatenate(Ps), N=np.concatenate(Ns), UV=np.concatenate(UVs), I=np.concatenate(Is)))
        things.append(dict(level=name, id=f"{name}_{len(things)}", size=size.round(2).tolist(), tris=int(tris), textures=texs,
                           at=foot.round(2).tolist(), visuals=sorted({pieces[i]["v"] for i in idx}), meshes=meshes))
    print(name, "things", len(things), flush=True)
    return things


def draw(t):
    out = os.path.join(OUT, "thumbs", t["id"] + ".jpg")
    if not os.path.exists(out):
        ogfview.thumbnail({"meshes": t["meshes"]}, TEX, out, size=150)
    return t["id"]


if __name__ == "__main__":
    low()
    os.makedirs(os.path.join(OUT, "thumbs"), exist_ok=True)
    for name in sys.argv[1:]:
        things = scan(name)
        pickle.dump(things, open(os.path.join(OUT, name + ".pkl"), "wb"))
        json.dump([{k: v for k, v in t.items() if k != "meshes"} for t in things], open(os.path.join(OUT, name + ".json"), "w"), indent=0)
        with mp.Pool(3, initializer=low) as pool:
            for _ in pool.imap_unordered(draw, things, chunksize=4):
                pass
        print(name, "drawn", flush=True)
