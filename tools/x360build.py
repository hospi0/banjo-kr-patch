"""반조-카주이 XBLA(360) 한글 빌더 — 한글을 «일본어» 언어 칸에 넣는다 (Xenia, user_language = 일본어).

python tools/x360build.py <번역 tsv 폴더 또는 파일> <출력 폴더> [--write]

구조 (docs/00_이어하기.md «XBLA» 참고)
  * 일본어 대사 = FD 6A + 1바이트 글리프 id (좌표표 = 에셋 0x6EA, 텍스처 = 표 첫 u32)
  * 한글 = 선행 바이트 0xF0~0xF3 + 후행(0x01~0xFF, 0x20·0xFD 제외) → id = (선행-0xEF)*256 + 후행
    선행 바이트는 쪽 레지스터(+0x438)를 세우고 끝 (원래 FD FE / FD FF 가 쓰던 레지스터)
  * 글꼴 텍스처 = textures.bin 끝에 새 항목(6576번) 1024×1280 ARGB, 32px 칸.
    위 왼쪽 512×512 = 원래 일본어 글꼴 그대로(id 0~255 좌표 불변), 나머지 칸 = 한글
  * 텍스처 크기 상수(0x200×0x200)는 0으로 → 그리기 명령이 텍스처 자체 크기를 씀
  * 일본어 칸은 엔진이 줄을 안 바꾼다 → 한 줄씩 항목으로 나눠 넣음(원본 일본어도 그렇게 돼 있음)
"""
import csv, glob, os, shutil, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
import xex
import ppc
from x360tex import Textures, tiled_offset

ROOT = os.path.join(os.path.dirname(__file__), '..')
X360 = os.path.join(ROOT, 'work', 'x360')
PKG = os.path.join(X360, 'pkg')
FONT = r'C:\Windows\Fonts\malgunbd.ttf'

