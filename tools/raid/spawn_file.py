"""An all.spawn read and written by parts: chunks, the game graph, spawn records, patrol paths (for raid_copy.py)."""
import struct

VERTEX = 42  # GameGraph::CVertex, pack(1): local, global, level id:8 + node:24, types[4], edge/point offsets, counts
EDGE = 6  # CEdge, pack(1): vertex id u16, distance
POINT = 20  # CLevelPoint: point, node, distance
CELL = 6  # CGameLevelCrossTable::CCell, pack(2): game vertex id u16, distance
TABLE_HEADER = 44  # cross table: version, node count, game vertex count, level guid, game guid

M_SPAWN = 1
M_SPAWN_VERSION = 1 << 5
SPAWN_VERSION = 128


def chunks(data):
    out, pos = {}, 0
    while pos < len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        out[cid & 0x7FFFFFFF] = data[pos + 8:pos + 8 + size]
        pos += 8 + size
    return out


def chunk_list(data):
    pos = 0
    while pos < len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        yield cid, data[pos + 8:pos + 8 + size]
        pos += 8 + size


def chunk(cid, data):
    return struct.pack("<II", cid, len(data)) + data


def string_z(data, pos):
    end = data.index(b"\0", pos)
    return data[pos:end], end + 1


def read_graph(g):
    """Chunk 4: the header, its levels and where the vertices, edges, death points and cross tables start."""
    version, vertex_count, edge_count, point_count = struct.unpack_from("<BHII", g, 0)
    level_count = g[27]
    pos, levels = 28, []
    for _ in range(level_count):
        name, pos = string_z(g, pos)
        offset = g[pos:pos + 12]
        lid = g[pos + 12]
        section, pos = string_z(g, pos + 13)
        levels.append(dict(name=name, offset=offset, id=lid, section=section, guid=g[pos:pos + 16]))
        pos += 16
    nodes = pos
    edges = nodes + vertex_count * VERTEX
    points = edges + edge_count * EDGE
    return dict(version=version, vertex_count=vertex_count, edge_count=edge_count, point_count=point_count,
                guid=g[11:27], levels=levels, data=g, nodes=nodes, edges=edges, points=points,
                tables=points + point_count * POINT)


def vertex_level(graph, gvid):
    """Level id of a graph vertex (the low byte of the u32 at +24), None for a vertex outside the graph."""
    if gvid >= graph["vertex_count"]:
        return None
    return graph["data"][graph["nodes"] + gvid * VERTEX + 24]


def cross_table(graph, level_id):
    """A level's cross table, u32 size first; the tables follow the death points in level id order."""
    pos = graph["tables"]
    for level in sorted(graph["levels"], key=lambda l: l["id"]):
        size = struct.unpack_from("<I", graph["data"], pos)[0]
        if level["id"] == level_id:
            return graph["data"][pos:pos + size]
        pos += size
    raise SystemExit("no cross table for level %d" % level_id)


