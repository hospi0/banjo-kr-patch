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
import csv, glob, os, re, shutil, struct, sys
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
LOGO_EN, LOGO_JP = 11, 12                        # 타이틀 로고 텍스처(영어 / 일본어)
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


TOKEN = re.compile(r'\{FD\}.|.')                 # {FD}h 떨림 켬 / {FD}l 끔 = FD + 문자 (설정·해제라 줄마다 다시 넣어도 됨)
PLACE = 0x02                                     # 일본어 칸의 «끼워 넣기 자리»(영어 칸 ~) — 일본어 원본 36곳 모두 0x02
PLACE_W = 30                                     # 끼워질 숫자 폭 어림(3자리)
NORMALIZE = [('…', '...'), ('‥', '..'), ('™', 'TM'), ('＿', ' ')]


def normalize(t):
    for a, b in NORMALIZE:
        t = t.replace(a, b)
    return re.sub(' {2,}', ' ', t).strip()


def encode(t, cmap):
    out = bytearray(b'\xfd\x6a')
    for c in TOKEN.findall(t):
        if len(c) > 1:
            out += bytes([0xFD, ord(c[-1])])
        elif c == '~':
            out.append(PLACE)
        elif c in cmap:
            out += cmap[c][0]
        elif JP.get(c) is not None:
            out.append(JP[c])
        else:
            raise ValueError('글꼴에 없는 글자 %r: %s' % (c, t))
    return bytes(out) + b'\0'


def width(t):
    w = 0
    for c in TOKEN.findall(t):
        if len(c) > 1:
            continue
        w += (SPACE_W if c == ' ' else PLACE_W if c == '~' else
              KR_W if ord(c) >= 0xAC00 else jp_w[JP[c]])
    return w


def wrap(t):
    """공백에서 줄을 나눔 → 줄 목록 (한 줄 = 항목 하나). 떨림({FD}h)이 켜진 채 줄이 넘어가면 다음 줄 앞에 다시 넣는다."""
    lines = _wrap(t)
    on = False
    for k, l in enumerate(lines):
        if on and not l.startswith('{FD}h'):
            lines[k] = l = '{FD}h' + l
        for m in re.findall(r'\{FD\}([hl])', l):
            on = m == 'h'
    return lines


