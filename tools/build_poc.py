"""PoC: Captain Blubber's first line in Korean via 2-byte hook + expansion-RAM glyphs.
Output: work/BK_KR_poc.z64"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(__file__))
import bkrom, bkbuild as B, n64crc

OUT = os.path.join(os.path.dirname(__file__), '..', 'work', 'BK_KR_poc.z64')
BLOB_ROM = 0xFDE000
POC = {  # (asset, sec, idx) -> text
    (0x90B, 0, 0): '어이! 나는 블러버 선장이다. 배가 부서져서 보물을 잃어버렸어.',
    (0x90B, 0, 2): '아르르... 난 헤엄을 못 쳐! 도와줄래?',
    # Bottles, first molehill next to Banjo's house (seen within a minute of a new game)
    (0xA35, 0, 0): '잘 들어! 난 보틀즈야.',
}


def main():
    rom = bytearray(bkrom.load_rom())
    tab = bkrom.asset_table(rom)
    # glyph set
    chars = sorted({c for t in POC.values() for c in t if ord(c) >= 0x80})
    cmap = {c: i for i, c in enumerate(chars)}
    glyphs = B.render_glyphs(chars)
    # blob = [PEND .. pad to 0x10][code][align 8][glyphs]
    code, draw, getspr = B.hook_code(0)          # size probe
    gly_off = (0x10 + len(code) + 7) & ~7
    code, draw, getspr = B.hook_code(B.KR_RAM + gly_off)
    blob = bytes(0x10) + code
    blob += bytes(gly_off - len(blob)) + glyphs
    blob += bytes(-len(blob) % 8)
    assert BLOB_ROM + len(blob) <= len(rom) and not any(rom[BLOB_ROM:BLOB_ROM + len(blob)].strip(b'\xff'))
    rom[BLOB_ROM:BLOB_ROM + len(blob)] = blob
    # code
    used, slot = B.rebuild_code(rom, B.core2_patches(draw, getspr, BLOB_ROM, len(blob)))
    print('core2 compressed %d / slot %d' % (used, slot))
    # dialog asset(s)
    for k in sorted({a for a, _, _ in POC}):
        r = bkrom.asset(rom, tab, k)
        _, secs, _ = bkrom.parse_dialog(r)
        assert B.build_dialog(secs) == r[:len(B.build_dialog(secs))]
        secs = [list(s) for s in secs]
        for (a, si, i), t in POC.items():
            if a == k:
                secs[si][i] = (secs[si][i][0], B.encode_kr(t, cmap) + b'\0')
        z = B.rzip(B.build_dialog(secs))
        p, size, comp, _ = tab[k]
        assert comp and len(z) <= size, 'asset %X: %d > slot %d' % (k, len(z), size)
        rom[p:p + size] = z + bytes(size - len(z))
        print('asset %X: %d / slot %d' % (k, len(z), size))
    print('header crc', [hex(x) for x in n64crc.fix(rom)])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'wb').write(rom)
    print('glyphs', len(chars), 'blob', len(blob), '->', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
