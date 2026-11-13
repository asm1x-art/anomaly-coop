r"""Quality tiers (tiers.py): GRA's visual mods merged per tier the way Mod Organizer merges them, then cut into
components by the set of tiers that use each file, so that no path is in two components of one tier and changing the
tier downloads only the difference.
  build_tiers.py plan                      the components and tiers, sizes, what was left out and why
  build_tiers.py build <stage> <out>       pack every component into <out>\<component>\db\patches\<component>_*.db
                                           and write <out>\tiers.json for the release builder
Options: --mo2 <mods folder> (or GRA_MO2), --converter <converter.exe> (or GRA_CONVERTER), --loose <gamedata folder>
(loose files of a release outside git: they win over archives, so their paths are not packed; may repeat),
--only <component> (may repeat), --sample <MB> (the first files of each component up to that size: a pipeline test),
--files <file> (plan: write "component<TAB>path<TAB>size<TAB>source" lines).
"""
import fnmatch
import json
import os
import shutil
import subprocess
import sys

import build_pack
import db_list
import tiers as T

TIER_IDS = [t["id"] for t in T.TIERS]


def mod_files(mo2, mod):
    """{gamedata path (lower case, /): real path} of a mod"""
    root = os.path.join(mo2, mod, "gamedata")
    if not os.path.isdir(root):
        sys.exit(f"no {root}")
    out = {}
    for dirpath, _, names in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            out[os.path.relpath(full, root).replace("\\", "/").lower()] = full
    return out


def allowed(rel):
    """a picture and nothing else: textures, models, particles.xr, a level's grass and terrain texture"""
    try:
        rel.encode("ascii")
    except UnicodeEncodeError:
        return False
    parts = rel.split("/")
    if parts[0] == "textures":
        return rel.endswith((".dds", ".thm", ".ogm", ".seq"))
    if parts[0] == "meshes":
        return rel.endswith((".ogf", ".omf", ".dm"))
    if rel == "particles.xr":
        return True
    if parts[0] == "levels" and len(parts) >= 3:
        return (len(parts) == 3 and parts[2] in T.ALLOWED_LEVEL_FILES) or (parts[2] == "terrain" and rel.endswith(".dds"))
    return False


def same_for_all(rel):
    """files co-op needs identical on every player's machine: models (bones, shapes, joints) and level.details"""
    return rel.startswith("meshes/") or fnmatch.fnmatch(rel, "levels/*/level.details")


def plan(mo2, loose_dirs):
    """-> components {id: {"title", "files": [(rel, full, size, mod)], "mods": set}}, tiers {tier: [component ids]}, notes"""
    files = {m["mod"]: mod_files(mo2, m["mod"]) for m in T.MODS}
    yielded = {}
    for mod in T.YIELD_TO:
        for rel in mod_files(mo2, mod):
            yielded[rel] = mod
    loose = [build_pack.REPO_GAMEDATA] + loose_dirs
    notes = {"not a picture": [], "yielded": {}, "loose": []}

    winners = {}  # tier -> {rel: mod}
    for tier in TIER_IDS:
        w = {}
        for m in T.MODS:  # lowest first: a later mod replaces
            if tier in m["tiers"].split():
                for rel in files[m["mod"]]:
                    w[rel] = m["mod"]
        winners[tier] = w
    group = {m["mod"]: m["group"] for m in T.MODS}

    components = {}
    for rel in sorted(set().union(*winners.values())):
        by_mod = {}  # mod -> tiers it wins in
        for tier in TIER_IDS:
            mod = winners[tier].get(rel)
            if mod:
                by_mod.setdefault(mod, []).append(tier)
        if not allowed(rel):
            notes["not a picture"].append((rel, sorted(by_mod)))
            continue
        if rel in yielded:
            notes["yielded"].setdefault(yielded[rel], []).append(rel)
            continue
        if any(os.path.isfile(os.path.join(d, *rel.split("/"))) for d in loose):
            notes["loose"].append(rel)
            continue
        if same_for_all(rel) and (len(by_mod) > 1 or next(iter(by_mod.values())) != TIER_IDS):
            sys.exit(f"{rel} would differ between tiers ({by_mod}): models and level.details must be the same for all")
        for mod, mod_tiers in by_mod.items():
            key = group[mod] if mod_tiers == TIER_IDS else " ".join(mod_tiers)
            cid, title = T.COMPONENTS[key]
            c = components.setdefault(cid, {"title": title, "tiers": mod_tiers if mod_tiers != TIER_IDS else TIER_IDS,
                                            "files": [], "mods": set()})
            full = files[mod][rel]
            c["files"].append((rel, full, os.path.getsize(full), mod))
            c["mods"].add(mod)

    tiers = {tier: sorted(cid for cid, c in components.items() if tier in c["tiers"]) for tier in TIER_IDS}
    # the partition holds: within a tier no path twice
    for tier, cids in tiers.items():
        paths = [f[0] for cid in cids for f in components[cid]["files"]]
        assert len(paths) == len(set(paths)), tier
    return components, tiers, notes


def tiers_json(components, tiers, sizes=None, sample=False):
    order = [m["mod"] for m in T.MODS]
    out = {
        "components": [{
            "id": cid, "title": c["title"],
            "raw_bytes": sizes[cid] if sizes else sum(f[2] for f in c["files"]),
            "files": len(c["files"]),
            "mods": sorted(c["mods"], key=order.index),
        } for cid, c in sorted(components.items())],
        "tiers": [{"id": t["id"], "title": t["title"], "vram_gb": t["vram_gb"], "components": tiers[t["id"]]} for t in T.TIERS],
    }
    if sample:
        out["sample"] = True
    return out


