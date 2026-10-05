"""Dump UI strings from the compressed core data segment to work/bk_code_strings.tsv.
Columns: rom_block(hex)  offset_in_decompressed(hex)  maxlen(bytes incl. NUL, up to next string/align)  text"""
import os, re, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
import bkrom

CORE_DATA = 0xF9FA9E   # rarezip block, 91,648 B decompressed: menus, level names, credits cast
OUT = os.path.join(os.path.dirname(__file__), '..', 'work', 'bk_code_strings.tsv')


def main():
    rom = bkrom.load_rom()
    r = bkrom.unzip(rom[CORE_DATA:CORE_DATA + 0x20000])
    rows = []
    for m in re.finditer(rb'[ -~]{3,}\x00', r):
        s = m.group()[:-1]
        if sum(c in b'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for c in s) < 3 or s != s.upper():
            continue
        end = m.end()
        while end < len(r) and r[end] == 0:
            end += 1
        rows.append('%X\t%X\t%d\t%s' % (CORE_DATA, m.start(), end - m.start(), s.decode()))
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('block\toffset\tmaxlen\ttext\n' + '\n'.join(rows) + '\n')
    print(len(rows), 'strings ->', OUT)


if __name__ == '__main__':
    main()