def _wrap(t, limit=LINE_UNITS):
    words = t.split(' ')
    lines, cur = [], ''
    for w in words:
        cand = (cur + ' ' + w) if cur else w
        if width(cand) <= limit or not cur:
            if width(cand) > limit:
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
    # 타이틀 로고: 일본어(12번) 자리에 영어 로고(11번)를 그대로 — 크기·형식·밉 같음 (하스피 «영문으로 교체»)
    body = bytearray(body)
    (o11, w11, h11, s11, _), (o12, w12, h12, s12, _) = (struct.unpack_from('>5I', d, 4 + i * 20) for i in (LOGO_EN, LOGO_JP))
    assert (w11, h11, s11) == (w12, h12, s12) and d[H + LOGO_EN * 0x34:][:0x34][0x1C:] == d[H + LOGO_JP * 0x34:][:0x34][0x1C:]
    body[o12:o12 + s12] = body[o11:o11 + s11]
    body = bytes(body)
    out =struct.pack('>I', n + 1) + d[4:H] + entry + d[H:data0] + bytes(hdr) + body + pix
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

    # 문자열 폭(이름표 띠 길이·정렬) 0x820D1E70 의 FD 6A 경로: 한글 선행이면 폭 KR_W, 후행 건너뜀
    WIDTH_AT, WIDTH_RET = 0x820D1F24, 0x820D1F30
    orig = [r32(WIDTH_AT + 4 * k) for k in range(3)]   # slwi r10,r10,4 / add r10,r10,r9 / lwa r10,0xC(r10)
    assert orig[0] == 0x554A2036, hex(orig[0])
    cave2 = CAVE + 0x40
    words = ppc.assemble([
        ppc.cmplwi(6, 10, LEAD0), ('blt', 'n'),
        ppc.cmplwi(6, 10, LEAD0 + NLEAD), ('bge', 'n'),
        ppc.addi(11, 11, 1),
        ppc.li(10, KR_W), ('b', WIDTH_RET),
        ('label', 'n'), orig[0], orig[1], orig[2], ('b', WIDTH_RET)], cave2)
    for i, w in enumerate(words):
        assert r32(cave2 + i * 4) == 0
        w32(cave2 + i * 4, w)
    w32(WIDTH_AT, ppc.b(WIDTH_AT, cave2))

    # 메뉴 글상자 줄 접기 0x82147038 의 일본어 경로(바이트 수로 끊음): 한글 2바이트 = 1글자, 둘 사이에서 안 끊음
    WRAP_AT, WRAP_RET = 0x82147148, 0x82147178
    assert r32(WRAP_AT) == ppc.li(10, 0), hex(r32(WRAP_AT))
    cave3 = CAVE + 0x80
    words = ppc.assemble([
        ppc.li(10, 0),
        ('label', 'L'),
        ppc.cmpw(6, 10, 4), ('bge', 'done'),
        ppc.lbzx(8, 9, 11),
        ppc.cmplwi(6, 8, 6), ('beq', 'done'),
        ppc.cmplwi(6, 8, LEAD0), ('blt', 'one'),
        ppc.cmplwi(6, 8, LEAD0 + NLEAD), ('bge', 'one'),
        ppc.addi(11, 11, 1),
        ('label', 'one'),
        ppc.addi(11, 11, 1), ppc.addi(10, 10, 1),
        ppc.lbzx(8, 9, 11), ppc.cmplwi(0, 8, 0), ('bne0', 'L'),
        ('label', 'done'), ('b', WRAP_RET)], cave3)
    for i, w in enumerate(words):
        assert r32(cave3 + i * 4) == 0
        w32(cave3 + i * 4, w)
    w32(WRAP_AT, ppc.b(WRAP_AT, cave3))

    w32(0x820D15A4, 0x38C00000)                    # li r6,0  (높이 → 텍스처 자체 크기)
    w32(0x820D15AC, 0x38A00000)                    # li r5,0  (폭)
    assert r32(SPACE_TAB) == 16
    w32(SPACE_TAB, SPACE_VAL)
    return bytes(img)


# ---------------------------------------------------------------- xex 안 일본어 문자열 (일시정지·파일 선택·출연진)
X360_XEX = os.path.join(ROOT, 'work', 'text', 'x360_xex.tsv')
STR_CAVE = 0x8244A000                            # .text 끝 뒤 빈 곳(0x82440CF4~0x82450000, 0 확인) — 훅 코드는 0x82448000
CAST_TABLE = 0x8245DBF8                          # 출연진 20B 항목 {?, 영어 이름*, ?, 일본어 이름*, 플래그}


def read_xex_tr():
    with open(X360_XEX, encoding='utf-8-sig', newline='') as fh:
        r = csv.reader(fh, delimiter='\t', quoting=csv.QUOTE_NONE); next(r)
        return [(int(c[0], 16), c[1], c[2], c[3]) for c in r]   # 번역은 앞뒤 공백까지 그대로(이어 붙는 조각)


def cast_names(img):
    """출연진 표 → [(일본어 포인터 칸 주소, 영어 이름)]"""
    out = []                                     # 표가 일본어 이름 덩어리 사이사이에 여러 개 — 항목 모양으로 훑는다
    a = CAST_TABLE
    while a < 0x82460000:
        en_p, _, jp_p, z = struct.unpack_from('>4I', img, a + 4 - 0x82000000)
        if (0x82008000 <= en_p < 0x8200A000 and 0x8245D000 <= jp_p < 0x8245F000 and
                img[jp_p - 0x82000000:jp_p - 0x82000000 + 2] == b'\xfd\x6a'):
            e = img.index(b'\0', en_p - 0x82000000)
            out.append((a + 12, img[en_p - 0x82000000:e].decode('latin-1')))
            a += 20
        else:
            a += 4
    return out