def gb(n):
    return f"{n / 2**30:.2f} GiB"


def cmd_plan(components, tiers, notes, files_out):
    for cid, c in sorted(components.items()):
        size = sum(f[2] for f in c["files"])
        print(f"{cid}  «{c['title']}»  tiers: {' '.join(c['tiers'])}  {len(c['files'])} files, {gb(size)}")
        by_mod = {}
        for rel, _, n, mod in c["files"]:
            e = by_mod.setdefault(mod, [0, 0, {}])
            e[0] += 1
            e[1] += n
            top = rel.split("/")[0]
            e[2][top] = e[2].get(top, 0) + 1
        for m in T.MODS:
            if m["mod"] in by_mod:
                n, size, kinds = by_mod[m["mod"]]
                print(f"    {n:5d} files {size / 2**20:8.0f} MiB  {m['mod']}  {kinds}")
    print()
    for t in T.TIERS:
        cids = tiers[t["id"]]
        size = sum(f[2] for cid in cids for f in components[cid]["files"])
        print(f"tier {t['id']} ({t['title']}): {gb(size)}  = {' + '.join(cids)}")
    print()
    print(f"not a picture, left out: {len(notes['not a picture'])}")
    for rel, mods in notes["not a picture"]:
        print(f"    {rel}  <- {', '.join(mods)}")
    for mod, rels in notes["yielded"].items():
        print(f"left to {mod}: {len(rels)} paths")
    print(f"loose in gamedata (it wins over archives), left out: {len(notes['loose'])}")
    for rel in notes["loose"]:
        print(f"    {rel}")
    if files_out:
        with open(files_out, "w", encoding="utf-8", newline="\n") as f:
            for cid, c in sorted(components.items()):
                for rel, full, size, mod in c["files"]:
                    f.write(f"{cid}\t{rel}\t{size}\t{full}\n")


def link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def cmd_build(components, tiers, stage, out, converter, sample_mb):
    os.makedirs(stage, exist_ok=True)
    header = os.path.join(stage, "header.ltx")
    open(header, "w", newline="\r\n").write(build_pack.HEADER)
    sizes = {}
    for cid, c in sorted(components.items()):
        items = sorted(c["files"])
        if sample_mb:
            kept, total = [], 0
            for f in items:
                if total + f[2] <= sample_mb << 20:
                    kept.append(f)
                    total += f[2]
            items = c["files"] = kept
        dest = os.path.join(out, cid, *T.ARCHIVE_DIR.split("/"))
        if os.path.isdir(os.path.join(out, cid)):
            shutil.rmtree(os.path.join(out, cid))
        os.makedirs(dest)
        # archives by kind (meshes, textures, levels, particles.xr), each up to build_pack.ARCHIVE_SIZE
        groups, current = [], None
        for rel, full, size, mod in items:
            top = rel.split("/", 1)[0].split(".")[0]
            if current is None or current[0] != top or current[2] + size > build_pack.ARCHIVE_SIZE:
                current = [top, [], 0]
                groups.append(current)
            current[1].append((rel, full, size))
            current[2] += size
        counters, sizes[cid] = {}, 0
        for top, group, size in groups:
            n = counters.get(top, 0)
            counters[top] = n + 1
            name = f"{cid}_{top}_{n:02d}"
            folder = os.path.join(stage, name)
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            for rel, full, _ in group:
                dst = os.path.join(folder, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                link_or_copy(full, dst)
            db = os.path.join(dest, name + ".db")
            print(f"{name}: {len(group)} files, {size / 2**20:.0f} MiB -> {db}", flush=True)
            subprocess.run([converter, "-pack", folder, "-out", db, "-xdb", "-xdb_ud", header], check=True,
                           stdout=subprocess.DEVNULL)
            shutil.rmtree(folder)
            # the archive lists exactly the files given, with their sizes
            packed = {name_: real for name_, real, _, _, _ in db_list.table(db) if not name_.endswith("/")}
            assert packed == {rel: size_ for rel, _, size_ in group}, db
            sizes[cid] += os.path.getsize(db)
    path = os.path.join(out, "tiers.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(tiers_json(components, tiers, sizes, bool(sample_mb)), f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("written", path)


def main(argv):
    opts = {"mo2": os.environ.get("GRA_MO2", build_pack.MO2), "converter": os.environ.get("GRA_CONVERTER", build_pack.CONVERTER),
            "loose": [], "only": [], "sample": 0, "files": None}
    args = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--mo2", "--converter", "--files"):
            opts[a[2:]] = argv[i + 1]
            i += 1
        elif a in ("--loose", "--only"):
            opts[a[2:]].append(argv[i + 1])
            i += 1
        elif a == "--sample":
            opts["sample"] = int(argv[i + 1])
            i += 1
        else:
            args.append(a)
        i += 1
    cmd = args[0] if args else "plan"
    components, tiers, notes = plan(opts["mo2"], opts["loose"])
    if opts["only"]:
        components = {cid: c for cid, c in components.items() if cid in opts["only"]}
        tiers = {t: [cid for cid in cids if cid in components] for t, cids in tiers.items()}
    if cmd == "plan":
        cmd_plan(components, tiers, notes, opts["files"])
    elif cmd == "build" and len(args) == 3:
        cmd_build(components, tiers, args[1], args[2], opts["converter"], opts["sample"])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
