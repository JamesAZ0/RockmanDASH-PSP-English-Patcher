"""Add the English symbols the PSP font lacks, taken from the PS1 English font (project decision 2026-09-29).
Runs before tools/patch_eboot.py. Reference: docs/RESEARCH.md §4.
The PSP font (FONT.BIN) is the Japanese font; the PS1 disc has a nearly identical FONT.BIN, and the US game draws its
text with a second font that only the PS1 has:
PS1 (US) CDDATA/DAT/KAIFONT.BIN ..\\bg\\char\\kaifont.dat is the US font; its cells are laid out by text code, so
alpha / omega / ; / = are PS1 codes 0x80-0x83 at cells 0x80-0x83. They are copied into cells of the PSP font
(FONT.BIN ..\\bg\\char\\font.dat) that are empty and unused by any Japanese text (checked: MSG files and the EBOOT
system strings): 0x10D, 0x10E, 0x10F, 0x1A5. tools/msgtool.py maps the PS1 codes to these cells and
tools/patch_eboot.py measures their widths from this font. (All other English characters already exist in the
Japanese font: letters, digits, and the symbol set at 0xFD-0x10B.)
Inputs : extracted/psp/FONT/bg/char/font.dat (tools/extract.py) and KAIFONT.BIN read from the PS1 image.
Outputs: build/font/font.dat (full entry: 0x800 header + data, for patch_eboot) and
         build/tex_psp/FONT/bg/char/font.dat.pix (data only, put into FONT.BIN by pack_inplace)."""
import sys, os, io, pycdlib
sys.path.insert(0, 'tools'); import psp_font as F; from rawiso import open_ps1
ADD = {0x80: 0x10D, 0x81: 0x10E, 0x82: 0x10F, 0x83: 0x1A5}   # PS1 code/cell -> PSP cell
src = open('extracted/psp/FONT/bg/char/font.dat', 'rb').read()   # 0x800 header + 0x8000 data (tools/extract.py)
ps1 = open_ps1('originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin')
b = io.BytesIO(); ps1.get_file_from_iso_fp(b, iso_path='/CDDATA/DAT/KAIFONT.BIN;1'); kai = b.getvalue()
K = F.pages(kai[0x800:0x8800])                     # KAIFONT.BIN: entry header at 0, data at 0x800
A, B = F.pages(src)
# code -> (page, u, v) of its 12x12 cell: same lookup as psp_font.glyph (page A below 0x1BA, 21 cells per row)
def cell(code):
    pg, c = (A, code) if code < 0x1BA else (B, code - 0x1BA)
    return pg, (c % 21) * 12, (c // 21) * 12
# copy each glyph; stop if the PS1 glyph is blank or the PSP cell is not
for pc, qc in ADD.items():
    g = F.glyph(K, pc); assert F.ink(g), ('empty PS1 glyph', hex(pc))
    pg, u, v = cell(qc); assert not any(pg[v+y][u+x] for y in range(12) for x in range(12)), ('PSP cell not empty', hex(qc))
    for y in range(12):
        for x in range(12): pg[v+y][u+x] = g[y][x]
# re-encode (inverse of psp_font.pages: 128x32 blocks, 64 bytes per block row; page A bits 0-1/4-5, page B 2-3/6-7)
data = bytearray(0x8000); off = 0
for y in range(0, 256, 32):
    for x in range(0, 256, 128):
        for by in range(32):
            for bx in range(0, 128, 2):
                a0, a1, b0, b1 = A[y+by][x+bx], A[y+by][x+bx+1], B[y+by][x+bx], B[y+by][x+bx+1]
                data[off] = a0 | (b0 << 2) | (a1 << 4) | (b1 << 6); off += 1
assert F.pages(bytes(src[:0x800]) + bytes(data)) == (A, B), 'font re-encode mismatch'
# the re-encode must decode back to the same pages; count the changed bytes for the log (104 expected)
orig = src[0x800:0x8800]; changed = sum(1 for i in range(0x8000) if orig[i] != data[i])
os.makedirs('build/font', exist_ok=True); os.makedirs('build/tex_psp/FONT/bg/char', exist_ok=True)
open('build/font/font.dat', 'wb').write(src[:0x800] + bytes(data))
open('build/tex_psp/FONT/bg/char/font.dat.pix', 'wb').write(bytes(data))
print('font: added', {hex(k): hex(v) for k, v in ADD.items()}, f'({changed} bytes changed)')
