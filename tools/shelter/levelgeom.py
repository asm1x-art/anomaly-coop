# Triangles of a compiled level's static visuals: level.geom vertex/index buffers (chunks 9, 10) read through each
# visual's OGF_GCONTAINER (chunk 21: vb, vertex base, vertex count, ib, index base, index count).
import struct

import numpy as np

from levelvis import chunks

SIZES = {0: 4, 1: 8, 2: 12, 3: 16, 4: 4, 5: 4, 6: 4, 7: 8, 8: 4, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 14: 4, 15: 4, 16: 8}


class Geom:
    def __init__(self, path):
        d = open(path, 'rb').read()
        top = {cid: (off, sz) for cid, off, sz in chunks(d)}
        self.data = d
        self.vbs, self.ibs = [], []      # (positions array, file offset of vertex 0, stride) / (file offset of index 0, count)
        off, _ = top[9]
        n = struct.unpack_from('<I', d, off)[0]
        p = off + 4
        for _ in range(n):
            stride, pos_off = 0, None
            while True:
                stream, eoff, typ, meth, usage, uidx = struct.unpack_from('<HHBBBB', d, p)
                p += 8
                if stream == 0xFF:
                    break
                stride = max(stride, eoff + SIZES[typ])
                if usage == 0 and pos_off is None:
                    assert typ == 2, typ
                    pos_off = eoff
            count = struct.unpack_from('<I', d, p)[0]
            p += 4
            raw = np.frombuffer(d, np.uint8, count * stride, p).reshape(count, stride)
            pos = raw[:, pos_off:pos_off + 12].copy().view('<f4').reshape(count, 3).astype(np.float64)
            self.vbs.append((pos, p, stride))
            p += count * stride
        off, _ = top[10]
        n = struct.unpack_from('<I', d, off)[0]
        p = off + 4
        for _ in range(n):
            count = struct.unpack_from('<I', d, p)[0]
            self.ibs.append((p + 4, count))
            p += 4 + count * 2

    def container(self, level_data, visual):
        o, _ = visual['sub'][21]
        return struct.unpack_from('<6I', level_data, o)

    def triangles(self, level_data, visual):
        vb, vbase, vcount, ib, ibase, icount = self.container(level_data, visual)
        pos = self.vbs[vb][0]
        start = self.ibs[ib][0] + ibase * 2
        idx = np.frombuffer(self.data, '<u2', icount, start).astype(np.int64) + vbase
        return pos[idx].reshape(-1, 3, 3)
