"""Dump every dialogue block to work/bk_dialog.tsv.
Columns: asset(hex)  sec(0/1, Q=quiz)  idx  cmd(hex)  text   — control entries (cmd<0x80) kept as {hex}."""
import os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import bkrom

OUT = os.path.join(os.path.dirname(__file__), '..', 'work', 'bk_dialog.tsv')


def show(b):
    s = ''
    for x in b.rstrip(b'\0'):
        s += chr(x) if 0x20 <= x < 0x7F and x not in (0x7B, 0x7D) else '{%02X}' % x
    return s


def main():
    rom = bkrom.load_rom()
    tab = bkrom.asset_table(rom)
    rows, nblk, nchar, cmds = [], 0, 0, collections.Counter()
    for k in range(len(tab)):
        if not tab[k][1] or not tab[k][2]:
            continue
        r = bkrom.asset(rom, tab, k)
        if bkrom.is_quiz(r):
            nblk += 1
            _, ent, _ = bkrom.parse_quiz(r)
            for i, (cmd, data) in enumerate(ent):
                cmds[cmd] += 1
                nchar += len(data.rstrip(b'\0'))
                rows.append('%04X\tQ\t%d\t%02X\t%s' % (k, i, cmd, show(data)))
            continue
        if not bkrom.is_dialog(r):
            continue
        nblk += 1
        _, secs, _ = bkrom.parse_dialog(r)
        for si, sec in enumerate(secs):
            for i, (cmd, data) in enumerate(sec):
                cmds[cmd] += 1
                t = show(data)
                if cmd >= 0x80:
                    nchar += len(data.rstrip(b'\0'))
                rows.append('%04X\t%d\t%d\t%02X\t%s' % (k, si, i, cmd, t))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('asset\tsec\tidx\tcmd\ttext\n' + '\n'.join(rows) + '\n')
    print('blocks', nblk, 'rows', len(rows), 'text chars', nchar)
    print('cmds', sorted(cmds.items()))


if __name__ == '__main__':
    main()
