r"""The file table of a game archive (.db / .db0...), read the way the engine does (CLocatorAPI::LoadArchive):
chunk 666 is the header (an ltx), chunk 1 the table, packed with LZHUF (src\xrCore\LzHuf.cpp).
  db_list.py <archive>...        path<TAB>size<TAB>packed size<TAB>crc, one file a line (gamedata paths, lower case, /)
"""
import struct
import sys

N, F, THRESHOLD = 4096, 60, 2
N_CHAR = 256 - THRESHOLD + F
T = N_CHAR * 2 - 1
R = T - 1
MAX_FREQ = 0x4000
P_LEN = [3] + [4] * 3 + [5] * 8 + [6] * 12 + [7] * 24 + [8] * 16
D_CODE, D_LEN = [], []
for _code, _len in enumerate(P_LEN):
    D_CODE += [_code] * (1 << (8 - _len))
    D_LEN += [_len] * (1 << (8 - _len))


def lzhuf_decode(src):
    size = struct.unpack_from("<I", src)[0]
    out = bytearray()
    if not size:
        return bytes(out)
    freq = [0] * (T + 1)
    prnt = [0] * (T + N_CHAR + 1)
    son = [0] * T
    for i in range(N_CHAR):
        freq[i], son[i], prnt[i + T] = 1, i + T, i
    i, j = 0, N_CHAR
    while j <= R:
        freq[j] = freq[i] + freq[i + 1]
        son[j] = i
        prnt[i] = prnt[i + 1] = j
        i += 2
        j += 1
    freq[T] = 0xFFFF
    prnt[R] = 0
    pos, end = 4, len(src)
    getbuf = getlen = 0

    def getbit():
        nonlocal pos, getbuf, getlen
        while getlen <= 8:
            b = src[pos] if pos < end else 0
            pos += 1
            getbuf |= b << (8 - getlen)
            getlen += 8
        bit = (getbuf >> 15) & 1
        getbuf = (getbuf << 1) & 0xFFFF
        getlen -= 1
        return bit

    def getbyte():
        nonlocal pos, getbuf, getlen
        while getlen <= 8:
            b = src[pos] if pos < end else 0
            pos += 1
            getbuf |= b << (8 - getlen)
            getlen += 8
        byte = (getbuf >> 8) & 0xFF
        getbuf = (getbuf << 8) & 0xFFFF
        getlen -= 8
        return byte

    def reconst():
        j = 0
        for i in range(T):
            if son[i] >= T:
                freq[j] = (freq[i] + 1) // 2
                son[j] = son[i]
                j += 1
        i, j = 0, N_CHAR
        while j < T:
            f = freq[i] + freq[i + 1]
            freq[j] = f
            k = j - 1
            while f < freq[k]:
                k -= 1
            k += 1
            freq[k + 1:j + 1] = freq[k:j]
            freq[k] = f
            son[k + 1:j + 1] = son[k:j]
            son[k] = i
            i += 2
            j += 1
        for i in range(T):
            k = son[i]
            if k >= T:
                prnt[k] = i
            else:
                prnt[k] = prnt[k + 1] = i

    def update(c):
        if freq[R] == MAX_FREQ:
            reconst()
        c = prnt[c + T]
        while True:
            freq[c] += 1
            k = freq[c]
            l = c + 1
            if k > freq[l]:
                l += 1
                while k > freq[l]:
                    l += 1
                l -= 1
                freq[c] = freq[l]
                freq[l] = k
                i = son[c]
                prnt[i] = l
                if i < T:
                    prnt[i + 1] = l
                j = son[l]
                son[l] = i
                prnt[j] = c
                if j < T:
                    prnt[j + 1] = c
                son[c] = j
                c = l
            c = prnt[c]
            if c == 0:
                break

    text = bytearray(b" " * (N - F)) + bytearray(F)
    r = N - F
    while len(out) < size:
        c = son[R]
        while c < T:
            c = son[c + getbit()]
        c -= T
        update(c)
        if c < 256:
            out.append(c)
            text[r] = c
            r = (r + 1) & (N - 1)
        else:
            i = getbyte()
            code = D_CODE[i] << 6
            for _ in range(D_LEN[i] - 2):
                i = (i << 1) + getbit()
            i = (r - (code | (i & 0x3F)) - 1) & (N - 1)
            for k in range(c - 255 + THRESHOLD):
                b = text[(i + k) & (N - 1)]
                out.append(b)
                text[r] = b
                r = (r + 1) & (N - 1)
    return bytes(out[:size])


def chunk(f, wanted):
    f.seek(0)
    while True:
        head = f.read(8)
        if len(head) < 8:
            return None
        cid, size = struct.unpack("<II", head)
        if cid & 0x7FFFFFFF == wanted:
            data = f.read(size)
            return lzhuf_decode(data) if cid & 0x80000000 else data
        f.seek(size, 1)


def table(path):
    """[(gamedata path, size, packed size, crc, offset)] of an archive"""
    with open(path, "rb") as f:
        data = chunk(f, 1)
    out, pos = [], 0
    while pos < len(data):
        size = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        real, packed, crc = struct.unpack_from("<III", data, pos)
        name = data[pos + 12:pos + size - 4].decode("cp1251").replace("\\", "/").lower()
        offset = struct.unpack_from("<I", data, pos + size - 4)[0]
        pos += size
        out.append((name, real, packed, crc, offset))
    return out


def header(path):
    with open(path, "rb") as f:
        data = chunk(f, 666)
    return data.decode("cp1251") if data else ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for archive in sys.argv[1:]:
        for name, real, packed, crc, _ in table(archive):
            print(f"{name}\t{real}\t{packed}\t{crc:08x}")
