r"""Loading screens of the raid's levels: the originals' own, under the copies' names. The engine shows a random one of
textures\intro\intro_<level>_<n>.dds (n from 1) while a level loads; a copy (raid_*) has none, so the originals'
(intro_l10_limansk_1.dds...) are taken out of Anomaly's texture archives and written as intro_raid_limansk_1.dds...
  raid_intro.py <converter.exe> <Anomaly db\textures dir> <out gamedata dir>
The converter is Anomaly's tools\converter.exe (X-Ray db unpacker); only textures\intro\ is unpacked, into a
temporary folder next to the output, removed after.
"""
import glob
import os
import re
import shutil
import subprocess
import sys

from raid_copy import LEVELS


def main():
    converter, db_textures, out = sys.argv[1:4]
    temp = os.path.join(out, "_unpack_intro")
    os.makedirs(temp, exist_ok=True)
    try:
        for db in sorted(glob.glob(os.path.join(db_textures, "textures*.db*"))):
            subprocess.run([converter, "-unpack", "-xdb", db, "-dir", temp, "-flt", "textures\\intro\\"], check=True,
                           cwd=os.path.dirname(converter), stdout=subprocess.DEVNULL)
        src = os.path.join(temp, "textures", "intro")
        dst = os.path.join(out, "textures", "intro")
        os.makedirs(dst, exist_ok=True)
        for orig, copy in LEVELS.items():
            orig, copy = orig.decode(), copy.decode()
            # intro_<orig>_<n>.dds only: l12_stancia's must not take l12_stancia_2's (intro_l12_stancia_2_1)
            pattern = re.compile(r"^intro_%s_(\d+)\.dds$" % re.escape(orig), re.I)
            found = sorted((int(m.group(1)), name) for name in os.listdir(src) if (m := pattern.match(name)))
            for n, name in found:
                shutil.copyfile(os.path.join(src, name), os.path.join(dst, "intro_%s_%d.dds" % (copy, n)))
            print("%s: %d loading screens from %s" % (copy, len(found), orig))
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
