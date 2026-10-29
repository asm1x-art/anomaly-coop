# The static visuals of a compiled level ("level" file, chunk 3), with their shader/textures (chunk 2), type and
# world bounds; filtered to a box and optionally by texture words.
#   levelvis.py <level dir> [x0 x1 y0 y1 z0 z1] [words]
import struct
import sys

TYPES = {0: 'normal', 1: 'hierarchy', 2: 'progressive', 6: 'lod', 7: 'tree_st', 11: 'tree_pm'}


def chunks(data, base=0, end=None):
    p, end = base, len(data) if end is None else end
    while p + 8 <= end:
        cid, sz = struct.unpack_from('<II', data, p)
        yield cid & 0x7fffffff, p + 8, sz
        p += 8 + sz


def level(level_dir):
    d = open(level_dir + '/level', 'rb').read()
    top = {cid: (off, sz) for cid, off, sz in chunks(d)}
    off, sz = top[2]
    n = struct.unpack_from('<I', d, off)[0]
    shaders, p = [], off + 4
    for _ in range(n):
        e = d.index(b'\0', p)
        shaders.append(d[p:e].decode('latin1'))
        p = e + 1
    off, sz = top[3]
    visuals = []
    for idx, voff, vsz in chunks(d, off, off + sz):
        sub = {cid: (o, s) for cid, o, s in chunks(d, voff, voff + vsz)}
        o, _ = sub[1]
        ver, typ, shader = struct.unpack_from('<BBH', d, o)
        box = struct.unpack_from('<6f', d, o + 4)
        visuals.append(dict(idx=idx, type=typ, shader=shader, box=box, header=o, sub=sub))
    return d, shaders, visuals


if __name__ == '__main__':
    d, shaders, visuals = level(sys.argv[1])
    area = list(map(float, sys.argv[2:8])) if len(sys.argv) >= 8 else None
    words = sys.argv[8].split(',') if len(sys.argv) > 8 else []
    print(f'{len(shaders)} shaders, {len(visuals)} visuals')
    for v in visuals:
        b = v['box']
        if area and not (b[3] >= area[0] and b[0] <= area[1] and b[4] >= area[2] and b[1] <= area[3] and b[5] >= area[4] and b[2] <= area[5]):
            continue
        name = shaders[v['shader']] if v['shader'] < len(shaders) else '?'
        if words and not any(w in name for w in words):
            continue
        size = (b[3] - b[0], b[4] - b[1], b[5] - b[2])
        print(f"{v['idx']:5d} {TYPES.get(v['type'], v['type']):11s} {name:60s} "
              f"x {b[0]:7.2f}..{b[3]:7.2f} y {b[1]:6.2f}..{b[4]:6.2f} z {b[2]:7.2f}..{b[5]:7.2f}  size {size[0]:.1f}x{size[1]:.1f}x{size[2]:.1f}  "
              f"chunks {sorted(v['sub'])}")
