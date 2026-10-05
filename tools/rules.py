"""Translation rules — enforced when a translation is read (not only at build time).

Engine facts (Rev1 zoombox):
  * a line is cut only at a SPACE, searching back from the end until the line fits LINE_UNITS
    (no space in range -> the search runs past the start = crash)
  * width units after our patch: ASCII/space 1, Korean syllable 1.5, {FD}+next byte 0
  * dialog box holds ~207 px (widest original wrapped line), Korean glyph advance 12 px
  * one entry <= 255 bytes incl. NUL
"""
import re

LINE_UNITS = 24
BOX_PX = 207
PUNCT = ',.!?:;)]}\'"、。，．！？：；）］｝」』】〉》”’…‥・·～〜♪♥'
TOKEN = re.compile(r'\{FD\}.|\{[0-9A-F]{2}\}|~')   # {FD}h 떨림 켬 / {FD}l 끔 / ~ = 엔진이 다른 문자열을 끼워 넣는 자리(replaceText)

BANNER = '''=== 반조 번역 규칙 (적재기가 막음) ===
 1. {FD}h(떨림 켬)·{FD}l(끔) 같은 제어 토큰은 원문에 있는 것을 모두 남길 것 (치트 코드 영문 철자도 그대로)
    ~ 는 이름 등이 끼워지는 자리표시 — 지우지 말 것 (부호 뒤 공백 제거 대상에서도 뺌)
 2. 문장부호 뒤 공백은 화면에서 폭 0으로 그린다(엔진이 공백에서만 줄을 끊어서 바이트는 남김) — 한 줄(한글 16자) 안에 공백이 하나는 있어야 한다
 3. 한 항목 255바이트(한글 1자 = 2바이트) — 넘는 대사는 빌더가 같은 화자 쪽으로 나눔(퀴즈는 넘으면 실패)
 4. 쓸 수 있는 글자: 한글 완성형, 영문 대문자, 숫자, 원본 글꼴 문장부호 (소문자·특수문자는 글꼴에 없음)
'''


ZW_PUNCT = ',.!?:;)\'"'   # space after these is drawn zero-width (hook)
AUTO_FIX = [('＿', ' '), ('…', '...'), ('‥', '..'), ('™', 'TM'), ('<', "'"), ('>', "'")]   # artefacts / glyphs the font lacks


def normalize(t):
    for a, b in AUTO_FIX:
        t = t.replace(a, b)
    t = re.sub(r'(?<!\{FD\})[a-z]+', lambda m: m.group().upper(), t)   # font has capitals only ({FD}h/{FD}l kept)
    return re.sub(' {2,}', ' ', t)


def squeeze(t):
    return re.sub('([' + re.escape(PUNCT) + '])[ 　](?![ 　])', r'\1', t)


def tokens(t):
    return TOKEN.findall(t)


def units2(t):
    """width in half units (ASCII 2, Hangul 3, tokens 0) — same as the patched engine."""
    t = TOKEN.sub('', t)
    return sum(2 if ord(c) < 0x80 else 3 for c in t)


def engine_wrap(t):
    """Simulate the patched zoombox wrap on display text -> list of lines, or raise ValueError."""
    lines = []
    while units2(t) > LINE_UNITS * 2 + 1:          # engine compares floor(half/2) > 24
        i = len(t)
        while i > 0 and (units2(t[:i]) // 2 > LINE_UNITS or t[i:i + 1] != ' '):
            i -= 1
        if i <= 0:
            raise ValueError('공백 없는 구간이 한 줄(%d칸)을 넘음: %s' % (LINE_UNITS, t[:30]))
        lines.append(t[:i])
        t = t[i + 1:]
    lines.append(t)
    return lines


def px(t, adv):
    t = TOKEN.sub('', t)
    w = 0
    for i, c in enumerate(t):
        if c == ' ':
            w += 0 if i and t[i - 1] in ZW_PUNCT else 6.4
        else:
            w += 12 if ord(c) >= 0x80 else adv.get(c, 8)
    return w


def nbytes_of(t):
    return sum(2 if ord(c) >= 0x80 else 1 for c in re.sub(r'\{[0-9A-F]{2}\}', 'X', t)) + 1


def split_pages(t, limit=255):
    """Split an over-long dialog entry into pages (consecutive same-speaker entries) at a space,
    preferring right after . ! ? and the middle. Never inside {FD}h..{FD}l."""
    if nbytes_of(t) <= limit:
        return [t]
    best = None
    depth = 0
    for i, ch in enumerate(t):
        if t.startswith('{FD}h', i):
            depth += 1
        elif t.startswith('{FD}l', i):
            depth = max(0, depth - 1)
        if ch != ' ' or depth:
            continue
        a, b = t[:i], t[i + 1:]
        if nbytes_of(a) > limit:
            break
        score = (0 if a[-1:] in '.!?' else 1, abs(nbytes_of(a) - nbytes_of(b)))
        if best is None or score < best[0]:
            best = (score, a, b)
    if best is None:
        raise ValueError('255바이트를 넘는데 나눌 공백이 없음: %s' % t[:30])
    return [best[1]] + split_pages(best[2], limit)


def validate(src, kr, kind, adv, glyph_ok):
    """-> (kr_squeezed, errors, warnings)"""
    err, warn = [], []
    k = normalize(kr.strip())          # space after punctuation is kept as a wrap point and drawn zero-width by the hook
    if '\\n' in k or '\n' in k:
        err.append('개행 금지(엔진이 공백에서 알아서 접음)')
    ts, tk = tokens(src), tokens(k)
    if sorted(set(ts)) != sorted(set(tk)) or (len(set(ts)) == len(ts) and ts != tk):
        err.append('제어 토큰 불일치 %s -> %s' % (ts, tk))
    bad = sorted({c for c in TOKEN.sub('', k) if not glyph_ok(c)})
    if bad:
        err.append('글꼴에 없는 글자 %s' % ''.join(bad))
    nbytes = sum(2 if ord(c) >= 0x80 else 1 for c in re.sub(r'\{FD\}.', 'XX', re.sub(r'\{[0-9A-F]{2}\}', 'X', k))) + 1
    if '~' in k:
        warn.append('~ 자리에 끼워질 글의 폭은 검사 못 함')
    if nbytes > 255:
        if kind == '대사':
            try:
                pages = split_pages(k)
                warn.append('%d바이트 > 255 → 같은 화자 %d쪽으로 나눔' % (nbytes, len(pages)))
            except ValueError as e:
                err.append(str(e))
        else:
            err.append('%d바이트 > 255 (퀴즈는 쪽 나눔 불가)' % nbytes)
    if kind in ('대사', '퀴즈'):
        try:
            for ln in engine_wrap(k):
                if px(ln, adv) > BOX_PX:
                    warn.append('줄 %dpx > %dpx: %s' % (px(ln, adv), BOX_PX, ln))
        except ValueError as e:
            err.append(str(e))
    return k, err, warn
