r"""Raid copies of levels as one level pack: each level of the raid under its own name (raid_*), with its spawn
records and patrol paths renamed (prefix raid_), re-pointed to the pack graph and cleared of the story; transitions
made restrictors that raid.script runs. The originals stay in the world as they are.
  raid_copy.py <all.spawn> <Anomaly configs dir> <out gamedata dir> [<converter.exe> <Anomaly db\levels dir>]
Writes into <out>: spawns\raid.spawn, configs\mod_game_raid.ltx (the levels in game.ltx),
configs\misc\mod_smart_terrain_masks_raid.ltx, configs\scripts\raid\smart\*.ltx, configs\scripts\raid\levels.ltx
(for raid.script: the levels in the app's order, their originals and maps, the landing); given the converter (X-Ray
db unpacker, Anomaly's tools\converter.exe) also levels\<copy>\ from each level's archive, first (the maps are read
from their level.ltx).
all.spawn and the configs come unpacked from Anomaly's db\configs\spawns.db0 and configs.db0
(converter.exe -unpack -xdb <db0> -dir <dir>).

Records on a copy:
- the name gets the prefix; so do the names of copied records and paths its custom data mentions;
- story ids and [story_object] are dropped, and [logic] whose cfg is level-specific (scripts\<folder>\...) except
  crow spawners; quest items (DROP) are not copied;
- a smart terrain gets its own cfg (scripts\raid\smart\<name>.ltx: population only, no respawn, no story jobs) and
  the original's terrain mask;
- transitions: Anomaly's sr_teleport restrictor (a dialog that drops the actor into a level changer) becomes the
  trigger of the level changer its drop point lands in; a level changer no such restrictor uses (the Sarcophagus,
  the Control Center) becomes a restrictor itself. Its [raid_transition]: level (the copy's name, or the original
  level's for one outside the raid), position, node, direction. Engine level changers are not copied.
The graph keeps the copied levels' vertices, death points and cross tables, and only the edges inside a level: a
copy has no graph link to any other level.
"""
import os
import re
import struct
import subprocess
import sys
import uuid

from spawn_file import (CELL, EDGE, POINT, TABLE_HEADER, VERTEX, chunk, chunks, cross_table, paths, read_graph,
                        records, vertex_level)

LEVELS = {  # in the raid app's order
    b"l10_limansk": b"raid_limansk",
    b"l11_hospital": b"raid_hospital",
    b"l12_stancia_2": b"raid_stancia_2",  # Север ЧАЭС
    b"l12_stancia": b"raid_stancia",  # Юг ЧАЭС
    b"l12u_sarcofag": b"raid_sarcofag",
    b"l12u_control_monolith": b"raid_control_monolith",
}
PREFIX = b"raid_"
DROP = {b"main_story_7_mon_con_documents"}
KEEP_LOGIC = re.compile(rb"_crow_spawner\.ltx$", re.I)
OFFSET_SHIFT = (0.0, 0.0, 10000.0)  # of each copy's global offset: off the world's levels
LANDING = (b"l10_red_forest", b"l10_limansk")  # a raid lands where this level changer brings the actor


def ini_sections(text):
    """[(section name, or None for the lines before the first one, [lines])]"""
    out = [(None, [])]
    for line in text.replace(b"\r", b"").split(b"\n"):
        m = re.match(rb"\s*\[([^\]]+)\]", line)
        if m:
            out.append((m.group(1), [line]))
        else:
            out[-1][1].append(line)
    return out


def ini_join(sections):
    lines = [l for _, ls in sections for l in ls]
    while lines and not lines[-1].strip():
        lines.pop()
    return b"\r\n".join(lines) + (b"\r\n" if lines else b"")


