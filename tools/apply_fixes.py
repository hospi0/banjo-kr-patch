"""Glossary/tone correction of the user's translation.
  in : my files/번역/*.tsv (read only)
  out: work/text/fixed/bk_text_NNN.tsv (same split) + work/text/교정_변경목록.tsv
Order: global glossary replacements (translation column only) -> per-row fixes (work/text/fixes.tsv)."""
import glob, os, re

ROOT = os.path.join(os.path.dirname(__file__), '..')
SRC = os.path.join(ROOT, 'my files', '번역')
OUT = os.path.join(ROOT, 'work', 'text', 'fixed')
LOG = os.path.join(ROOT, 'work', 'text', '교정_변경목록.tsv')
FIXES = os.path.join(ROOT, 'work', 'text', 'fixes.tsv')

# (from, to, reason) — applied in this order (longer phrases first)
GLOSSARY = [
    ('밴조', '반조', '주인공 이름 통일(하스피 지정)'),
    ('맘보', '멈보', '이름 통일(MUMBO=멈보)'),
    ('클룽고', '클렁고', '이름 통일(KLUNGO=클렁고, UI와 같게)'),
    ('직소 조각', '지기', '용어 통일(JIGSAW/JIGGY=지기)'),
    ('직소', '지기', '용어 통일(JIGSAW/JIGGY=지기)'),
    ('지그소', '지기', '용어 통일(JIGSAW/JIGGY=지기)'),
    ('퍼즐 조각', '지기', '용어 통일(JIGSAW PIECE=지기)'),
    ('트레저 트로브 코브', '보물의 만', '지명 통일(TREASURE TROVE COVE=보물의 만, UI와 같게)'),
    ('트레저 트로브', '보물의 만', '지명 통일(보물의 만)'),
    ('트레저 코브', '보물의 만', '지명 통일(보물의 만)'),
    ('보물섬 만', '보물의 만', '지명 통일(보물의 만)'),
    ('스파이럴 마운틴', '나선산', '지명 통일(SPIRAL MOUNTAIN=나선산, UI와 같게)'),
    ('나선 산', '나선산', '지명 통일(나선산)'),
    ('멈보 마운틴', '멈보의 산', '지명 통일(MUMBO\'S MOUNTAIN=멈보의 산, UI와 같게)'),
    ('버블글룹 늪지', '보글늪', '지명 통일(BUBBLEGLOOP SWAMP=보글늪, UI와 같게)'),
    ('버블글룹', '보글늪', '지명 통일(보글늪)'),
    ('프리지지 피크', '프리지피크', '지명 통일(FREEZEEZY PEAK=프리지피크, UI와 같게)'),
    ('프리지지', '프리지피크', '지명 통일(프리지피크)'),
    ('매드 몬스터 맨션', '미친 괴물 저택', '지명 통일(MAD MONSTER MANSION=미친 괴물 저택, UI와 같게)'),
    ('몬스터 맨션', '괴물 저택', '지명 통일(미친 괴물 저택)'),
    ('러스티 버킷 베이', '녹슨 양동이 만', '지명 통일(RUSTY BUCKET BAY=녹슨 양동이 만, UI와 같게)'),
    ('러스티 베이', '녹슨 양동이 만', '지명 통일(녹슨 양동이 만)'),
    ('러스티 버킷', '녹슨 양동이 만', '지명 통일(녹슨 양동이 만)'),
    ('클릭 클록 숲', '똑딱똑딱 숲', '지명 통일(CLICK CLOCK WOOD=똑딱똑딱 숲, UI와 같게)'),
    ('클릭 클록', '똑딱똑딱 숲', '지명 통일(똑딱똑딱 숲)'),
    ('징조', '진조', '이름 통일(JINJO=진조)'),
    ('보틀즈', '보틀스', '이름 통일(BOTTLES=보틀스)'),
    ('허니콤', '벌집', '용어 통일(HONEYCOMB=벌집)'),
    ('붉은 깃털', '빨간 깃털', '용어 통일(RED FEATHER=빨간 깃털)'),
    ('부리 양반', '부리양', '보틀스가 카주이를 부르는 별명 통일(BEAKY=부리양)'),
    ('게임 팩', '게임팩', '용어 통일(게임팩)'),
    ('락업', '록업', '이름 통일(LOCKUP=록업, UI와 같게)'),
    ('염염', '얌얌', '이름 통일(YUM-YUM=얌얌, UI와 같게)'),
    ('아이리', '에이리', '이름 통일(EYRIE=에이리, UI와 같게)'),
    ('탈론 트롯', '탤런 트롯', '기술 이름 통일(TALON TROT=탤런 트롯)'),
    ('탈론＿트롯', '탤런＿트롯', '기술 이름 통일(TALON TROT=탤런 트롯)'),
    ('원더 윙', '원더윙', '기술 이름 통일(WONDERWING=원더윙)'),
    ('원더＿윙', '원더윙', '기술 이름 통일(WONDERWING=원더윙)'),
    ('미스터 바일', '바일 씨', '이름 통일(MR. VILE=바일 씨)'),
    ('선장 블러버', '블러버 선장', '이름 통일(CAPTAIN BLUBBER=블러버 선장)'),
    ('붐박스', '붐 박스', '이름 통일(BOOM BOX=붐 박스, UI와 같게)'),
    ('스니핏', '스니펫', '이름 통일(SNIPPET=스니펫, UI와 같게)'),
    ('촘파', '참파', '이름 통일(CHOMPA=참파, UI와 같게)'),
    ('슈래플', '슈래프널', '이름 통일(SHRAPNEL=슈래프널, UI와 같게)'),
    ('위플래시', '휩래시', '이름 통일(WHIPLASH=휩래시, UI와 같게)'),
    ('빅벗', '빅버트', '이름 통일(BIGBUTT=빅버트, UI와 같게)'),
    ('칭커', '친커', '이름 통일(CHINKER=친커, UI와 같게)'),
    ('멈보점보', '멈보 점보', '이름 통일(MUMBO JUMBO=멈보 점보, UI와 같게)'),
]


