r"""Writes gamedata/textures/pfx/coop/afx_dot.dds: a soft round dot (gaussian falloff to zero at the edge) for the
artefacts' ground particles, 64x64 uncompressed BGRA with its full mip chain, so it stays soft close up and far away
(Anomaly's pfx\snowo, used before, is 32x32 with four 16 px blobs: big blocky squares near the camera).
  python tools/artifact_fx/make_dot.py
"""
import math
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "gamedata", "textures", "pfx", "coop", "afx_dot.dds")
SIZE = 64


def level(n):
    px = bytearray()
    c = (n - 1) / 2.0
    for y in range(n):
        for x in range(n):
            r = math.hypot(x - c, y - c) / (n / 2.0)
            v = 0.0 if r >= 1 else math.exp(-4.5 * r * r) * (1 - r * r)
            b = int(round(255 * v))
            px += bytes((b, b, b, b))  # B, G, R, A
    return bytes(px)


def main():
    mips = []
    n = SIZE
    while n >= 1:
        mips.append(level(n))
        n //= 2
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000  # caps, height, width, pitch, pixelformat, mipmapcount
    pf = struct.pack("<II4sIIIII", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    hdr = struct.pack("<I", 124) + struct.pack("<IIIIII", flags, SIZE, SIZE, SIZE * 4, 0, len(mips)) + b"\0" * 44 + pf
    hdr += struct.pack("<IIIII", 0x1000 | 0x8 | 0x400000, 0, 0, 0, 0)  # texture, complex, mipmap
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(b"DDS " + hdr + b"".join(mips))
    print(OUT, len(mips), "mips")


if __name__ == "__main__":
    main()
