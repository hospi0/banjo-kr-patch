"""Full Korean build of Banjo-Kazooie (USA Rev1).

  python tools/build.py [tsv_dir_or_file ...]   (default: my files/tsv)
  -> work/BK_KR.z64  (32 MB, expansion pak required)

Layout of the output ROM:
  0x0000000-0x1000000  original (patched code, checksums, header CRC)
  0x1000000-           relocated asset table + data (assetCache_init now points here)
  after that           Korean blob (hook code + glyphs) -> DMA'd to 0x80400000 by print_init
"""
import glob, os, re, struct, sys
sys.path.insert(0, os.path.dirname(__file__))
import bkrom, bkbuild as B, n64crc, rules, bdf, mips

ROOT = os.path.join(os.path.dirname(__file__), '..')
OUT = os.path.join(ROOT, 'work', 'BK_KR.z64')
NEW_ASSETS = 0x1000000
ROM_SIZE = 0x2000000
UI_FIXED = [(0x12B3C, b'\0'), (0x12B4C, b'\0')]   # 'S' after ' JIGSAW' / ' NOTE' (English plural)
ASCII_OK = set(' !"\'(),-./0123456789:;?ABCDEFGHIJKLMNOPQRSTUVWXYZ')   # glyphs that exist in font 0x6EB


def read_translations(paths):
    tr = {}
    files = []
    for p in paths:
        files += sorted(glob.glob(os.path.join(p, '*.tsv'))) if os.path.isdir(p) else [p]
    for f in files:
        with open(f, encoding='utf-8-sig') as fh:
            head = fh.readline().rstrip('\n').split('\t')
            ci = {n: i for i, n in enumerate(head)}
            for ln in fh:
                c = ln.rstrip('\n').split('\t')
                if len(c) <= ci['번역'] or not c[ci['번역']].strip():
                    continue
                tr[c[ci['위치']]] = (c[ci['구분']], c[ci['원문']], c[ci['번역']])
    return tr, files


def to_bytes(t, cmap):
    """display text with {FD}x / {XX} tokens -> game bytes"""
    out = bytearray()
    i = 0
    while i < len(t):
        m = re.match(r'\{([0-9A-F]{2})\}', t[i:])
        if m:
            out.append(int(m.group(1), 16)); i += 4; continue
        out += B.encode_kr(t[i], cmap); i += 1
    return bytes(out)


