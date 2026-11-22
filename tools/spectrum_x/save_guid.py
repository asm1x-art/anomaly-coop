"""The spawn GUID a save was made with (the engine prints it as two u64: '%016llx%016llx').
  python save_guid.py <save.scop> [<expected guid>]   -> prints it; exit 1 if it differs from the expected one
A save whose spawn differs from the game's (other spawn overlay packs / levels) dies at load with "Saved game doesn't
correspond to the spawn": check before a launch. The stand's current GUID is kept in spawn_guid.txt (written by
the stand kit from a save that loaded)."""
import struct, sys, lzo
b = open(sys.argv[1], "rb").read()
sig, ver, src = struct.unpack_from("<iII", b, 0)
d = lzo.decompress(b[12:], False, src)
want = sys.argv[2] if len(sys.argv) > 2 else None
if want:
    raw = bytes.fromhex(want[:16])[::-1] + bytes.fromhex(want[16:])[::-1]
    ok = raw in d
    print(("matches " if ok else "DIFFERS from ") + want)
    sys.exit(0 if ok else 1)
print("(give the expected guid to compare)")