def logic_cfg(lines):
    for line in lines:
        m = re.match(rb"\s*cfg\s*=\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


def rename_refs(text, names):
    """Whole names of copied records and paths get the prefix; a name inside a file path does not."""
    return re.sub(rb"(?<![\w\\.])[A-Za-z_]\w*(?![\w\\.])", lambda m: PREFIX + m.group(0) if m.group(0) in names else m.group(0), text)


def read_ltx(path):
    return open(path, "rb").read().decode("cp1251", "replace")


def ltx_section(text, name, raw=False):
    m = re.search(r"(?ms)^\s*\[%s\][^\n]*\n(.*?)(?=^\s*\[|\Z)" % re.escape(name), text)
    if not m:
        return None if raw else {}
    if raw:
        return m.group(1)
    out = {}
    for line in m.group(1).splitlines():
        line = line.split(";")[0]
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def build_graph(graph, level_ids):
    """The pack graph: the copied levels' vertices (renumbered), the edges inside each level, death points and cross
    tables; the levels keep their ids and take the copies' names."""
    g, vc, ec = graph["data"], graph["vertex_count"], graph["edge_count"]
    vertex = lambda i: g[graph["nodes"] + i * VERTEX:graph["nodes"] + (i + 1) * VERTEX]
    ours = [i for i in range(vc) if vertex_level(graph, i) in level_ids]
    remap = {old: new for new, old in enumerate(ours)}
    guid = uuid.uuid4().bytes

    rows, kept, dropped = [], 0, 0
    for old in ours:
        v = vertex(old)
        edge_offset, point_offset, neighbours, deaths = struct.unpack_from("<IIBB", v, 32)
        first_edge = (edge_offset - vc * VERTEX) // EDGE
        edges = []
        for k in range(neighbours):
            target, distance = struct.unpack_from("<Hf", g, graph["edges"] + (first_edge + k) * EDGE)
            if target in remap and vertex_level(graph, target) == vertex_level(graph, old):
                edges.append(struct.pack("<Hf", remap[target], distance))
            else:
                dropped += 1
        first_point = (point_offset - vc * VERTEX - ec * EDGE) // POINT
        rows.append((v, edges, g[graph["points"] + first_point * POINT:graph["points"] + (first_point + deaths) * POINT]))
        kept += len(edges)

    edge_offset, point_offset = len(ours) * VERTEX, len(ours) * VERTEX + kept * EDGE
    vertices = b""
    for v, edges, points in rows:
        vertices += v[:32] + struct.pack("<IIBB", edge_offset, point_offset, len(edges), len(points) // POINT)
        edge_offset += len(edges) * EDGE
        point_offset += len(points)
    edge_bytes = b"".join(e for _, edges, _ in rows for e in edges)
    point_bytes = b"".join(points for _, _, points in rows)

    levels = sorted((l for l in graph["levels"] if l["id"] in level_ids), key=lambda l: l["id"])
    tables = b""
    for level in levels:
        table = bytearray(cross_table(graph, level["id"]))
        nodes = struct.unpack_from("<I", table, 8)[0]
        struct.pack_into("<I", table, 12, sum(1 for i in ours if vertex_level(graph, i) == level["id"]))
        table[32:48] = guid  # game guid, after the size, version, node and vertex counts, level guid
        for i in range(nodes):
            at = 4 + TABLE_HEADER + i * CELL
            struct.pack_into("<H", table, at, remap[struct.unpack_from("<H", table, at)[0]])
        tables += bytes(table)

    header = struct.pack("<BHII", graph["version"], len(ours), kept, len(point_bytes) // POINT) + guid + bytes([len(levels)])
    for level in levels:
        name = LEVELS[level["name"]]
        header += name + b"\0" + level["offset"] + bytes([level["id"]]) + b"level_" + name + b"\0" + level["guid"]
    print("graph: %d vertices, %d edges kept, %d to other levels dropped" % (len(ours), kept, dropped))
    return header + vertices + edge_bytes + point_bytes + tables, guid, remap, levels


def transition_ini(changer):
    f = changer.changer_fields()
    return (b"[logic]\r\nactive = sr_idle@raid_wait\r\n\r\n"
            b"[sr_idle@raid_wait]\r\non_actor_inside = sr_idle@raid_run %=raid_transition%\r\n\r\n"
            b"[sr_idle@raid_run]\r\non_actor_outside = sr_idle@raid_wait\r\n\r\n"
            b"[raid_transition]\r\nlevel = " + LEVELS.get(f["level"], f["level"]) + b"\r\n"
            + b"position = %.3f, %.3f, %.3f\r\n" % f["position"]
            + b"node = %d\r\ndirection = %.4f\r\n" % (f["node"], f["angles"][1]))


def copy_records(top, graph, level_ids, configs):
    teleports = read_ltx(os.path.join(configs, "sr_teleport_sections.ltx"))
    ours = [r for r in records(top) if vertex_level(graph, r.gvid) in level_ids and r.section not in DROP]
    all_paths, our_paths = {}, []
    for p in paths(top):
        all_paths[p.name] = p
        levels = {vertex_level(graph, x) for x in p.gvids()} - {None}
        if levels and levels <= level_ids:
            our_paths.append(p)
    copied = {r.name for r in ours} | {p.name for p in our_paths}

    changers = [r for r in ours if r.section == b"level_changer"]
    taken = set()  # changers a teleport took, by record: names repeat across levels (exit_to_sarcofag_01)
    out, smarts = [], []
    stats = dict(teleports=0, changers=0, stripped=0, story=0)
    for r in ours:
        if r.section == b"level_changer":
            continue
        sections = ini_sections(r.ini)
        if any(s == b"story_object" for s, _ in sections):
            sections = [(s, ls) for s, ls in sections if s != b"story_object"]
            stats["story"] += 1
        cfg = next((logic_cfg(ls) for s, ls in sections if s == b"logic"), None)
        if cfg and cfg.lower().endswith(b"sr_teleport_logic.ltx"):
            drop = ltx_section(teleports, r.name.decode()).get("path")
            drop = drop and all_paths.get(drop.encode())  # a drop point may lie off the AI map: such a path is not copied
            here = [c for c in changers if vertex_level(graph, c.gvid) == vertex_level(graph, r.gvid)]
            if not (drop and here):
                print("! %s: no drop point or level changer, not copied" % r.name.decode())
                continue
            at = drop.first_position()
            changer = min(here, key=lambda c: sum((a - b) ** 2 for a, b in zip(c.position, at)))
            taken.add(id(changer))
            r.set_ini(transition_ini(changer))
            stats["teleports"] += 1
        elif r.section == b"smart_terrain":
            path = cfg and os.path.join(configs, cfg.decode().replace("\\", os.sep))
            smarts.append((r.name, ltx_section(read_ltx(path), "smart_terrain") if path and os.path.exists(path) else {}))
            r.set_ini(b"[smart_terrain]\r\ncfg = scripts\\raid\\smart\\" + PREFIX + r.name + b".ltx\r\n")
        else:
            if cfg and b"\\" in cfg and not KEEP_LOGIC.search(cfg):
                sections = [(s, ls) for s, ls in sections if s != b"logic"]
                stats["stripped"] += 1
            r.set_ini(rename_refs(ini_join(sections), copied))
        r.clear_story_ids()
        out.append(r)

    for c in changers:
        if id(c) in taken:
            continue
        ini = transition_ini(c)
        c.to_restrictor()
        c.set_ini(ini)
        c.clear_story_ids()
        out.append(c)
        stats["changers"] += 1
    print("records %d (teleports made triggers %d, level changers made triggers %d, level logic stripped %d, story "
          "objects cleared %d), paths %d, smarts %d" % (len(out), stats["teleports"], stats["changers"], stats["stripped"],
                                                      stats["story"], len(our_paths), len(smarts)))
    return out, our_paths, smarts


def write_configs(out, configs, levels, smarts):
    def write(relative, text):
        path = os.path.join(out, "configs", relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="cp1251", newline="\r\n").write(text)

    for name, src in smarts:
        write(os.path.join("scripts", "raid", "smart", (PREFIX + name).decode() + ".ltx"),
              "; raid copy of %s: population only, squads come from the raid\n[smart_terrain]\nsquad_id = %s\n"
              "max_population = %s\n" % (name.decode(), src.get("squad_id", "1"), src.get("max_population", "2")))

    masks = read_ltx(os.path.join(configs, "misc", "smart_terrain_masks.ltx"))
    lines = ["; Raid copies' smart terrains (raid_copy.py): the originals' masks"]
    for name, _ in smarts:
        body = ltx_section(masks, name.decode(), raw=True)
        if body is not None:
            lines += ["[%s]" % (PREFIX + name).decode(), body.rstrip("\n")]
    write(os.path.join("misc", "mod_smart_terrain_masks_raid.ltx"), "\n".join(lines) + "\n")

    game_levels = read_ltx(os.path.join(configs, "game_levels.ltx"))
    maps = read_ltx(os.path.join(configs, "game_maps_single.ltx"))
    lines = ["; Raid copies of levels (raid_copy.py): each its own level, added by the raid.spawn pack", "![levels]"]
    lines += ["level_" + LEVELS[l["name"]].decode() for l in levels]
    for l in levels:
        copy, orig = LEVELS[l["name"]].decode(), l["name"].decode()
        section = next(s for s in re.findall(r"(?m)^\s*\[(level\d+)\]", game_levels) if ltx_section(game_levels, s).get("name") == orig)
        x, y, z = struct.unpack("<3f", l["offset"])
        lines += ["", "[level_%s]" % copy, "name     = %s" % copy, 'caption  = "%s"' % copy,
                  "offset   = %.1f, %.1f, %.1f" % (x + OFFSET_SHIFT[0], y + OFFSET_SHIFT[1], z + OFFSET_SHIFT[2]),
                  "weathers = %s" % ltx_section(game_levels, section).get("weathers", "[default]"), "id       = auto"]
    lines += ["", "![level_maps_single]"] + ["%s =" % LEVELS[l["name"]].decode() for l in levels]
    for l in levels:
        lines += ["", "[%s]" % LEVELS[l["name"]].decode(), "global_rect  = 0, 0, 0, 0"]
        lines += ["%s = %s" % (k, v) for k, v in ltx_section(maps, l["name"].decode()).items() if k != "global_rect"]
    write("mod_game_raid.ltx", "\n".join(lines) + "\n")


def write_levels(out, top, graph):
    r"""configs\scripts\raid\levels.ltx: the levels in order with their originals and maps (from levels\<copy>\level.ltx
    when there), the landing (the destination of the LANDING level changer; came_from: the level it is from, whose
    transition on the landing level is the way out)."""
    lines = ["; Raid levels (raid_copy.py): read by raid.script", "[levels]",  # a list: an ini's lines come sorted
             "order = " + ", ".join(c.decode() for c in LEVELS.values())]
    for orig, copy in LEVELS.items():
        lines += ["", "[%s]" % copy.decode(), "original = %s" % orig.decode()]
        level_ltx = os.path.join(out, "levels", copy.decode(), "level.ltx")
        if os.path.exists(level_ltx):
            m = ltx_section(read_ltx(level_ltx), "level_map")
            if m.get("texture") and not m["texture"].endswith("map_nomap"):
                lines += ["map_texture = %s" % m["texture"], "map_bounds = %s" % m["bound_rect"]]
    source = next(l["id"] for l in graph["levels"] if l["name"] == LANDING[0])
    changer = next(r for r in records(top) if r.section == b"level_changer" and vertex_level(graph, r.gvid) == source
                   and r.changer_fields()["level"] == LANDING[1])
    f = changer.changer_fields()
    lines += ["", "[landing]", "level = %s" % LEVELS[LANDING[1]].decode(), "came_from = %s" % LANDING[0].decode(),
              "position = %.3f, %.3f, %.3f" % f["position"], "node = %d" % f["node"], "direction = %.4f" % f["angles"][1]]
    path = os.path.join(out, "configs", "scripts", "raid", "levels.ltx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="cp1251", newline="\r\n").write("\n".join(lines) + "\n")
    print("landing: %s at %s (%s)" % (LEVELS[LANDING[1]].decode(), f["position"], changer.name.decode()))


def unpack_levels(out, converter, db_levels):
    for orig, copy in LEVELS.items():
        orig, copy = orig.decode(), copy.decode()
        temp = os.path.join(out, "levels", "_unpack_" + orig)
        subprocess.run([converter, "-unpack", "-xdb", os.path.join(db_levels, "level_%s.db0" % orig), "-dir", temp],
                       check=True, cwd=os.path.dirname(converter), stdout=subprocess.DEVNULL)
        os.replace(os.path.join(temp, "levels", orig), os.path.join(out, "levels", copy))
        os.rmdir(os.path.join(temp, "levels"))
        os.rmdir(temp)
        print("levels\\%s from level_%s.db0" % (copy, orig))


def main():
    source, configs, out = sys.argv[1:4]
    top = chunks(open(source, "rb").read())
    graph = read_graph(top[4])
    by_name = {l["name"]: l["id"] for l in graph["levels"]}
    level_ids = {by_name[n] for n in LEVELS}

    body, graph_guid, remap, levels = build_graph(graph, level_ids)
    out_records, out_paths, smarts = copy_records(top, graph, level_ids, configs)
    for r in out_records:
        r.set_name(PREFIX + r.name)
        r.set_gvid(remap[r.gvid])
    for p in out_paths:
        p.name = PREFIX + p.name
        p.map_gvids(remap)

    vertices = b"".join(chunk(i, chunk(0, struct.pack("<H", i)) + chunk(1, r.bytes())) for i, r in enumerate(out_records))
    spawn_graph = chunk(0, struct.pack("<I", len(out_records))) + chunk(1, vertices) + chunk(2, b"")
    path_storage = chunk(0, struct.pack("<I", len(out_paths))) + chunk(1, b"".join(chunk(i, p.bytes()) for i, p in enumerate(out_paths)))
    header = struct.unpack_from("<I", top[0], 0)[0]
    header = struct.pack("<I", header) + uuid.uuid4().bytes + graph_guid + struct.pack("<II", len(out_records), len(levels))
    pack = chunk(0, header) + chunk(1, spawn_graph) + chunk(2, struct.pack("<I", 0)) + chunk(3, path_storage) + chunk(4, body)
    os.makedirs(os.path.join(out, "spawns"), exist_ok=True)
    open(os.path.join(out, "spawns", "raid.spawn"), "wb").write(pack)
    write_configs(out, configs, levels, smarts)
    if len(sys.argv) > 5:
        unpack_levels(out, sys.argv[4], sys.argv[5])
    write_levels(out, top, graph)


if __name__ == "__main__":
    main()