def main():
    print(rules.BANNER)
    global OUT
    args = sys.argv[1:]
    if args and args[-1].lower().endswith('.z64'):
        OUT = args.pop()
    paths = args or [os.path.join(ROOT, 'my files', 'tsv')]
    tr, files = read_translations(paths)
    print('번역 파일 %d개, 번역된 행 %d' % (len(files), len(tr)))

    rom = bytearray(bkrom.load_rom())
    tab = bkrom.asset_table(rom)
    font = bdf.BdfFont(B.FONT_PATH)
    g0 = bkrom.font_glyphs(bkrom.asset(rom, tab, bkrom.FONT_ASSET))
    adv = {chr(0x21 + i): a for i, (a, _, _, _) in enumerate(g0)}
    glyph_ok = lambda c: c in ASCII_OK or (0xAC00 <= ord(c) <= 0xD7A3 and ord(c) in font.glyphs)

    # validate everything first (stop on any error)
    fixed, ui, errs, warns = {}, {}, [], []
    for loc, (kind, src, kr) in tr.items():
        k, e, w = rules.validate(src, kr, kind, adv, glyph_ok)
        if kind == 'UI':                  # keep the layout spaces of the original ("GAME ", " JIGSAW")
            k = k.strip()
            k = ' ' * (len(src) - len(src.lstrip(' '))) + k + ' ' * (len(src) - len(src.rstrip(' ')))
            ui[loc] = (src, k)
            errs += ['%s: %s' % (loc, x) for x in e]
            continue
        errs += ['%s: %s' % (loc, x) for x in e]
        warns += ['%s: %s' % (loc, x) for x in w]
        fixed[loc] = k
    for w in warns[:50]:
        print('경고', w)
    if errs:
        for e in errs:
            print('오류', e)
        raise SystemExit('규칙 위반 %d건 — 빌드 중단' % len(errs))
    chars = sorted({c for t in list(fixed.values()) + [k for _, k in ui.values()]
                    for c in rules.TOKEN.sub('', t) if ord(c) >= 0x80})
    assert len(chars) <= (B.LEAD1 - B.LEAD0) * B.NTRAIL
    cmap = {c: i for i, c in enumerate(chars)}

    # rebuild text assets
    by_asset = {}
    for loc, t in fixed.items():
        a, s, i = loc.split(':')
        by_asset.setdefault(int(a, 16), []).append((s, int(i), t))
    replaced = {}
    for k, items in sorted(by_asset.items()):
        r = bkrom.asset(rom, tab, k)
        if bkrom.is_quiz(r):
            _, ent, _ = bkrom.parse_quiz(r)
            ent = list(ent)
            for s, i, t in items:
                ent[i] = (ent[i][0], to_bytes(t, cmap) + b'\0')
            raw = B.build_quiz(r[:5], ent)
        else:
            _, secs, _ = bkrom.parse_dialog(r)
            secs = [[[e] for e in x] for x in secs]       # each slot -> list of entries (page split)
            for s, i, t in items:
                cmd = secs[int(s)][i][0][0]
                secs[int(s)][i] = [(cmd, to_bytes(p, cmap) + b'\0') for p in rules.split_pages(t)]
            secs = [[e for slot in x for e in slot] for x in secs]
            assert all(len(x) < 256 for x in secs)
            raw = B.build_dialog(secs)
        replaced[k] = B.rzip(raw)
    region = B.build_asset_region(rom, tab, replaced)

    # ROM: extend, place assets and blob
    rom += bytes(ROM_SIZE - len(rom))
    rom[NEW_ASSETS:NEW_ASSETS + len(region)] = region
    blob_rom = (NEW_ASSETS + len(region) + 0xFFF) & ~0xFFF
    glyphs = B.render_glyphs(chars)
    bglyphs = B.render_bold_glyphs(chars)          # same index g in both tables (font decides which)
    code, _ = B.hook_code(0, 0)
    gly_off = (0x10 + len(code) + 7) & ~7
    bgly_off = (gly_off + len(glyphs) + 7) & ~7
    str_off = bgly_off + len(bglyphs)
    code, syms = B.hook_code(B.KR_RAM + gly_off, B.KR_RAM + bgly_off)

    # UI strings in core2 data: in place if they fit, else into the blob with references repointed
    drefs, crefs, c2d = B.core2_ui_refs(rom)
    c2t_orig, _ = B.unrzip_at(rom, B.CORE2_TEXT)
    text_p, data_p, strings, moved, ui_errs = [], [], b'', [], []
    for loc, (src, k) in sorted(ui.items()):
        o = int(loc[2:], 16)
        end = c2d.index(0, o)
        assert c2d[o:end].decode() == src, loc
        lim = end
        while lim < len(c2d) and c2d[lim] == 0:
            lim += 1
        b = to_bytes(k, cmap) + b'\0'
        # File select strings (< 0x14000) go through strcat / the zoombox line buffers: they must stay
        # within the ORIGINAL length (2026-10-05: '삭제하세요!' 50 B broke into '삭제하세있ㅌ',
        # ': 비어있음' left a stray '음'). Pause menu / cast names are drawn straight from the pointer,
        # so the zero padding after them may be used. Nothing is relocated any more.
        limit = len(src) + 1 if o < 0x14000 else lim - o
        if len(b) > limit:
            ui_errs.append('%s: %d바이트 > 원문 한도 %d (%s)' % (loc, len(b) - 1, limit - 1, k))
            continue
        data_p.append((o, b + bytes(lim - o - len(b))))
    for o, b in UI_FIXED:                       # plural 'S' appended by the file select code
        data_p.append((o, b))
    if ui_errs:
        for e in ui_errs:
            print('오류', e)
        raise SystemExit('UI 길이 초과 %d건 — 빌드 중단' % len(ui_errs))

    blob = bytes(0x10) + code
    blob += bytes(gly_off - len(blob)) + glyphs
    blob += bytes(bgly_off - len(blob)) + bglyphs + strings
    blob += bytes(-len(blob) % 8)
    assert blob_rom + len(blob) <= ROM_SIZE and len(blob) <= 0x400000
    rom[blob_rom:blob_rom + len(blob)] = blob

    patches = B.core2_patches(syms, blob_rom, len(blob))
    patches += B.asset_base_patches(NEW_ASSETS)
    patches.append(B.print_len_patch())
    used, slot = B.rebuild_code(rom, patches + text_p, data_p)
    c1, c2 = n64crc.fix(rom)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'wb').write(rom)
    print('에셋 %d개 교체, 영역 %d B @0x%X' % (len(replaced), len(region), NEW_ASSETS))
    print('한글 글리프 %d자, 블롭 %d B @0x%X' % (len(chars), len(blob), blob_rom))
    print('UI %d개 (제자리 %d · 확장 메모리로 옮김 %d: %s)' % (len(ui), len(ui) - len(moved), len(moved), ' '.join(moved)))
    print('core2 %d / %d, 헤더 CRC %08X %08X' % (used, slot, c1, c2))
    print('->', os.path.abspath(OUT))


if __name__ == '__main__':
    main()
