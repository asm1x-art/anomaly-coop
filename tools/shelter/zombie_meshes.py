# The shelter's zombies (gamedata/configs/gameplay/character_desc_shelter.xml) in suits no zombie model has: a copy of
# the stalker model with the zombies' animations added to its motion references (the last top-level chunk,
# OGF_S_MOTION_REFS2: u32 count, then the names). Without "actors\zombied_animation" a zombified stalker moves like a
# live one.
#   zombie_meshes.py <dir with the original models> <gamedata dir>
# The originals come out of the game's archives under these names (path separators as "__"):
#   actors__stalker_merc__stalker_merc4nosorog.ogf, actors__stalker_neutral__stalker_neutral_nauchniy.ogf
import os
import struct
import sys

MODELS = {
    'actors__stalker_merc__stalker_merc4nosorog.ogf': 'meshes/actors/stalker_zombak/shelter_zombied_nosorog.ogf',
    'actors__stalker_neutral__stalker_neutral_nauchniy.ogf': 'meshes/actors/stalker_zombak/shelter_zombied_seva.ogf',
}
ZOMBIE = b'actors\\zombied_animation'
OGF_S_MOTION_REFS2 = 24

src_dir, gamedata = sys.argv[1], sys.argv[2]
for src, dst in MODELS.items():
    data = open(os.path.join(src_dir, src), 'rb').read()
    p = 0
    while p + 8 <= len(data):
        cid, size = struct.unpack_from('<II', data, p)
        if cid & 0x7fffffff == OGF_S_MOTION_REFS2:
            break
        p += 8 + size
    else:
        raise SystemExit(f'{src}: no motion references')
    count = struct.unpack_from('<I', data, p + 8)[0]
    names = data[p + 12:p + 8 + size].split(b'\0')[:count]
    if ZOMBIE not in names:
        names.append(ZOMBIE)
    body = struct.pack('<I', len(names)) + b''.join(n + b'\0' for n in names)
    out = data[:p] + struct.pack('<II', OGF_S_MOTION_REFS2, len(body)) + body + data[p + 8 + size:]
    path = os.path.join(gamedata, dst)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').write(out)
    print(f'{dst}: {[n.decode() for n in names]}')
