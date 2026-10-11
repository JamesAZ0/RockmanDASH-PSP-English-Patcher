"""Decode the Rockman DASH font (FONT.BIN -> bg/char/font.dat) into two 256x256 2bpp pages. Library: used by
build_font.py (adds glyphs), patch_eboot.py (measures letter widths) and the analysis tools. Reference:
docs/RESEARCH.md §4.
The font entry is a 0x800-byte container header followed by 0x8000 bytes: one 256x256 4-bit texture that holds two
independent 2-bit images (pixel values 0-3, 0 = empty).
Storage (from DashEditor FONT.py): 128x32-pixel blocks, 64 bytes per block row; each byte holds 2 pixels
for page A (bits 0-1, 4-5) and the same 2 pixels for page B (bits 2-3, 6-7).
Glyph lookup (from the PSP EBOOT text renderer at 0x3C810): code < 0x1BA -> page A, else page B with code-0x1BA;
u = (code % 21) * 12, v = (code // 21) * 12, 12x12 cells.
The same decoding reads the PS1's US font KAIFONT (build_font.py)."""
import struct
# dat: a whole font entry (header + data) or just the 0x8000 data bytes -> (page A, page B) as [y][x] values 0-3
def pages(dat):
    px = dat[0x800:0x800+0x8000] if len(dat) >= 0x8800 else dat
    A = [[0]*256 for _ in range(256)]; B = [[0]*256 for _ in range(256)]; off = 0
    for y in range(0, 256, 32):
        for x in range(0, 256, 128):
            for by in range(32):
                for bx in range(0, 128, 2):
                    b = px[off]; off += 1
                    A[y+by][x+bx] = b & 3; A[y+by][x+bx+1] = (b >> 4) & 3
                    B[y+by][x+bx] = (b >> 2) & 3; B[y+by][x+bx+1] = (b >> 6) & 3
    return A, B
# the 12x12 cell of a character code as 12 rows of 12 values
def glyph(P, code):
    A, B = P
    pg, c = (A, code) if code < 0x1BA else (B, code - 0x1BA)
    u, v = (c % 21) * 12, (c // 21) * 12
    return [row[u:u+12] for row in pg[v:v+12]]
# (first, last) column that has any ink, or None for an empty glyph: the basis of the variable-width table
def ink(g):
    cols = [x for x in range(12) if any(g[y][x] for y in range(12))]
    return (cols[0], cols[-1]) if cols else None