def patch_xex_strings(img, cmap, rows, cast_kr):
    """반환: (img, 제자리 수, 옮긴 수, 출연진 수, 빠진 출연진)"""
    img = bytearray(img)
    def at(va):
        return va - 0x82000000
    cave = STR_CAVE
    def put(b):
        nonlocal cave
        o = at(cave)
        assert img[o:o + len(b)] == bytes(len(b)), '동굴 자리가 비어 있지 않음'
        img[o:o + len(b)] = b
        va = cave
        cave = (cave + len(b) + 3) & ~3
        assert cave < 0x82450000
        return va
    n_in = n_ptr = 0
    for va, how, _, kr in rows:
        if how == '제자리':
            o = at(va)
            e = img.index(b'\0', o)
            slot = e - o
            while img[o + slot] == 0:
                slot += 1
            data = encode(kr, cmap)
            if img[o:o + 2] != b'\xfd\x6a':
                data = data[2:]                        # 원래 FD 6A 없이 앞 문자열에 이어 붙는 조각
            assert len(data) <= slot, ('제자리 칸 넘침', hex(va), kr, len(data), slot)
            img[o:o + slot] = data + bytes(slot - len(data))
            n_in += 1
        else:
            struct.pack_into('>I', img, at(va), put(encode(kr, cmap)))
            n_ptr += 1
    miss = []
    names = cast_names(bytes(img))
    for slot_va, en in names:
        kr = cast_kr.get(en)
        if kr is None:
            miss.append(en); continue
        struct.pack_into('>I', img, at(slot_va), put(encode(kr, cmap)))
    return bytes(img), n_in, n_ptr, len(names) - len(miss), miss

# ---------------------------------------------------------------- main
def read_tsv(path, kind='대사'):
    files = sorted(glob.glob(os.path.join(path, '*.tsv'))) if os.path.isdir(path) else [path]
    tr = {}
    for f in files:
        with open(f, encoding='utf-8-sig', newline='') as fh:
            r = csv.reader(fh, delimiter='\t')
            head = next(r)
            ci = {h: i for i, h in enumerate(head)}
            for c in r:
                if len(c) > ci['번역'] and c[ci['번역']].strip() and c[ci['구분']] == kind:
                    tr[c[ci['위치']]] = (c[ci['원문']], normalize(c[ci['번역']]))
    return tr


# ---------------------------------------------------------------- 360 메뉴 문자열 (RAWFiles/X360_strings.dat)
STRINGS_DAT = os.path.join(PKG, 'RAWFiles', 'X360_strings.dat')
X360_UI = os.path.join(ROOT, 'work', 'text', 'x360_ui.tsv')
UI_LANG = 3                                      # 영/프/독/일 — 4번째가 일본어 칸


def parse_strings(d):
    """[u16 개수][u16 언어 수][u32 언어별 총 길이] + 언어마다 [u32 길이 × 개수] + 문자열들(뒤 쓰레기 바이트는 버림)"""
    n, nl = struct.unpack_from('<HH', d, 0)
    p = 4 + 4 * nl
    lens = []
    for _ in range(nl):
        lens.append(struct.unpack_from('<%dI' % n, d, p)); p += 4 * n
    langs = []
    for L in range(nl):
        a = []
        for l in lens[L]:
            a.append(d[p:p + l]); p += l
        langs.append(a)
    return langs


def build_strings(langs):
    n, nl = len(langs[0]), len(langs)
    out = bytearray(struct.pack('<HH', n, nl))
    out += struct.pack('<%dI' % nl, *(sum(len(s) for s in a) for a in langs))
    for a in langs:
        out += struct.pack('<%dI' % n, *(len(s) for s in a))
    for a in langs:
        for s in a:
            out += s
    return bytes(out)


