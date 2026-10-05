"""Translation TSVs.
  work/text/bk_text.tsv            — whole file
  my files/tsv/bk_text_NNN.tsv     — split at 29 KB (UTF-8) for the user
Columns: ID  위치  구분  화자  원문  번역
  위치: dialog/quiz = asset:sec:idx (sec Q = quiz), UI = C:offset in core2 data (hex)
  화자: dialog/quiz command byte (hex) — same value = same speaker portrait"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import bkrom, extract_dialog, extract_code_strings

ROOT = os.path.join(os.path.dirname(__file__), '..')
WHOLE = os.path.join(ROOT, 'work', 'text', 'bk_text.tsv')
SPLIT = os.path.join(ROOT, 'my files', 'tsv')
HEAD = 'ID\t위치\t구분\t화자\t원문\t번역\n'
LIMIT = 29 * 1024
UI_JUNK = {'QVCX', 'HCH', 'TREP', 'TREPGCP'}


def rows():
    rom = bkrom.load_rom()
    tab = bkrom.asset_table(rom)
    out = []
    for k in range(len(tab)):
        if not tab[k][1] or not tab[k][2]:
            continue
        r = bkrom.asset(rom, tab, k)
        if bkrom.is_quiz(r):
            _, ent, _ = bkrom.parse_quiz(r)
            for i, (cmd, d) in enumerate(ent):
                out.append(('%04X:Q:%d' % (k, i), '퀴즈', '%02X' % cmd, extract_dialog.show(d)))
        elif bkrom.is_dialog(r):
            _, secs, _ = bkrom.parse_dialog(r)
            for si, sec in enumerate(secs):
                for i, (cmd, d) in enumerate(sec):
                    if cmd >= 0x80:
                        out.append(('%04X:%d:%d' % (k, si, i), '대사', '%02X' % cmd, extract_dialog.show(d)))
    core = bkrom.unzip(rom[extract_code_strings.CORE_DATA:extract_code_strings.CORE_DATA + 0x20000])
    import re
    for m in re.finditer(rb'[ -~]{3,}\x00', core):
        s = m.group()[:-1].decode()
        if s in UI_JUNK or s.startswith('0123456789') or sum(c.isupper() for c in s) < 3 or s != s.upper():
            continue
        out.append(('C:%X' % m.start(), 'UI', '', s))
    return out


def main():
    lines = ['%05d\t%s\t%s\t%s\t%s\t\n' % ((n + 1,) + r) for n, r in enumerate(rows())]
    os.makedirs(os.path.dirname(WHOLE), exist_ok=True)
    with open(WHOLE, 'w', encoding='utf-8', newline='\n') as f:
        f.write(HEAD + ''.join(lines))
    os.makedirs(SPLIT, exist_ok=True)
    for f in os.listdir(SPLIT):
        if f.startswith('bk_text_') and f.endswith('.tsv'):
            os.remove(os.path.join(SPLIT, f))
    files, cur, size = [], [], len(HEAD.encode())
    for ln in lines:
        b = len(ln.encode())
        if cur and size + b > LIMIT:
            files.append(cur); cur, size = [], len(HEAD.encode())
        cur.append(ln); size += b
    if cur:
        files.append(cur)
    for i, fl in enumerate(files):
        with open(os.path.join(SPLIT, 'bk_text_%03d.tsv' % (i + 1)), 'w', encoding='utf-8', newline='\n') as f:
            f.write(HEAD + ''.join(fl))
    print(len(lines), 'rows ->', len(files), 'files')


if __name__ == '__main__':
    main()
