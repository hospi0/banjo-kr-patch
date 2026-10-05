"""Banjo-Kazooie (USA Rev1) ROM access: asset table, rarezip, dialogue blocks, font."""
import struct, zlib

ROM_PATH = r'C:\claude\roms\n64\Banjo-Kazooie (USA) (Rev 1).z64'
TABLE = 0x5E90          # [BE32 count][ffffffff] + count*{BE32 off, u16 comp, u16 type}
FONT_ASSET = 0x6EB      # dialogue font: 75 glyphs 0x21..0x6B, I8, height 13


def load_rom(path=ROM_PATH):
    return open(path, 'rb').read()


def asset_table(rom):
    n = struct.unpack_from('>I', rom, TABLE)[0]
    ent = TABLE + 8
    base = ent + n * 8
    out = []
    for k in range(n):
        off, comp, typ = struct.unpack_from('>IHH', rom, ent + k * 8)
        out.append((base + off, comp, typ))
    # size = next entry start - this start (last entry has no data)
    return [(p, (out[k + 1][0] - p) if k + 1 < n else 0, c, t)
            for k, (p, c, t) in enumerate(out)]


def unzip(blob):
    assert blob[:2] == b'\x11\x72', blob[:2].hex()
    size = struct.unpack_from('>I', blob, 2)[0]
    r = zlib.decompressobj(-15).decompress(blob[6:])
    assert len(r) >= size
    return r[:size]


def asset(rom, tab, k):
    p, size, comp, typ = tab[k]
    blob = rom[p:p + size]
    return unzip(blob) if comp else blob


def parse_dialog(r):
    """-> (nlang, [sections]); section = list of (cmd, bytes_without_nul).
    Layout: [nlang][u16le offset]*nlang, at offset: two sections, each
    [count] + count*{cmd, len, data[len]} (text data ends with NUL)."""
    nlang = r[0]
    offs = [struct.unpack_from('<H', r, 1 + i * 2)[0] for i in range(nlang)]
    p = offs[0]
    secs = []
    for _ in range(2):
        cnt = r[p]; p += 1
        ent = []
        for _ in range(cnt):
            cmd, ln = r[p], r[p + 1]
            ent.append((cmd, r[p + 2:p + 2 + ln]))
            p += 2 + ln
        secs.append(ent)
    return nlang, secs, p


def is_dialog(r):
    if len(r) < 8 or r[0] != 1 or r[1:3] != b'\x03\x00':
        return False
    try:
        _, secs, end = parse_dialog(r)
    except IndexError:
        return False
    return end <= len(r) and len(r) - end < 16 and any(secs)


def parse_quiz(r):
    """Grunty quiz: [nlang][2 bytes][u16le offset]*nlang, at offset
    [count] + count*{cmd, len, data}. cmd 0x80 = question line, 0x81.. = answers."""
    off = struct.unpack_from('<H', r, 3)[0]
    p = off
    cnt = r[p]; p += 1
    ent = []
    for _ in range(cnt):
        cmd, ln = r[p], r[p + 1]
        ent.append((cmd, r[p + 2:p + 2 + ln]))
        p += 2 + ln
    return r[1:3], ent, p


def is_quiz(r):
    if len(r) < 8 or r[0] != 1 or struct.unpack_from('<H', r, 3)[0] != 5:
        return False
    try:
        _, ent, end = parse_quiz(r)
    except IndexError:
        return False
    return end == len(r) and ent and all(c >= 0x80 for c, _ in ent)


def font_glyphs(r):
    """-> list of (advance, tex_w, h, pixels I8)."""
    p = 0x2C
    g = []
    while p + 8 <= len(r):
        adv, _y, w, h = struct.unpack_from('>hhHH', r, p)
        q = (p + 8 + 7) & ~7
        g.append((adv, w, h, r[q:q + w * h]))
        p = q + w * h
    return g
