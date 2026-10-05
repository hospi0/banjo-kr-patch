"""엑스박스 360 텍스처 (textures.bin) 읽기 — 32bpp 타일 해제."""
import struct
from PIL import Image

def tiled_offset(x, y, w, bpp_log2):
    # XGAddress2DTiledOffset
    aw = (w + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (aw >> 5)) << (bpp_log2 + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << bpp_log2
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + bpp_log2)) + ((y & 1) << 4)
    return ((((off & ~511) << 3) + ((off & 448) << 2) + (off & 63)
             + ((y & 16) << 7) + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> bpp_log2)

class Textures:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        self.n = struct.unpack('>I', self.d[:4])[0]
    def entry(self, i):
        return struct.unpack('>5I', self.d[4 + i * 20:24 + i * 20])
    def base(self):
        return 4 + self.n * 20
    def raw(self, i):
        o, w, h, s, f = self.entry(i)
        return self.d[o:o + s]
    def image(self, i, base=None):
        o, w, h, s, f = self.entry(i)
        b = self.d[(base if base is not None else 0x73984) + o:]
        img = Image.new('RGBA', (w, h))
        px = img.load()
        aw = (w + 31) & ~31
        for y in range(h):
            for x in range(w):
                t = tiled_offset(x, y, aw, 2) * 4
                a, r, g, bb = b[t], b[t + 1], b[t + 2], b[t + 3]
                px[x, y] = (r, g, bb, a)
        return img
