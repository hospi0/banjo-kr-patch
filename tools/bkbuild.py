"""Shared build pieces: rarezip, checksums, code segments, Korean glyph blob + hooks."""
import os, struct, sys, zlib
sys.path.insert(0, os.path.dirname(__file__))
import bkrom, mips, bdf

# --- code segments (ROM, Rev1) ---------------------------------------------
CORE1_TEXT = 0xF1C830       # VRAM 0x8023D680, followed immediately by core1 data
CORE1_DATA = 0xF391BB
CORE1_END = 0xF3ADB0        # core2 starts here
CORE2_TEXT = 0xF3ADB0       # VRAM 0x80285DD0
CORE2_DATA = 0xF9FA9E
CORE2_END = 0xFA6F80        # next overlay
CORE2_VRAM = 0x80285DD0
CRC_SEG = 0x5E70            # boot c1,c2 | core1 text c1,c2 | core1 data c1,c2
OFS_CORE2_TEXT_CRC2 = 0xF264    # in core2 data (D_803727F4)
OFS_CORE2_DATA_CRC2 = 0xE54     # in core1 data (D_80276574)

READ_DMA = 0x802401D0       # parallel_readDMA(vaddr, devaddr, size), core1
FONT_INIT_CALL = 0x802F42C4  # print_init: jal func_802F7A2C(3)
FUNC_802F7A2C = 0x802F6B3C
GET_SPRITE = 0x802F44F8     # print_getBoldFontLetterSprite(id, *type)
DRAW_FONT0 = 0x802F46DC     # _printbuffer_draw_letter: case FONTS_0_DIALOG
DRAW_FONT0_OUT = 0x802F46FC
DRAW_CASE2_BEQ = 0x802F46CC  # beq -> FONTS_2 (unused); nopped, block reused for stub
STUB_AT = 0x802F47AC        # 51 free instructions up to 0x802F4874
DRAW_FONT1 = 0x802F4708     # draw_letter case FONTS_1: slti at,t9,0x80 / beqz at,47A0 / move v1,t9
DRAW_FONT1_OUT = 0x802F47A0 # a1=2, a0=letter_id, -> common draw (t0 = valid)
CALC_FONT1 = 0x802F5DDC     # print_calculateLetterXPos: slti at,a3,0x80 / beqz at,5E80 / move a0,a3
CALC_FONT1_OUT = 0x802F5E80 # v0 = valid, 0x44(sp) = letter_id
BOLD_W, BOLD_H = 32, 24     # texture size (IA8)
BOLD_X = 26                 # sprite width field: print advances x-4 = 22 px (ink is 22 + 1 px shadow)
BOLD_STRIDE = 8 + BOLD_W * BOLD_H   # 776

# --- Korean blob in expansion RAM ------------------------------------------
KR_RAM = 0x80400000
GLYPH_W, GLYPH_H = 16, 13
GLYPH_STRIDE = 8 + GLYPH_W * GLYPH_H    # BKSpriteTextureBlock header + I8 pixels = 216 (8-aligned)
LEAD0, LEAD1 = 0x80, 0xA0   # lead byte range [0x80, 0xA0)
TRAIL0, NTRAIL = 0x80, 125  # trail byte 0x80..0xFC
KR_ID0 = 0x1000

FONT_PATH = r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11-Bold.bdf'
BOLD_FONT_PATH = r'C:\claude\utils\font\Galmuri-v2.40.3\Galmuri11.bdf'   # x2 for the bold font (Bold cut closes ㄹ gaps)


def crc(b):
    c1, c2 = 0, 0xFFFFFFFF
    for x in b:
        c1 = (c1 + x) & 0xFFFFFFFF
        c2 ^= (x << (c1 & 0x17)) & 0xFFFFFFFF
    return c1, c2


def rzip(raw):
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
    return b'\x11\x72' + struct.pack('>I', len(raw)) + c.compress(raw) + c.flush()


def unrzip_at(rom, p):
    """-> (raw, compressed_length)"""
    size = struct.unpack_from('>I', rom, p + 2)[0]
    o = zlib.decompressobj(-15)
    raw = o.decompress(rom[p + 6:p + 6 + size + 0x10000])
    assert len(raw) == size and o.eof
    return raw, 6 + (len(rom[p + 6:p + 6 + size + 0x10000]) - len(o.unused_data))