def read_ui():
    with open(X360_UI, encoding='utf-8-sig', newline='') as fh:
        r = csv.reader(fh, delimiter='\t', quoting=csv.QUOTE_NONE); next(r)      # 원문이 " 로 시작하는 줄 있음
        return {int(c[0]): (c[1], normalize(c[2]) if len(c) > 2 and c[2].strip() else '') for c in r}


def nchars(t):
    """메뉴 글상자가 세는 글자 수: 한글·영숫자·공백 1, {FD}x 2(바이트 둘)"""
    return sum(2 if len(c) > 1 else 1 for c in TOKEN.findall(t))


def _wrap_chars(t, maxc, maxw):
    lines, cur = [], ''
    for w in t.split(' '):
        cand = (cur + ' ' + w) if cur else w
        if (nchars(cand) <= maxc and width(cand) <= maxw) or not cur:
            if nchars(cand) > maxc:
                raise ValueError('공백 없는 구간이 한 줄(%d글자)을 넘음: %s' % (maxc, cand))
            cur = cand
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def ui_kind(j):
    """일본어 칸 원래 형식: FONT(FD 6A 게임 글꼴) / UTF16(시스템 메시지 상자, BE + 0 한 바이트) / ASCII(영어 그대로)"""
    if j[:2] == b'\xfd\x6a':
        return 'FONT'
    if j[:1] == b'\0' or any(c >= 0x80 for c in j):
        return 'UTF16'
    return 'ASCII'


def ui_font_chars(ui, jp):
    return [kr for i, (_, kr) in ui.items() if kr and ui_kind(jp[i]) != 'UTF16']


def apply_ui(ui, cmap):
    """일본어 칸을 한글로. 게임 글꼴 문자열은 줄바꿈(0x06, 번역의 \\)을 일본어 원본의 최대 줄 폭에 맞춰 넣는다
    (원본이 한 줄이면 한 줄 — 폭이 원본보다 크면 경고). 반환: (새 파일, 바꾼 수, 경고 목록)"""
    langs = parse_strings(open(STRINGS_DAT, 'rb').read())
    en, jp = langs[0], langs[UI_LANG]
    warns, n = [], 0
    for i, (src, kr) in sorted(ui.items()):
        assert en[i].rstrip(b'\0').decode('latin-1') == src, ('x360_ui 원문 다름', i)
        if not kr:
            continue
        kind = ui_kind(jp[i])
        if kind == 'UTF16':
            jp[i] = kr.encode('utf-16-be') + b'\0'
        else:
            jl = jp[i][2:].rstrip(b'\0').split(b'\x06') if kind == 'FONT' else [jp[i].rstrip(b'\0')]
            jw = max(sum(SPACE_W if c == 0x0F else jp_w[c] for c in l) for l in jl) if kind == 'FONT' else LINE_UNITS
            # 글상자는 줄을 «글자 수»로 끊고(한글 2바이트 = 1글자, xex 패치) 끊은 자리 다음 글자를 건너뛴다
            # → 일본어 원본 줄의 최대 글자 수 이하로 미리 나눠 엔진 한계에 안 걸리게
            jc = max(len(l) for l in jl)
            lines = []
            for seg in kr.split('\\'):
                if len(jl) > 1:
                    lines += _wrap_chars(seg, jc, max(jw, 150)) if seg else ['']
                else:
                    lines.append(seg)
            for l in lines:
                if l and width(l) > max(jw, 150) + 10:
                    warns.append('%d «%s» 폭 %d > 원본 %d' % (i, l, width(l), jw))
                if len(jl) > 1 and nchars(l) > jc:
                    warns.append('%d «%s» %d글자 > 원본 %d' % (i, l, nchars(l), jc))
            jp[i] = b'\xfd\x6a' + b'\x06'.join(encode(l, cmap)[2:-1] for l in lines) + b'\0'
        n += 1
    return build_strings(langs), n, warns


# ---------------------------------------------------------------- 그런티 퀴즈
QUIZ_LINES = 4                                   # 일본어 원본 문제 줄 수 최대(200개 중 194개가 4줄)


