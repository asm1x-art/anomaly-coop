# The shelter's cleaning zones for the game (scripts\shelter\cleaning.ltx): each zone's static visuals and their
# collision triangles (all three corners on the visual's vertices), as "first-last" ranges into level.cform; and the
# items the cleaning puts into the stash for what it takes away (Hideout Furniture's tables for the level's ones).
#   cleaning.py <level dir> <out.ltx>
import struct
import sys

import numpy as np

from levelgeom import Geom
from levelvis import level

ZONES = [
    ('start', "the lower hall, the water hall: open from the first visit (the doors lying on the floor are props), the rebar of the hall's broken corner", [339, 361, 274, 70, 344, 345]),
    ('corridor', "the north corridor and its two southern side rooms (open to it), behind point 3's mound (their "
     "furniture is movable props: props.py)", [57, 200]),
    # the side rooms behind the doorway mounds (8..13): each opens when its mound is dug out
    ('room_8', 'the north-west side room', [218]),
    ('room_10', 'the west side room in the middle', [237]),
    ('room_11', 'the east side room in the middle', [273]),
    ('room_12', 'the south-west side room', [266]),
    # open with their lifts (shelter_lift.script). The east hall's floor (370) and the mound at the tunnel's east end (140)
    # stay: there's no floor under them. The water (49) is one visual over the whole tunnel, past the gate too
    ('top', 'the top floor: its rubble, the broken ceiling and its rebar, hoses, cables, rusty sheets (the ducts are props)',
     [395, 396, 424, 528, 64, 419, 420, 421, 422, 423, 529, 530]),
    ('low', "the lower floor: the tunnel's water and slime", [49, 557]),
]

level_dir, out = sys.argv[1], sys.argv[2]
d, shaders, visuals = level(level_dir)
g = Geom(level_dir + '/level.geom')
cf = open(level_dir + '/level.cform', 'rb').read()
_, vc, fc = struct.unpack_from('<III', cf, 0)
cverts = np.frombuffer(cf, '<f4', vc * 3, 36).reshape(vc, 3).astype(np.float64)
cfaces = np.frombuffer(cf, '<u4', fc * 4, 36 + vc * 12).reshape(fc, 4)
ckey = [tuple(k) for k in np.round(cverts * 200).astype(np.int64)]


def ranges(idx):
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append(f'{start}-{prev}' if prev > start else str(start))
            start = prev = i
    if start is not None:
        out.append(f'{start}-{prev}' if prev > start else str(start))
    return out


lines = ['; The shelter\'s cleaning (scripts\\shelter.script): what the laptop\'s "clean up" takes out of bunker_a1, by zone.',
         '; visuals: indices of its static visuals ("level" file); triangles: their collision triangles in level.cform;',
         '; items: what the cleaning puts into the stash for what it takes away (skipped where the section is missing).',
         '; Made from the level files by a script (tools\\shelter\\cleaning.py); the indices only fit these files.', '']
for name, comment, ids, *items in ZONES:
    tris = set()
    for i in ids:
        T = g.triangles(d, visuals[i])
        vk = set(map(tuple, np.round(T.reshape(-1, 3) * 200).astype(np.int64)))
        tris |= {n for n, (a, b, c, _) in enumerate(cfaces) if ckey[a] in vk and ckey[b] in vk and ckey[c] in vk}
    r = ranges(sorted(tris))
    print(f'{name}: {len(tris)} triangles in {len(r)} ranges')
    lines += [f'; {comment}', f'[{name}]', 'visuals = ' + ', '.join(map(str, ids)), 'triangles = ' + ','.join(r)]
    lines += ['items = ' + items[0]] if items else []
    lines += ['']
open(out, 'w', newline='\r\n').write('\n'.join(lines))