ID_OFFSET = 7                  # 360 에셋 번호 = N64 번호 + 7 (대사 구간)
FONT_TABLE = 0x6EA
LEAD0, NLEAD = 0xF0, 4
TRAILS = [t for t in range(1, 256) if t not in (0x20, 0xFD)]
TEX_W, TEX_H = 1024, 1280
NGLYPH = (TEX_W // 32) * (TEX_H // 32)          # 1280 칸 = id 0~1279
LINE_UNITS = 222                                 # 일본어 원본 최장 줄 226 단위(16 = 32px)
KR_W = 14                                        # 한글 글자 폭(단위) = 진행 폭(글자별 폭 모드)
SPACE_W = 7                                      # id 0x0F (공백) — 엔진이 표 0x82453788+0x70 값 × 0.8 을 씀
SPACE_TAB = 0x824537F8                           # FONTS_2 공백 폭 (원래 16 → 한 글자보다 넓음)
SPACE_VAL = 8

# 일본어 글꼴의 부호·영숫자 id
JP = {' ': 0x0F, '、': 0x01, '$': 0x02, '(': 0x03, ')': 0x04, '・': 0x05, '%': 0x06, '「': 0x07, '」': 0x08,
      "'": 0x37, '"': 0x35, '<': 0x0B, '>': 0x0C, '&': 0x0D, '~': 0x0E, '～': 0x0E, '!': 0x34, '#': None,
      '*': 0x38, '+': 0x39, ',': 0x3A, '-': 0x3B, 'ー': 0x3B, '.': 0x3C, '/': 0x3D, ':': 0x3E, '=': 0x3F,
      '?': 0x40, '@': 0x41, '。': 0x42}
for i, c in enumerate('0123456789'):
    JP[c] = 0x10 + i
for i, c in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    JP[c] = 0x1A + i
for i, c in enumerate('abcdefghijklmnopqrstuvwxyz'):
    JP[c] = 0x95 + i

# ---------------------------------------------------------------- db360 / dialogue
def load_db():
    d = open(os.path.join(X360, 'db360.bin'), 'rb').read()
    n = struct.unpack('>I', d[:4])[0]
    ent = [struct.unpack('>II', d[8 + i * 8:16 + i * 8]) for i in range(n)]
    base = (n + 1) * 8
    assets = [d[base + ent[i][0]:base + (ent[i + 1][0] if i + 1 < n else len(d) - base)] for i in range(n)]
    return d, ent, assets


def build_db(d, ent, assets):
    n = len(ent)
    out = bytearray(d[:8])
    off = 0
    for i in range(n):
        out += struct.pack('>II', off, ent[i][1])
        off += len(assets[i])
    for a in assets:
        out += a
    return bytes(out)


def parse_sections(b, o):
    secs = []
    for _ in range(2):
        cnt = b[o]; o += 1
        s = []
        for _ in range(cnt):
            cmd, l = b[o], b[o + 1]
            s.append((cmd, b[o + 2:o + 2 + l])); o += 2 + l
        secs.append(s)
    return secs, o


def parse_dialog(b):
    nl = b[0]
    offs = struct.unpack('<%dH' % nl, b[1:1 + 2 * nl])
    langs = []
    for k in range(nl):
        secs, end = parse_sections(b, offs[k])
        langs.append(secs)
    return langs, end


def build_dialog(langs):
    nl = len(langs)
    body = bytearray(); offs = []
    p = 1 + 2 * nl
    for secs in langs:
        offs.append(p + len(body))
        for s in secs:
            body.append(len(s))
            for cmd, t in s:
                assert len(t) < 256
                body += bytes([cmd, len(t)]) + t
    return bytes([nl]) + struct.pack('<%dH' % nl, *offs) + bytes(body)

# ---------------------------------------------------------------- glyphs
def kr_code(k):
    lead, t = divmod(k, len(TRAILS))
    assert lead < NLEAD, '한글 글자가 너무 많음'
    return bytes([LEAD0 + lead, TRAILS[t]]), (lead + 1) * 256 + TRAILS[t]


def encode(t, cmap):
    out = bytearray(b'\xfd\x6a')
    for c in t:
        if c in cmap:
            out += cmap[c][0]
        elif JP.get(c) is not None:
            out.append(JP[c])
        else:
            raise ValueError('글꼴에 없는 글자 %r: %s' % (c, t))
    return bytes(out) + b'\0'


def width(t):
    w = 0
    for c in t:
        w += SPACE_W if c == ' ' else (KR_W if ord(c) >= 0xAC00 else jp_w[JP[c]])
    return w


def wrap(t):
    """공백에서 줄을 나눔 → 줄 목록 (한 줄 = 항목 하나)."""
    words = t.split(' ')
    lines, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w) if cur else w
        if width(cand) <= LINE_UNITS or not cur:
            if width(cand) > LINE_UNITS:
                raise ValueError('공백 없는 구간이 한 줄을 넘음: ' + cand)
            cur = cand
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