def jong(ch):
    """받침: None(한글 아님) / 0(없음) / 8(ㄹ) / 그 밖의 번호."""
    o = ord(ch) - 0xAC00
    return (o % 28) if 0 <= o < 11172 else None


# 받침 있을 때 / 없을 때 (ㄹ 받침은 «로»). 긴 것부터.
JOSA = [('이에요', '예요'), ('이야', '야'), ('이랑', '랑'), ('이나', '나'), ('으로', '로'),
        ('은', '는'), ('을', '를'), ('과', '와'), ('이', '가')]
_JOSA_RE = '|'.join(sorted({x for pair in JOSA for x in pair}, key=len, reverse=True))


def fit_josa(word, josa):
    """word 뒤에 오는 조사를 word 받침에 맞게."""
    j = jong(word[-1])
    if j is None:
        return josa
    for cons, vow in JOSA:
        if josa in (cons, vow):
            if cons == '으로':
                return '로' if j in (0, 8) else '으로'
            return vow if j == 0 else cons
    return josa


def replace_term(t, a, b):
    """a→b 로 바꾸면서 바로 뒤 조사를 b 받침에 맞춘다(받침이 달라지는 용어 — 퍼즐 조각→지기 등).
    «이/가·이야»는 뒤가 한글이 아닐 때만 조사로 본다(«조각이다»류 오인 방지)."""
    def sub(m):
        jo = m.group(1)
        if jo is None:
            return b
        if jo in ('이', '가', '이야', '야') and m.group(2) and jong(m.group(2)) is not None:
            return b + jo
        return b + fit_josa(b, jo)
    return re.sub(re.escape(a) + '(' + _JOSA_RE + ')?(?=(.?))', sub, t)


def main():
    fixes = {}
    for ln in open(FIXES, encoding='utf-8').read().splitlines()[1:]:
        if ln.strip():
            loc, new, why = ln.split('\t')
            assert loc not in fixes, 'duplicate fix ' + loc
            fixes[loc] = (new, why)
    os.makedirs(OUT, exist_ok=True)
    log = ['위치\t원문\t수정 전\t수정 후\t이유']
    seen = set()
    for f in sorted(glob.glob(os.path.join(SRC, '*.tsv'))):
        lines = open(f, encoding='utf-8-sig').read().splitlines()
        out = [lines[0]]
        for ln in lines[1:]:
            c = ln.split('\t')
            if len(c) > 5 and c[5]:
                before = c[5]
                t, why = before, []
                for a, b, r in GLOSSARY:
                    if a in t:
                        t = replace_term(t, a, b)
                        why.append(r)
                if c[1] in fixes:
                    t, r = fixes[c[1]]
                    why.append(r)
                    seen.add(c[1])
                if t != before:
                    c[5] = t
                    log.append('\t'.join((c[1], c[4], before, t, ' / '.join(dict.fromkeys(why)))))
            out.append('\t'.join(c))
        open(os.path.join(OUT, os.path.basename(f)), 'w', encoding='utf-8', newline='\n').write('\n'.join(out) + '\n')
    missing = set(fixes) - seen
    assert not missing, 'fixes for unknown rows: %s' % sorted(missing)
    open(LOG, 'w', encoding='utf-8', newline='\n').write('\n'.join(log) + '\n')
    print('changed rows', len(log) - 1, '->', OUT)


if __name__ == '__main__':
    main()