def encode_kr(text, cmap):
    """str -> bytes. ASCII kept, Hangul/others mapped to 2-byte codes via cmap (char -> glyph index)."""
    out = bytearray()
    for ch in text:
        if ord(ch) < 0x80:
            out.append(ord(ch))
        else:
            g = cmap[ch]
            out += bytes((LEAD0 + g // NTRAIL, TRAIL0 + g % NTRAIL))
            assert out[-2] < LEAD1
    return bytes(out)


def render_glyphs(chars):
    f = bdf.BdfFont(FONT_PATH)
    blob = b''
    for ch in chars:
        g = f.glyphs[ord(ch)]
        w, h, xo, yo = g.bbx
        px = bytearray(GLYPH_W * GLYPH_H)
        top = 11 - (h + yo)                 # baseline at row 11 (original caps occupy rows 1..10)
        for y, row in enumerate(g.bitmap()):
            for x, v in enumerate(row):
                X, Y = x + xo, y + top
                if v and 0 <= X < GLYPH_W and 0 <= Y < GLYPH_H:
                    px[Y * GLYPH_W + X] = 0xFF
        adv = g.dwidth[0]
        blob += struct.pack('>hhHH', adv, GLYPH_H, GLYPH_W, GLYPH_H) + bytes(px)
    return blob


def render_bold_glyphs(chars):
    """Bold-font Hangul: Galmuri11 (regular) x2 + 1 px black drop shadow, IA8 32x24 texture (white 0xFF, shadow 0x0F)."""
    f = bdf.BdfFont(BOLD_FONT_PATH)
    blob = b''
    for ch in chars:
        g = f.glyphs[ord(ch)]
        w, h, xo, yo = g.bbx
        ink = set()
        top = 11 - (h + yo)
        for y, row in enumerate(g.bitmap()):
            for x, v in enumerate(row):
                if v:
                    for dy in (0, 1):
                        for dx in (0, 1):
                            ink.add(((x + xo) * 2 + dx, (y + top) * 2 + dy))
        px = bytearray(BOLD_W * BOLD_H)
        for (X, Y) in ink:                  # 1 px drop shadow (a full outline fills the 2 px gaps between strokes)
            for dy, dx in ((1, 1), (0, 1), (1, 0)):
                    xx, yy = X + dx, Y + dy
                    if 0 <= xx < BOLD_W and 0 <= yy < BOLD_H and not px[yy * BOLD_W + xx]:
                        px[yy * BOLD_W + xx] = 0x0F
        for (X, Y) in ink:
            if 0 <= X < BOLD_W and 0 <= Y < BOLD_H:
                px[Y * BOLD_W + X] = 0xFF
        blob += struct.pack('>hhHH', BOLD_X, BOLD_H, BOLD_W, BOLD_H) + bytes(px)
    return blob


def hook_code(glyph_ram, bold_ram=0):
    """Code living in expansion RAM. KR_RAM+0 = pending lead (dialog), +1 = previous letter,
    +2 = pending lead (bold coord pass), +3 = pending byte (bold draw pass)."""
    a = mips.Asm(KR_RAM + 0x10, {'PEND': 0, 'OUT0': DRAW_FONT0_OUT, 'GLY': glyph_ram, 'BGLY': bold_ram,
                                 'GETSPR_CONT': GET_SPRITE + 8, 'BOLD_CONT': DRAW_FONT1 + 0xC,
                                 'BOLD_OUT': DRAW_FONT1_OUT, 'CALC_CONT': CALC_FONT1 + 0xC,
                                 'CALC_OUT': CALC_FONT1_OUT})
    prog = '''
    draw:                       # v1 = letter, t4 already = 1 (set in delay slot)
      lui t6, 0x8040
      lbu t7, 0(t6)
      bnez v1, d_nz
      nop
      sb zero, 0(t6)            # letter 0 = end of string -> drop pending lead
      sb zero, 1(t6)            #   and previous letter
      sb zero, 2(t6)            #   and bold-font pendings (coord pass / draw pass)
      sb zero, 3(t6)
      j OUT0
      nop
    d_nz:
      lbu t9, 1(t6)             # previous letter
      sb v1, 1(t6)
      bnez t7, d_trail
      sltiu at, v1, 0x80
      bnez at, d_ascii
      sltiu at, v1, 0xA0
      beqz at, d_ascii
      nop
      sb v1, 0(t6)              # lead byte: remember, draw nothing
      j OUT0
      nop
    d_trail:
      sb zero, 0(t6)
      addiu t7, t7, -0x80
      sll t8, t7, 7
      sll t9, t7, 1
      subu t8, t8, t9
      subu t8, t8, t7           # (lead-0x80)*125
      addu t8, t8, v1
      addiu t8, t8, 0xF80       # + 0x1000 - 0x80
      sw t8, 0x214(sp)
      j OUT0
      addiu t0, zero, 1
    d_ascii:
      addiu at, zero, 0x20      # space right after punctuation: zero width (rule: no space after punctuation;
      bne v1, at, d_asc2        #   the byte stays in the data because the engine wraps only at spaces)
      nop
      addiu at, zero, 44
      beq t9, at, d_sup
      nop
      addiu at, zero, 46
      beq t9, at, d_sup
      nop
      addiu at, zero, 33
      beq t9, at, d_sup
      nop
      addiu at, zero, 63
      beq t9, at, d_sup
      nop
      addiu at, zero, 58
      beq t9, at, d_sup
      nop
      addiu at, zero, 59
      beq t9, at, d_sup
      nop
      addiu at, zero, 41
      beq t9, at, d_sup
      nop
      addiu at, zero, 39
      beq t9, at, d_sup
      nop
      addiu at, zero, 34
      beq t9, at, d_sup
      nop
      b d_asc2
      nop
    d_sup:
      addiu t8, zero, 1         # turn it into an unknown control byte -> switch draws nothing
      sb t8, 0x223(sp)
      j OUT0
      nop
    d_asc2:                     # original range check 0x21..0x6B
      slti at, v1, 0x21
      bnez at, d_out
      slti at, v1, 0x6C
      beqz at, d_out
      addiu t8, v1, -0x21
      sw t8, 0x214(sp)
      addiu t0, zero, 1
    d_out:
      j OUT0
      nop

    getspr:                     # a0 = letter id, a1 = int *type
      slti at, a0, 0x1000
      beqz at, g_kr
      nop
      lui a2, 0x8038
      j GETSPR_CONT
      addiu a2, a2, -0x318
    g_kr:
      addiu t6, zero, 0x100     # IA8 (same type as the dialog font 0x6EB)
      sw t6, 0(a1)
      slti at, a0, 0x2000
      beqz at, g_bold
      nop
      addiu t7, a0, -0x1000
      sll t8, t7, 8
      sll t9, t7, 5
      subu t8, t8, t9
      sll t9, t7, 3
      subu t8, t8, t9           # *216
      lui v0, %hi(GLY)
      addiu v0, v0, %lo(GLY)
      jr ra
      addu v0, v0, t8
    g_bold:
      addiu t7, a0, -0x2000
      sll t8, t7, 9
      sll t9, t7, 8
      addu t8, t8, t9
      sll t9, t7, 3
      addu t8, t8, t9           # *776
      lui v0, %hi(BGLY)
      addiu v0, v0, %lo(BGLY)
      jr ra
      addu v0, v0, t8

    bdraw:                      # bold font (FONTS_1) branch of draw_letter; t9 = v1 = letter
      sltiu at, t9, 0x80
      beqz at, b_kr
      nop
      bnez t9, b_cont
      nop
      lui t6, 0x8040
      sb zero, 3(t6)
    b_cont:
      j BOLD_CONT
      nop
    b_kr:
      lui t6, 0x8040
      lbu t7, 3(t6)
      mfc1 t8, f24              # scale < 0 -> print_bold_overlapping draws the string backwards
      bltz t8, b_rev
      nop
      bnez t7, b_fwd_pair
      sltiu at, t9, 0xA0
      beqz at, b_inv
      nop
      sb t9, 3(t6)              # forward: lead first
      b b_inv
      nop
    b_fwd_pair:
      sb zero, 3(t6)
      b b_id
      move t8, t9               # t7 = lead, t8 = trail
    b_rev:
      bnez t7, b_rev_pair
      nop
      sb t9, 3(t6)              # backwards: trail first
      b b_inv
      nop
    b_rev_pair:
      sb zero, 3(t6)
      move t8, t7
      move t7, t9
    b_id:
      addiu t7, t7, -0x80
      sll t9, t7, 7
      sll at, t7, 1
      subu t9, t9, at
      subu t9, t9, t7
      addu t9, t9, t8
      addiu t9, t9, 0x1F80      # 0x2000 + g
      sw t9, 0x214(sp)
      j BOLD_OUT
      addiu t0, zero, 1
    b_inv:
      j BOLD_OUT
      move t0, zero

    bcalc:                      # print_calculateLetterXPos (bold, forward pass); a3 = a0 = letter
      sltiu at, a3, 0x80
      beqz at, c_kr
      nop
      j CALC_CONT
      nop
    c_kr:
      lui t6, 0x8040
      lbu t7, 2(t6)
      bnez t7, c_trail
      sltiu at, a3, 0xA0
      beqz at, c_inv
      nop
      sb a3, 2(t6)              # lead: one Korean-wide step (all bold Hangul share the width)
      addiu t8, zero, 0x2000
      sw t8, 0x44(sp)
      j CALC_OUT
      addiu v0, zero, 1
    c_trail:
      sb zero, 2(t6)
    c_inv:
      j CALC_OUT
      move v0, zero
    '''.splitlines()
    code = a.assemble(prog)
    return code, a.syms


def core2_patches(syms, blob_rom, blob_size):
    """-> list of (vram, bytes)"""
    p = []
    asm = lambda va, lines: (va, mips.Asm(va).assemble(lines))
    p.append(asm(DRAW_FONT0, ['j %d' % syms['draw'], 'addiu t4, zero, 1']))
    p.append(asm(GET_SPRITE, ['j %d' % syms['getspr'], 'nop']))
    p.append(asm(DRAW_FONT1, ['j %d' % syms['bdraw'], 'move v1, t9']))
    p.append(asm(CALC_FONT1, ['j %d' % syms['bcalc'], 'move a0, a3']))
    p.append(asm(DRAW_CASE2_BEQ, ['nop']))
    stub = [
        'addiu sp, sp, -0x20', 'sw ra, 0x1c(sp)', 'sw a0, 0x18(sp)',
        'lui a0, 0x8040',
        'lui a1, %d' % (blob_rom >> 16), 'ori a1, a1, %d' % (blob_rom & 0xFFFF),
        'lui a2, %d' % (blob_size >> 16), 'jal %d' % READ_DMA, 'ori a2, a2, %d' % (blob_size & 0xFFFF),
        'lw a0, 0x18(sp)', 'lw ra, 0x1c(sp)',
        'j %d' % FUNC_802F7A2C, 'addiu sp, sp, 0x20',
    ]
    p.append(asm(STUB_AT, stub))
    assert STUB_AT + 4 * len(stub) <= 0x802F4878
    p.append(asm(FONT_INIT_CALL, ['jal %d' % STUB_AT]))
    return p


CORE2_DATA_VRAM = 0x80362790   # core2 data follows its text in RAM


def core2_ui_refs(rom):
    """-> (data_refs, code_refs): address -> [offset in core2 data of a pointer word] /
    [(vram of lui, vram of addiu)] for every lui/addiu pair in core2 text."""
    import collections
    c2t, l = unrzip_at(rom, CORE2_TEXT)
    c2d, _ = unrzip_at(rom, CORE2_TEXT + l)
    W = struct.unpack('>%dI' % (len(c2t) // 4), c2t[:len(c2t) // 4 * 4])
    code = collections.defaultdict(list)
    for i, w in enumerate(W):
        if w >> 26 == 0xF:
            rt, h = (w >> 16) & 31, w & 0xFFFF
            for j in range(i + 1, min(i + 12, len(W))):
                v = W[j]
                if v >> 26 == 9 and (v >> 21) & 31 == rt:
                    a = ((h << 16) + ((v & 0xFFFF) ^ 0x8000) - 0x8000) & 0xFFFFFFFF
                    code[a].append((CORE2_VRAM + i * 4, CORE2_VRAM + j * 4))
                    break
    data = collections.defaultdict(list)
    for i in range(0, len(c2d) - 3, 4):
        data[struct.unpack_from('>I', c2d, i)[0]].append(i)
    return data, code, c2d


def rebuild_code(rom, core2_text_patches, core2_data_patches=()):
    """Patch core2 text (+data), fix the checksum chain, recompress core1+core2 in place.
    core2_data_patches: [(offset in core2 data, bytes)]"""
    c1t, c1t_len = unrzip_at(rom, CORE1_TEXT)
    c1d, c1d_len = unrzip_at(rom, CORE1_TEXT + c1t_len)
    c2t, c2t_len = unrzip_at(rom, CORE2_TEXT)
    c2d, c2d_len = unrzip_at(rom, CORE2_TEXT + c2t_len)
    assert CORE1_TEXT + c1t_len == CORE1_DATA and CORE2_TEXT + c2t_len == CORE2_DATA
    c1d, c2t, c2d = bytearray(c1d), bytearray(c2t), bytearray(c2d)
    # original checksums must match the stored chain
    assert struct.unpack_from('>I', c2d, OFS_CORE2_TEXT_CRC2)[0] == crc(c2t)[1]
    assert struct.unpack_from('>I', c1d, OFS_CORE2_DATA_CRC2)[0] == crc(c2d)[1]
    for va, b in core2_text_patches:
        o = va - CORE2_VRAM
        c2t[o:o + len(b)] = b
    for o, b in core2_data_patches:
        assert not (o <= OFS_CORE2_TEXT_CRC2 < o + len(b))
        c2d[o:o + len(b)] = b
    struct.pack_into('>I', c2d, OFS_CORE2_TEXT_CRC2, crc(c2t)[1])
    struct.pack_into('>I', c1d, OFS_CORE2_DATA_CRC2, crc(c2d)[1])
    t1, t2 = crc(c1t)
    d1, d2 = crc(c1d)
    assert struct.unpack_from('>II', rom, CRC_SEG + 8) == (t1, t2)
    struct.pack_into('>II', rom, CRC_SEG + 16, d1, d2)
    # core1: text unchanged -> keep original bytes, recompress data right after it
    z = rzip(bytes(c1d))
    assert CORE1_DATA + len(z) <= CORE1_END, 'core1 data too big'
    rom[CORE1_DATA:CORE1_END] = z + bytes(CORE1_END - CORE1_DATA - len(z))
    zt, zd = rzip(bytes(c2t)), rzip(bytes(c2d))
    assert CORE2_TEXT + len(zt) + len(zd) <= CORE2_END, 'core2 too big'
    rom[CORE2_TEXT:CORE2_END] = zt + zd + bytes(CORE2_END - CORE2_TEXT - len(zt) - len(zd))
    return len(zt) + len(zd), CORE2_END - CORE2_TEXT


ASSET_BASE_HI = 0x8033ADD0  # assetCache_init: lui t6, 0      -> lui t6, hi(new)
ASSET_BASE_LO = 0x8033ADDC  #                 addiu a1,t6,0x5E90 -> addiu a1, t6, lo(new)
PRINT_LEN = 0x80314924      # zoombox __get_str_print_len(s, n), 70 instructions to 0x80314A3C


def print_len_patch():
    """Width in units: ASCII 1, Korean 1.5 (lead 2 + trail 1 half-units), {FD}+next 0. Returns floor(half/2)."""
    prog = '''
      move v1, zero
      move t0, zero
      move t1, zero
      move a2, zero
    L:
      beq a2, a1, done
      nop
      addu t2, a0, a2
      lbu t2, 0(t2)
      addiu a2, a2, 1
      beqz t0, c1
      nop
      b L
      move t0, zero
    c1:
      addiu at, zero, 0xFD
      bne t2, at, c2
      nop
      b L
      addiu t0, zero, 1
    c2:
      beqz t1, c3
      nop
      move t1, zero
      b L
      addiu v1, v1, 1
    c3:
      sltiu at, t2, 0x80
      bnez at, c4
      sltiu at, t2, 0xA0
      beqz at, c4
      nop
      addiu t1, zero, 1
    c4:
      b L
      addiu v1, v1, 2
    done:
      jr ra
      sra v0, v1, 1
    '''.splitlines()
    code = mips.Asm(PRINT_LEN).assemble(prog)
    assert len(code) <= 0x80314A3C - PRINT_LEN
    return PRINT_LEN, code + bytes(0x80314A3C - PRINT_LEN - len(code))


def asset_base_patches(new_base):
    asm = lambda va, line: (va, mips.Asm(va).assemble([line]))
    return [asm(ASSET_BASE_HI, 'lui t6, %d' % mips.hi(new_base)),
            asm(ASSET_BASE_LO, 'addiu a1, t6, %d' % mips.lo(new_base))]


def build_quiz(head5, ent):
    out = bytearray(head5)
    out.append(len(ent))
    for cmd, raw in ent:
        assert len(raw) < 256
        out += bytes((cmd, len(raw))) + raw
    return bytes(out)


def build_asset_region(rom, tab, replaced):
    """replaced: {asset_id: compressed bytes}. -> region bytes (table + data) for a new base.
    Untouched assets keep their exact original slot bytes."""
    n = len(tab)
    data = bytearray()
    offs = []
    for k in range(n):
        p, size, comp, typ = tab[k]
        offs.append(len(data))
        blob = replaced.get(k, rom[p:p + size])
        data += blob
        data += bytes(-len(data) % 8)
    head = struct.pack('>I', n) + b'\xff\xff\xff\xff'
    ent = b''.join(struct.pack('>IHH', offs[k], tab[k][2], tab[k][3]) for k in range(n))
    return head + ent + bytes(data)


def build_dialog(nlang_secs):
    """[[(cmd, raw_bytes)], [..]] (raw as parse_dialog returns, text incl. NUL) -> dialog asset (nlang=1)."""
    out = bytearray(b'\x01\x03\x00')
    for sec in nlang_secs:
        out.append(len(sec))
        for cmd, raw in sec:
            assert len(raw) < 256
            out += bytes((cmd, len(raw))) + raw
    return bytes(out)