FREE_CELLS = [(x * 32, y * 32) for y in range(TEX_H // 32) for x in range(TEX_W // 32)
              if not (x < 16 and y < 16)]           # 일본어 글꼴(512×512) 자리 밖


def render_atlas(jp_atlas, chars):
    img = Image.new('RGBA', (TEX_W, TEX_H), (255, 255, 255, 0))
    img.paste(jp_atlas, (0, 0))
    font = ImageFont.truetype(FONT, 29)
    recs = {}
    for k, c in enumerate(chars):
        _, gid = kr_code(k)
        cx, cy = FREE_CELLS[gid - 256]
        m = Image.new('L', (32, 32), 0)
        dr = ImageDraw.Draw(m)
        bb = dr.textbbox((0, 0), c, font=font)
        gw, gh = bb[2] - bb[0], bb[3] - bb[1]
        dr.text(((KR_W * 2 - gw) // 2 - bb[0], (32 - gh) // 2 - bb[1] + 1), c, font=font, fill=255)
        glyph = Image.new('RGBA', (32, 32), (255, 255, 255, 0)); glyph.putalpha(m)
        img.paste(glyph, (cx, cy))
        recs[gid] = (cx // 2, cy // 2, KR_W, 16)
    return img, recs


def kr_cell_ok():
    for k in range(NLEAD * len(TRAILS)):
        _, gid = kr_code(k)
        if gid >= NGLYPH:
            return k
    return NLEAD * len(TRAILS)


def tile_argb(img):
    a = np.array(img)                                     # RGBA
    argb = a[..., [3, 0, 1, 2]].reshape(-1, 4)
    out = np.zeros((TEX_W * TEX_H, 4), np.uint8)
    ys, xs = np.mgrid[0:TEX_H, 0:TEX_W]
    idx = np.vectorize(lambda x, y: tiled_offset(x, y, TEX_W, 2))(xs, ys).reshape(-1)
    out[idx] = argb
    return out.tobytes()


def build_textures(atlas_img):
    T = Textures(os.path.join(X360, 'textures.bin'))
    d = T.d
    n = T.n
    H = 4 + n * 20
    data0 = H + n * 0x34
    assert data0 == 0x73984
    last_end = max(struct.unpack_from('>I', d, 4 + i * 20)[0] + struct.unpack_from('>I', d, 16 + i * 20)[0] for i in range(n))
    off = (last_end + 0xFFF) & ~0xFFF
    pix = tile_argb(atlas_img)
    entry = struct.pack('>5I', off, TEX_W, TEX_H, len(pix), 0xFFFFFFFF)
    hdr = bytearray(d[H:H + 0x34])                         # 0번(일본어 글꼴) 머리를 본떠서
    f = list(struct.unpack_from('>6I', hdr, 0x1C))
    f[0] = (f[0] & ~(0x1FF << 22)) | ((TEX_W // 32) << 22)
    f[2] = (TEX_W - 1) | ((TEX_H - 1) << 13)
    f[4] &= ~(0xF << 6)                                    # 밉 없음
    f[5] &= 0xFFF                                          # 밉 주소 0
    struct.pack_into('>6I', hdr, 0x1C, *f)
    body = d[data0:]
    body = body + bytes(off - len(body)) if len(body) < off else body[:off]
    out = struct.pack('>I', n + 1) + d[4:H] + entry + d[H:data0] + bytes(hdr) + body + pix
    return out, n

# ---------------------------------------------------------------- xex hook
CAVE = 0x82448000          # .text 끝(0x82440CF4) 뒤 빈 곳 — 랜더마이저는 0x82440CF4 부터 씀, 겹치지 않게
HOOK_AT = 0x820D12E4       # FONTS_2, 쪽 레지스터 0 일 때: cmplwi cr6,r28,0
RET_ORIG = 0x820D12E8
EPILOGUE = 0x820D1E60


def patch_xex(img):
    img = bytearray(img)
    def w32(va, v):
        struct.pack_into('>I', img, va - 0x82000000, v)
    def r32(va):
        return struct.unpack_from('>I', img, va - 0x82000000)[0]
    assert r32(HOOK_AT) == 0x2B1C0000, hex(r32(HOOK_AT))       # cmplwi cr6,r28,0
    assert r32(0x820D15A4) == 0x38C00200 and r32(0x820D15AC) == 0x38A00200
    code = [
        ppc.cmplwi(6, 28, LEAD0),
        ('blt', 'orig'),
        ppc.cmplwi(6, 28, LEAD0 + NLEAD),
        ('bge', 'orig'),
        ppc.addi(10, 28, -(LEAD0 - 2)),            # 쪽 = 선행-0xEE → id = (쪽-1)*256 + 후행
        ppc.stw(10, 0x438, 29),
        ('b', EPILOGUE),
        ('label', 'orig'),
        ppc.cmplwi(6, 28, 0),
        ('b', RET_ORIG),
    ]
    words = ppc.assemble(code, CAVE)
    for i, w in enumerate(words):
        assert r32(CAVE + i * 4) == 0
        w32(CAVE + i * 4, w)
    w32(HOOK_AT, ppc.b(HOOK_AT, CAVE))
    w32(0x820D15A4, 0x38C00000)                    # li r6,0  (높이 → 텍스처 자체 크기)
    w32(0x820D15AC, 0x38A00000)                    # li r5,0  (폭)
    assert r32(SPACE_TAB) == 16
    w32(SPACE_TAB, SPACE_VAL)
    return bytes(img)

# ---------------------------------------------------------------- main
def read_tsv(path):
    files = sorted(glob.glob(os.path.join(path, '*.tsv'))) if os.path.isdir(path) else [path]
    tr = {}
    for f in files:
        with open(f, encoding='utf-8-sig', newline='') as fh:
            r = csv.reader(fh, delimiter='\t')
            head = next(r)
            ci = {h: i for i, h in enumerate(head)}
            for c in r:
                if len(c) > ci['번역'] and c[ci['번역']].strip() and c[ci['구분']] == '대사':
                    tr[c[ci['위치']]] = (c[ci['원문']], c[ci['번역']].strip())
    return tr


jp_w = {}


def verify(tex_bin, tab, assets, changed, img):
    """새 텍스처 파일을 다시 풀고 좌표표대로 바뀐 일본어 칸 대사를 그려 본다 → work/x360/preview_kr.png"""
    from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
    n = struct.unpack_from('>I', tex_bin)[0]
    o, w, h, size, _ = struct.unpack_from('>5I', tex_bin, 4 + (n - 1) * 20)
    hdr = tex_bin[4 + n * 20 + (n - 1) * 0x34:][:0x34]
    f = struct.unpack_from('>6I', hdr, 0x1C)
    assert ((f[0] >> 22) & 0x1FF) * 32 == w and (f[2] & 0x1FFF) + 1 == w and ((f[2] >> 13) & 0x1FFF) + 1 == h
    data0 = 4 + n * 20 + n * 0x34
    raw = np.frombuffer(tex_bin, np.uint8, size, data0 + o).reshape(-1, 4)
    ys, xs = np.mgrid[0:h, 0:w]
    idx = np.vectorize(lambda x, y: tiled_offset(x, y, w, 2))(xs, ys)
    atlas = Image.fromarray(raw[idx][..., [1, 2, 3, 0]].copy(), 'RGBA')
    assert struct.unpack_from('>I', tab)[0] == n - 1
    recs = [struct.unpack_from('>4I', tab, 4 + i * 16) for i in range(NGLYPH)]
    lines = []
    for a in changed:
        for s in parse_dialog(assets[a])[0][1]:
            for cmd, t in s:
                if t[:2] == b'\xfd\x6a':
                    lines.append(t[2:].rstrip(b'\0'))
    canvas = Image.new('RGBA', (LINE_UNITS * 2 + 40, 36 * len(lines) + 8), (40, 40, 90, 255))
    for k, t in enumerate(lines):
        x, y, page, j = 8, 4 + k * 36, 0, 0
        while j < len(t):
            c = t[j]; j += 1
            if page == 0 and LEAD0 <= c < LEAD0 + NLEAD:
                page = c - (LEAD0 - 2); continue
            gid = (page - 1) * 256 + c if page else c
            page = 0
            if gid == 0x0F:
                x += SPACE_W * 2; continue
            rx, ry, rw, rh = recs[gid]
            assert rw > 0, ('빈 글리프', hex(gid))
            canvas.alpha_composite(atlas.crop((rx * 2, ry * 2, rx * 2 + rw * 2, ry * 2 + rh * 2)), (x, y))
            x += rw * 2
        assert x <= LINE_UNITS * 2 + 8 + 8, ('줄 넘침', x)
    canvas.save(os.path.join(X360, 'preview_kr.png'))
    md = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
    for va, cnt in ((HOOK_AT, 1), (CAVE, 10), (0x820D15A4, 3)):
        for i in md.disasm(img[va - 0x82000000:va - 0x82000000 + cnt * 4], va):
            print('  %X %s %s' % (i.address, i.mnemonic, i.op_str))
    print('미리보기 줄 %d개 → work/x360/preview_kr.png' % len(lines))


def main():
    src, out_dir = sys.argv[1], sys.argv[2]
    tr = read_tsv(src)
    d, ent, assets = load_db()
    t = assets[FONT_TABLE]
    jp_recs = [struct.unpack('>4I', t[4 + i * 16:20 + i * 16]) for i in range(256)]
    for i, r in enumerate(jp_recs):
        jp_w[i] = r[2]
    chars = sorted({c for _, k in tr.values() for c in k if 0xAC00 <= ord(c) <= 0xD7A3})
    assert len(chars) <= kr_cell_ok(), (len(chars), kr_cell_ok())
    cmap = {c: kr_code(k) for k, c in enumerate(chars)}

    by_n64 = {}
    for loc, (en, kr) in tr.items():
        a, s, i = loc.split(':')
        by_n64.setdefault(int(a, 16), []).append((int(s), int(i), en, kr))
    en_of = {}                                       # 360 대사 에셋 → 영어 칸
    for k, b in enumerate(assets):
        if len(b) > 9 and b[0] == 4:
            try:
                en_of[k] = parse_dialog(b)[0][0]
            except Exception:
                pass
    def fits(k, items):
        en = en_of.get(k)
        return en is not None and all(s < len(en) and i < len(en[s]) and
                                      en[s][i][1].rstrip(b'\0').decode('latin-1') == e for s, i, e, _ in items)
    by_asset = {}
    for a, items in by_n64.items():
        near = [a + ID_OFFSET] + sorted(en_of, key=lambda k: abs(k - a - ID_OFFSET))
        k = next((k for k in near if fits(k, items)), None)
        assert k is not None, 'N64 %X 에 맞는 360 에셋 없음' % a
        by_asset[k] = items
    for a, items in sorted(by_asset.items()):
        langs, _ = parse_dialog(assets[a])
        en = langs[0]
        jp = [[(cmd, t) for cmd, t in s] for s in en]           # 영어 칸 구조를 본떠 일본어 칸을 새로
        slots = [[[e] for e in s] for s in jp]
        for s, i, src_en, kr in items:
            cmd, t = en[s][i]
            assert t.rstrip(b'\0').decode('latin-1') == src_en, (hex(a), s, i, t, src_en)
            slots[s][i] = [(cmd, encode(line, cmap)) for line in wrap(kr)]
        # 번역 안 된 영어 대사는 원래 일본어를 못 쓰니 영어 그대로(FD 6A 없이 = 영어 글꼴)
        langs[1] = [[e for sl in s for e in sl] for s in slots]
        assert all(len(s) < 256 for s in langs[1])
        assets[a] = build_dialog(langs)

    # 글꼴 좌표표: [텍스처 번호][1280 × {x,y,w,h}]
    T = Textures(os.path.join(X360, 'textures.bin'))
    atlas, recs = render_atlas(T.image(0), chars)
    tex_bin, tex_id = build_textures(atlas)
    tab = bytearray(struct.pack('>I', tex_id))
    for gid in range(NGLYPH):
        r = jp_recs[gid] if gid < 256 else recs.get(gid, (0, 0, 0, 16))
        tab += struct.pack('>4I', *r)
    assets[FONT_TABLE] = bytes(tab)
    db = build_db(d, ent, assets)

    img, base, _ = xex.load(os.path.join(PKG, 'default.xex'))
    img = patch_xex(img)

    atlas.save(os.path.join(X360, 'kr_atlas.png'))
    print('대사 에셋 %d개 · 한글 %d자 · 텍스처 #%d %dx%d · db %d B · 텍스처 파일 %d B' % (
        len(by_asset), len(chars), tex_id, TEX_W, TEX_H, len(db), len(tex_bin)))
    verify(tex_bin, tab, assets, sorted(by_asset), img)
    if '--write' not in sys.argv:
        print('드라이런 — 출력 안 씀 (--write 로 기록)')
        return
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(PKG, out_dir)
    xex.write_plain(os.path.join(PKG, 'default.xex'), img, os.path.join(out_dir, 'default.xex'))
    open(os.path.join(out_dir, 'RAWFiles', 'db360.cmp'), 'wb').write(db)
    open(os.path.join(out_dir, 'RAWFiles', 'db360.textures.cmp'), 'wb').write(tex_bin)
    print('출력', out_dir)


if __name__ == '__main__':
    main()