class Record:
    """One spawn record: the M_SPAWN packet (version 128) with the offsets of the fields a copy changes."""

    def __init__(self, raw):
        parts = chunks(raw)
        self.update = parts.get(1)
        spawn = parts[0]
        p = spawn[2:2 + struct.unpack_from("<H", spawn, 0)[0]]
        assert struct.unpack_from("<H", p, 0)[0] == M_SPAWN
        self.section, pos = string_z(p, 2)
        self.name_at = pos
        self.name, pos = string_z(p, pos)
        pos += 2  # game id, rp
        self.position = struct.unpack_from("<3f", p, pos)
        pos += 24 + 8  # position, angle; respawn time, id, parent, phantom
        flags, version = struct.unpack_from("<HH", p, pos)
        assert flags & M_SPAWN_VERSION and version == SPAWN_VERSION, (self.name, flags, version)
        pos += 8  # flags, version, game type, script version
        pos += 2 + struct.unpack_from("<H", p, pos)[0] + 2  # client data, spawn id
        self.state_size_at = pos
        self.state_at = pos + 2
        self.state_end = self.state_at + struct.unpack_from("<H", p, pos)[0]
        self.packet = bytearray(p)
        self.gvid = struct.unpack_from("<H", p, self.state_at)[0]
        # CSE_ALifeObject: graph vertex, distance, direct control, node, flags, ini string, story id, spawn story id
        self.ini_at = self.state_at + 18
        self.ini, after = string_z(p, self.ini_at)
        self.story_at = after
        self.alife_end = after + 8

    def set_name(self, name):
        self._replace(self.name_at, len(self.name) + 1, name + b"\0")
        self.name = name

    def set_gvid(self, gvid):
        struct.pack_into("<H", self.packet, self.state_at, gvid)
        self.gvid = gvid

    def clear_story_ids(self):
        struct.pack_into("<II", self.packet, self.story_at, 0xFFFFFFFF, 0xFFFFFFFF)

    def set_ini(self, ini):
        self._replace(self.ini_at, len(self.ini) + 1, ini + b"\0")
        self.ini = ini

    def changer_fields(self):
        """A level changer's destination: after the alife object part come the shapes (sphere: centre + radius,
        box: 4 vec3 of r_matrix), the restrictor type, then graph vertex, node, position, angles, level, point."""
        p, pos = self.packet, self.alife_end
        count = p[pos]
        pos += 1
        for _ in range(count):
            pos += 1 + (16 if p[pos] == 0 else 48)
        at = pos + 1
        node, = struct.unpack_from("<I", p, at + 2)
        position = struct.unpack_from("<3f", p, at + 6)
        angles = struct.unpack_from("<3f", p, at + 18)
        level, _ = string_z(p, at + 30)
        return dict(at=at, node=node, position=position, angles=angles, level=bytes(level))

    def to_restrictor(self):
        """A level changer as a plain space restrictor: the section renamed, the state cut after the restrictor
        type (se_restrictor writes nothing more)."""
        cut = self.changer_fields()["at"]
        self.packet[cut:self.state_end] = b""
        struct.pack_into("<H", self.packet, self.state_size_at, cut - self.state_at)
        self.state_end = cut
        delta = len(b"space_restrictor") - len(self.section)
        self.packet[2:2 + len(self.section)] = b"space_restrictor"
        for attr in ("name_at", "state_size_at", "state_at", "ini_at", "story_at", "alife_end", "state_end"):
            setattr(self, attr, getattr(self, attr) + delta)
        self.section = b"space_restrictor"

    def _replace(self, at, length, data):
        delta = len(data) - length
        self.packet[at:at + length] = data
        if at >= self.state_at:
            size = struct.unpack_from("<H", self.packet, self.state_size_at)[0]
            struct.pack_into("<H", self.packet, self.state_size_at, size + delta)
        else:
            self.state_size_at += delta
            self.state_at += delta
            self.ini_at += delta
        self.state_end += delta
        if at < self.story_at:
            self.story_at += delta
            self.alife_end += delta

    def bytes(self):
        out = chunk(0, struct.pack("<H", len(self.packet)) + bytes(self.packet))
        if self.update is not None:
            out += chunk(1, self.update)
        return out


def records(top):
    """Records of chunk 1 (the spawn graph's vertices)."""
    for _, vertex in chunk_list(chunks(top[1])[1]):
        yield Record(chunks(vertex)[1])


class Path:
    """A patrol path of chunk 3: name, and its points (name, position, flags, node, graph vertex) kept raw."""

    def __init__(self, raw):
        parts = chunks(raw)
        self.name = parts[0][:-1]
        body = chunks(parts[1])
        self.count = body[0]
        self.links = body.get(2, b"")
        self.points = {}
        for cid, data in chunk_list(body[1]):
            p = chunks(data)
            self.points[cid] = (p[0], bytearray(p[1]))

    def first_position(self):
        point = self.points[min(self.points)][1]
        return struct.unpack_from("<3f", point, point.index(b"\0") + 1)

    def _on_mesh(self):
        """(point, graph vertex offset) of the points on the AI map; a point off it (node -1) is used by position
        only and keeps whatever graph vertex xrAI left in it."""
        for _, point in self.points.values():
            pos = point.index(b"\0") + 1
            if struct.unpack_from("<I", point, pos + 16)[0] != 0xFFFFFFFF:
                yield point, pos + 20

    def gvids(self):
        for point, at in self._on_mesh():
            yield struct.unpack_from("<H", point, at)[0]

    def map_gvids(self, remap):
        for point, at in self._on_mesh():
            struct.pack_into("<H", point, at, remap[struct.unpack_from("<H", point, at)[0]])

    def bytes(self):
        points = b"".join(chunk(cid, chunk(0, vid) + chunk(1, bytes(point)))
                          for cid, (vid, point) in sorted(self.points.items()))
        body = chunk(0, self.count) + chunk(1, points) + chunk(2, self.links)
        return chunk(0, self.name + b"\0") + chunk(1, body)


def paths(top):
    for _, data in chunk_list(chunks(top[3])[1]):
        yield Path(data)