def parse_quiz(b):
    """[언어 수][2바이트][u16le 오프셋 × 언어] + 언어마다 [개수] + {cmd, len, data} (0x80 문제 줄, 0x81~ 보기)"""
    nl = b[0]
    offs = struct.unpack_from('<%dH' % nl, b, 3)
    langs = []
    for o in offs:
        n = b[o]; o += 1
        e = []
        for _ in range(n):
            c, l = b[o], b[o + 1]
            e.append((c, b[o + 2:o + 2 + l])); o += 2 + l
        langs.append(e)
    return b[1:3], langs


def build_quiz(hdr, langs):
    nl = len(langs)
    body = bytearray(); offs = []
    p = 3 + 2 * nl
    for e in langs:
        offs.append(p + len(body))
        body.append(len(e))
        for c, t in e:
            assert len(t) < 256
            body += bytes([c, len(t)]) + t
    return bytes([nl]) + hdr + struct.pack('<%dH' % nl, *offs) + bytes(body)


def apply_quiz(assets, qtr, cmap, qov):
    """N64 퀴즈 번역(위치 0C00:Q:i) → 영어 칸 글이 같은 360 퀴즈 에셋의 일본어 칸. 반환: (바꾼 에셋 수, 문제 목록)
    qov = {(360에셋, i): (360영어, 번역)} — x360_kr.tsv 의 «에셋:Q:i» 줄(360 에서 바뀐 보기, 360 만 짧게 다듬은 보기)"""
    import bkrom
    rom = bkrom.load_rom(); ntab = bkrom.asset_table(rom)
    by_n64 = {}
    for loc, (en, kr) in qtr.items():
        a, _, i = loc.split(':')
        by_n64.setdefault(int(a, 16), {})[int(i)] = kr
    x_by_text = {}
    for k, b in enumerate(assets):
        if len(b) > 12 and b[0] == 4 and b[3:5] == b'\x0b\x00':
            try:
                hdr, L = parse_quiz(b)
            except Exception:
                continue
            if L[0] and all(c >= 0x80 for c, _ in L[0]):
                x_by_text.setdefault(tuple(t for _, t in L[0]), []).append(k)
    n, errs = 0, []
    for a, rows in sorted(by_n64.items()):
        _, ent, _ = bkrom.parse_quiz(bkrom.asset(rom, ntab, a))
        ks = x_by_text.get(tuple(t for _, t in ent))
        if not ks:                                   # 보기만 바뀐 퀴즈 = 문제 줄이 같은 것
            q = tuple(t for c, t in ent if c == 0x80)
            ks = [k for key, kk in x_by_text.items() for k in kk
                  if len(key) == len(ent) and key[:len(q)] == q]
        if not ks:
            errs.append('N64 퀴즈 %04X: 360 에 같은 영어 퀴즈 없음' % a); continue
        for k in ks:
            hdr, L = parse_quiz(assets[k])
            jp = []
            for i, (c, t) in enumerate(ent):
                kr = rows.get(i)
                if (k, i) in qov:
                    en_x, kr = qov[(k, i)]
                    assert L[0][i][1].rstrip(b'\0').decode('latin-1') == en_x, ('x360_kr 퀴즈 원문 다름', hex(k), i)
                elif L[0][i][1] != t:
                    errs.append('%X:Q:%d 360 보기가 다름(x360_kr.tsv 필요): %s' % (k, i, L[0][i][1])); jp = None; break
                if kr is None:
                    errs.append('%04X:Q:%d 번역 없음' % (a, i)); jp = None; break
                lines = wrap(kr)
                if c != 0x80 and len(lines) > 1:
                    errs.append('%04X:Q:%d 보기가 한 줄을 넘음: %s' % (a, i, kr)); jp = None; break
                jp += [(c, encode(l, cmap)) for l in lines]
            if jp is None:
                continue
            if sum(1 for c, _ in jp if c == 0x80) > QUIZ_LINES:
                errs.append('%04X 문제가 %d줄을 넘음: %s' % (a, QUIZ_LINES, ' / '.join(rows.get(i, '') for i, (c, _) in enumerate(ent) if c == 0x80)))
                continue
            L[1] = jp
            assets[k] = build_quiz(hdr, L)
            n += 1
    return n, errs


