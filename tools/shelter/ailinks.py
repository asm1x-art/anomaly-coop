# middle-floor AI nodes (y -1..6) linked to nodes outside that band: where the floor connects to stairs
import math, struct, sys
ai = open(sys.argv[1], 'rb').read()
_, count, size, size_y = struct.unpack_from('<IIff', ai, 0)
minx, miny, minz = struct.unpack_from('<3f', ai, 16)
maxz = struct.unpack_from('<f', ai, 36)[0]
row = int(math.floor((maxz - minz) / size + 1e-6 + 1.5))
pos, links = [], []
for i in range(count):
    rec = ai[56 + i * 23: 56 + i * 23 + 23]
    bits = int.from_bytes(rec[:12], 'little')
    links.append([(bits >> (23 * k)) & 0x7fffff for k in range(4)])
    p = rec[18:23]
    xz = p[0] | (p[1] << 8) | (p[2] << 16)
    pos.append((minx + (xz // row) * size, miny + struct.unpack_from('<H', p, 3)[0] / 65535 * size_y, minz + (xz % row) * size))
mid = lambda y: -1 <= y <= 6
seen = {}
for i, (x, y, z) in enumerate(pos):
    if not mid(y):
        continue
    for j in links[i]:
        if j < count and not mid(pos[j][1]):
            key = (round(x), round(z))
            seen.setdefault(key, []).append((x, y, z, pos[j][1]))
for k, v in sorted(seen.items()):
    x, y, z, y2 = v[0]
    print(f'{x:7.2f} {y:6.2f} {z:7.2f} -> y {y2:6.2f}  ({len(v)} links)')