jp_w = {}
DIFF_TSV = os.path.join(ROOT, 'work', 'text', 'x360_diff.tsv')
X360_KR = os.path.join(ROOT, 'work', 'text', 'x360_kr.tsv')
X360_CREDITS = os.path.join(ROOT, 'work', 'text', 'x360_credits.tsv')


def map_rows(tr, assets):
    """N64 번역 행 → 360 에셋 위치. 영어 원문이 같은 행은 그대로,
    다른 행(360 버튼 설명 등)은 diff 로 돌려준다 — work/text/x360_diff.tsv 의 «360번역» 칸으로 채운다.
    반환: {360에셋: [(s, i, 360영어, 번역)]}, [(N64위치, 360에셋, s, i, 360영어, 360번역, N64영어, N64번역)]"""
    by_n64 = {}
    for loc, (en, kr) in tr.items():
        a, s, i = loc.split(':')
        by_n64.setdefault(int(a, 16), []).append((int(s), int(i), en, kr, loc))
    en_of = {}
    for k, b in enumerate(assets):
        if len(b) > 9 and b[0] == 4:
            try:
                en_of[k] = parse_dialog(b)[0][0]
            except Exception:
                pass
    import difflib
    import bkrom
    rom = bkrom.load_rom()
    ntab = bkrom.asset_table(rom)
    def texts(sec):
        return [(i, t.rstrip(b'\0').decode('latin-1').replace('\xfd', '{FD}'))   # 번역 TSV 표기와 같게
                for i, (c, t) in enumerate(sec) if c >= 0x80]
    n64 = {a: [texts(sec) for sec in bkrom.parse_dialog(bkrom.asset(rom, ntab, a))[1]] for a in by_n64}
    def score(a, k):
        en = en_of.get(k)
        if en is None:
            return 0
        return sum(1 for s, sec in enumerate(n64[a]) if s < len(en)
                   for _, t in sec if t in {x for _, x in texts(en[s])})
    def align(a, k):
        """N64 (s,i) → (360 i, 360 영어) — 대사 순서 정렬(같은 글 / 같은 길이로 바뀐 구간은 짝지음)."""
        en = en_of[k]
        m = {}
        for s, sec in enumerate(n64[a]):
            if s >= len(en):
                continue
            xs = texts(en[s])
            sm = difflib.SequenceMatcher(None, [t for _, t in sec], [t for _, t in xs], autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == 'equal' or (op == 'replace' and i2 - i1 == j2 - j1):
                    for d in range(i2 - i1):
                        a_t, b_t = sec[i1 + d][1], xs[j1 + d][1]
                        head = lambda x: re.sub('[^A-Z]', '', x)[:8]
                        if (op == 'equal' or head(a_t) == head(b_t) or
                                difflib.SequenceMatcher(None, a_t, b_t, autojunk=False).ratio() >= 0.45):
                            m[(s, sec[i1 + d][0])] = xs[j1 + d]
        return m
    best, last = {}, 0
    for a in sorted(by_n64):                       # 같은 문장이 여러 에셋에 있으면 앞 에셋의 번호 차이에 가까운 쪽
        k = max(range(a - 45, a + 60), key=lambda k: (score(a, k), -abs(k - a - last)))
        if score(a, k):
            best[a] = last = k - a
    done = sorted(best)
    for a, items in by_n64.items():               # 한 줄도 안 맞는 에셋 = 이웃 에셋의 번호 차이
        if a not in best:
            nb = min(done, key=lambda x: abs(x - a))
            best[a] = best[nb]
    old = {}
    if os.path.exists(DIFF_TSV):
        with open(DIFF_TSV, encoding='utf-8-sig', newline='') as fh:
            r = csv.reader(fh, delimiter='\t'); next(r)
            for c in r:
                if len(c) >= 6:
                    old[c[0]] = (c[3], c[5].strip())
    by_asset, diff = {}, []
    anywhere, used = {}, set()
    for k, en in en_of.items():
        for s, sec in enumerate(en):
            for j, t in texts(sec):
                anywhere.setdefault(t, []).append((k, s, j))
    for a, items in sorted(by_n64.items()):
        k = a + best[a]
        m = align(a, k) if k in en_of else {}
        for s, i, e, kr, loc in items:
            if (s, i) not in m:
                hit = next((x for x in anywhere.get(e, []) if x not in used), None)
                if hit is None:
                    diff.append((loc, k, s, -1, '(360 에 짝 대사 없음)', '', e, kr))
                else:                                     # 360 에서 다른 에셋으로 옮겨진 대사
                    used.add(hit)
                    by_asset.setdefault(hit[0], []).append((hit[1], hit[2], e, kr))
                continue
            j, t = m[(s, i)]
            used.add((k, s, j))
            if t == e:
                by_asset.setdefault(k, []).append((s, j, e, kr))
            else:
                o = old.get(loc)
                kr360 = o[1] if o and o[0] == t else ''
                diff.append((loc, k, s, j, t, kr360, e, kr))
    with open(DIFF_TSV, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh, delimiter='\t', lineterminator='\n')
        w.writerow(['N64위치', '360위치', 'N64원문', '360원문', 'N64번역', '360번역'])
        for loc, k, s, i, t, kr360, e, kr in diff:
            w.writerow([loc, '%X:%d:%d' % (k, s, i), e, t, kr, kr360])
    return by_asset, diff


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
            if page == 0 and c == 0xFD:                    # FD + 명령 바이트 = 폭 0
                j += 1; continue
            if page == 0 and c == PLACE:
                x += PLACE_W * 2; continue
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
    by_asset, diff = map_rows(tr, assets)
    # 360 에서 영어가 바뀐 줄(버튼 설명 등)·360 전용 줄 = work/text/x360_kr.tsv (360위치 / 360원문 / 번역)
    extra, qov = 0, {}
    with open(X360_KR, encoding='utf-8-sig', newline='') as fh:
        r = csv.reader(fh, delimiter='\t'); next(r)
        for loc, en, kr in r:
            if ':Q:' in loc:                          # 퀴즈 (에셋:Q:번호)
                qk, _, qi = loc.split(':')
                qov[(int(qk, 16), int(qi))] = (en, normalize(kr))
                continue
            k, s, i = (int(x, 16) if n == 0 else int(x) for n, x in enumerate(loc.split(':')))
            items = [x for x in by_asset.get(k, []) if (x[0], x[1]) != (s, i)]
            by_asset[k] = items + [(s, i, en, normalize(kr))]
            extra += 1
    done = {(k, s, i) for k, items in by_asset.items() for s, i, _, _ in items}
    left = [x for x in diff if x[3] < 0 or (x[1], x[2], x[3]) not in done]
    print('360 원문이 다른 줄 %d개 중 x360_kr.tsv 로 %d줄 · 360 전용 포함 %d줄 적용 · 남은 줄 %d (영어로 남음, N64 전용 크레딧 등)'
          % (len(diff), len(diff) - len(left), extra, len(left)))
    # 남은 360 대사(엔딩 크레딧·360 전용 안내) — 일본어를 하나도 남기지 않는다(だぢづで = 한글 선행 바이트와 겹침)
    # x360_credits.tsv(영어 원문 → 번역) 에 있으면 번역, 없으면(사람 이름) 영어를 일본어 칸에 그대로
    with open(X360_CREDITS, encoding='utf-8-sig', newline='') as fh:
        r = csv.reader(fh, delimiter='\t', quoting=csv.QUOTE_NONE); next(r)
        credits = {c[0]: normalize(c[1]) for c in r}
    n_cr = n_name = 0
    for k, b in enumerate(assets):
        if len(b) > 9 and b[0] == 4:
            try:
                L, _ = parse_dialog(b)
            except Exception:
                continue
            for s, sec in enumerate(L[0]):
                for i, (c, t) in enumerate(sec):
                    en = t.rstrip(b'\0').decode('latin-1').replace('\xfd', '{FD}')
                    if c >= 0x80 and en and (k, s, i) not in done:
                        if en in credits:
                            n_cr += 1
                        else:
                            n_name += 1
                        by_asset.setdefault(k, []).append((s, i, en, credits.get(en, en)))
    print('남은 대사: 번역 %d · 영어 그대로(이름) %d' % (n_cr, n_name))
    qtr = read_tsv(src, '퀴즈')
    ui = read_ui()
    img, base, _ = xex.load(os.path.join(PKG, 'default.xex'))
    xrows = read_xex_tr()
    cast_kr = {en: kr for en, kr in read_tsv(src, 'UI').values()}
    cast_kr = {e: cast_kr[e] for _, e in cast_names(img) if e in cast_kr}
    ui_jp = parse_strings(open(STRINGS_DAT, 'rb').read())[UI_LANG]
    texts_all = ([k for items in by_asset.values() for _, _, _, k in items] + [k for _, k in qtr.values()] +
                 [k for _, k in qov.values()] + ui_font_chars(ui, ui_jp) +
                 [r[3] for r in xrows] + list(cast_kr.values()))
    chars = sorted({c for k in texts_all for c in k if 0xAC00 <= ord(c) <= 0xD7A3})
    assert len(chars) <= kr_cell_ok(), (len(chars), kr_cell_ok())
    cmap = {c: kr_code(k) for k, c in enumerate(chars)}
    for a, items in sorted(by_asset.items()):
        langs, _ = parse_dialog(assets[a])
        en = langs[0]
        jp = [[(cmd, t) for cmd, t in s] for s in en]           # 영어 칸 구조를 본떠 일본어 칸을 새로
        slots = [[[e] for e in s] for s in jp]
        for s, i, src_en, kr in items:
            cmd, t = en[s][i]
            assert cmd >= 0x80 and t.rstrip(b'\0').decode('latin-1').replace('\xfd', '{FD}') == src_en, (hex(a), s, i, t, src_en)
            slots[s][i] = [(cmd, encode(line, cmap)) for line in wrap(kr)]
        # 번역 안 된 영어 대사는 원래 일본어를 못 쓰니 영어 그대로(FD 6A 없이 = 영어 글꼴)
        langs[1] = [[e for sl in s for e in sl] for s in slots]
        assert all(len(s) < 256 for s in langs[1])
        assets[a] = build_dialog(langs)
    nq, qerrs = apply_quiz(assets, qtr, cmap, qov)
    print('퀴즈 %d행 → 360 퀴즈 에셋 %d개 · 문제 %d건' % (len(qtr), nq, len(qerrs)))
    for e in qerrs:
        print('  퀴즈', e)
    strings_dat, nu, uwarn = apply_ui(ui, cmap)
    print('메뉴 문자열 %d개 한글화 · 폭 경고 %d건' % (nu, len(uwarn)))
    for e in uwarn:
        print('  메뉴', e)

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

    img = patch_xex(img)
    img, n_in, n_ptr, n_cast, cmiss = patch_xex_strings(img, cmap, xrows, cast_kr)
    print('xex 문자열: 제자리 %d · 옮김 %d · 출연진 %d (번역 없음 %d: %s)' % (n_in, n_ptr, n_cast, len(cmiss), ', '.join(cmiss)))

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
    open(os.path.join(out_dir, 'RAWFiles', 'X360_strings.dat'), 'wb').write(strings_dat)
    open(os.path.join(out_dir, 'RAWFiles', 'db360.textures.cmp'), 'wb').write(tex_bin)
    print('출력', out_dir)


if __name__ == '__main__':
    main()
