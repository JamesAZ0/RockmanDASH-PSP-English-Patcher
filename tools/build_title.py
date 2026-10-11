"""Build the English title-menu texture for the PSP (project decision 2026-09-29). Reference: docs/RESEARCH.md §8, §2.
The title menu's words are not text but a texture, and the two games lay it out differently.
Takes the English word art from the PS1 title texture (DEMO_DAT.BIN ..\\BG\\CHAR\\NTITLE5U.TIM) and places it in the
PSP texture (DEMO_DAT.BIN ..\\BG\\CHAR\\NTITLE2.TIM, 256x64 4bpp, 8 CLUTs, unchanged):
  rows 0-31  : PSP original (PRESS START BUTTON, (c) CAPCOM 1997, 2005) - untouched
  row  32-44 : NEW GAME | CONTINUE | OPTION  - PS1 letters re-spaced to 1 px gaps (3 px word space), in u cells
               0-86 / 86-172 / 169-255 used by the patched title code (tools/patch_eboot.py, TITLE)
  row  48-60 : HARD | NORMAL | EASY - PS1 words unchanged, centred in the PSP's 80 px difficulty cells
               (difficulty 2 = u 0-80, 1 = u 80-160, 0 = u 160-240; code 0x2AEC)
Why re-spaced: the PSP draws the three options with one shared width from side-by-side cells of one 256-px row
(function 0x26BC, static analysis). The PS1's NEW GAME and CONTINUE are 102 px wide; with the letters unchanged and
1-px gaps the three words
are 86 / 83 / 66 px, and 86 is the widest cell that fits three across.
Colours: the PS1 word art uses indices 1-7 (dark->bright) + 8/9 (shadow); remapped onto the PSP scheme
1-13 (dark->bright) + 14/15 (outline) so the PSP's own palettes (0 = blue, 1 = yellow when selected) apply.
Container TIM entry (same on both games; layout from DashEditor): 0x800-byte header with the width in 16-bit units
at +0x24, the height at +0x28 and the CLUTs (16 colours each) from +0x100; then the pixels, stored in blocks of
64x32 bytes. The entry's size field also counts the CLUT bytes, which is why only width*height bytes are pixels.
Inputs: both disc images (read-only). The logo and the background are not touched here (the PS1 title screen of
--localization=legends is a separate step, tools/build_ps1_title.py).
Output: build/tex_psp/DEMO_DAT/BG/CHAR/NTITLE2.TIM.pix  (pixel data exactly as stored after the 0x800 header,
        same size as the original) + build/analysis/tim/ntitle2_english_preview.png"""
import sys, os, io, struct, pycdlib
sys.path.insert(0, 'tools'); from rawiso import open_ps1
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
# import tools/inputs.py from this file's own folder, wherever the tool is run from
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '')); import inputs as _IN
PSP = _IN.PSP                    # PSP base image: tools/inputs.py (the path build.py passes in PSP_ISO, or the default)
OUT = 'build/tex_psp/DEMO_DAT/BG/CHAR/NTITLE2.TIM.pix'
# PS1 colour index -> PSP colour index (see "Colours" above); 0 = transparent
MAP = {0: 0, 1: 1, 2: 3, 3: 5, 4: 7, 5: 9, 6: 11, 7: 13, 8: 14, 9: 15}

# Find an entry in a container file by its name field (header +0x40) -> (0x800-byte header, data). Entries start on
# 0x800 boundaries; +4 of the header is the data size.
def entry(iso, path, name):
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=path); d = b.getvalue()
    for off in range(0, len(d) - 0x7FF, 0x800):
        if d[off+0x40:off+0x80].split(b'\0')[0] == name:
            h = d[off:off+0x800]; size = struct.unpack_from('<I', h, 4)[0]
            return h, d[off+0x800: off+0x800+size]
    raise KeyError(name)
def blocks(wbytes, h):                      # 64x32-byte block order (DashEditor Formats/TIM.py)
    for y in range(0, h, 32):
        for x in range(0, wbytes, 64):
            for by in range(32):
                for bx in range(64): yield (y+by)*wbytes + x+bx
# to_idx: stored pixel bytes -> rows of 4-bit colour indices (low nibble = left pixel); also returns the width in
# bytes and the height. from_idx is the inverse; the round trip is asserted against the original below.
def to_idx(h, px):
    w16, H = struct.unpack_from('<I', h, 0x24)[0], struct.unpack_from('<I', h, 0x28)[0]; wb = w16*2
    lin = bytearray(wb*H)
    for o, p in zip(range(len(px)), blocks(wb, H)):
        if p < len(lin): lin[p] = px[o]
    return [[(lin[y*wb + x//2] >> (4*(x & 1))) & 15 for x in range(wb*2)] for y in range(H)], wb, H
def from_idx(I, wb, H, size, tail=b''):
    """Pixels occupy the first wb*H bytes; any bytes after that (the entry size counts the CLUT too) are kept."""
    lin = bytearray(wb*H)
    for y in range(H):
        for x in range(0, wb*2, 2): lin[y*wb + x//2] = I[y][x] | (I[y][x+1] << 4)
    out = bytearray(size)
    for o, p in zip(range(wb*H), blocks(wb, H)): out[o] = lin[p]
    out[wb*H:] = tail[wb*H:size] if tail else out[wb*H:]
    return bytes(out)
# word: cut a 13-row word out of the PS1 texture (columns x0..x1 from row y0), colours remapped.
# letters: split it into letters at the blank columns. pack: put letters back side by side with 'gap' blank columns,
# or 'space' columns after letter number space_after. put: paint non-transparent pixels into the PSP image.
def word(S, x0, x1, y0): return [[MAP[S[y0+y][x]] for x in range(x0, x1+1)] for y in range(13)]
def letters(w):
    cols = [x for x in range(len(w[0])) if any(r[x] for r in w)]; segs = []; s = p = cols[0]
    for x in cols[1:]:
        if x != p + 1: segs.append((s, p)); s = x
        p = x
    segs.append((s, p)); return [[r[a:b+1] for r in w] for a, b in segs]
def pack(parts, gap=1, space_after=None, space=3):
    rows = [[] for _ in range(13)]
    for i, L in enumerate(parts):
        for y in range(13): rows[y] += L[y]
        if i < len(parts) - 1:
            for y in range(13): rows[y] += [0] * (space if i == space_after else gap)
    return rows
def put(I, w, x, y):
    for yy, r in enumerate(w):
        for xx, v in enumerate(r):
            if v: I[y+yy][x+xx] = v

psp = pycdlib.PyCdlib(); psp.open(PSP); ps1 = open_ps1(PS1)
ph, ppx = entry(psp, '/PSP_GAME/USRDIR/DAT/DEMO_DAT.BIN', b'..\\BG\\CHAR\\NTITLE2.TIM')
sh, spx = entry(ps1, '/CDDATA/DAT/DEMO_DAT.BIN;1', b'..\\BG\\CHAR\\NTITLE5U.TIM')
P, wb, H = to_idx(ph, ppx); S, _, _ = to_idx(sh, spx)
assert from_idx(P, wb, H, len(ppx), ppx) == ppx, 'swizzle round-trip failed'
# PS1 NTITLE5U word positions (x0, x1, y0), measured with research/tim_dump.py
NEW_GAME = pack(letters(word(S, 3, 104, 42)), space_after=2)       # N E W | G A M E -> 86 px
CONTINUE = pack(letters(word(S, 115, 216, 42)))                    # 83 px
OPTION   = pack(letters(word(S, 3, 75, 58)))                       # 66 px
EASY, NORMAL, HARD = word(S, 84, 131, 58), word(S, 139, 210, 58), word(S, 3, 50, 74)
widths = {n: len(w[0]) for n, w in (('NEW GAME', NEW_GAME), ('CONTINUE', CONTINUE), ('OPTION', OPTION),
                                     ('EASY', EASY), ('NORMAL', NORMAL), ('HARD', HARD))}
assert widths['NEW GAME'] <= 86 and widths['CONTINUE'] <= 83 and widths['OPTION'] <= 86, widths
# clear the lower half (the Japanese words), then place the option row at y 32 and the difficulty row at y 48
for y in range(32, 64): P[y] = [0] * (wb*2)
put(P, NEW_GAME, 0, 32)                                            # cell [0,86)
put(P, CONTINUE, 86, 32)                                           # cell [86,172); art 86..168 (cell 3 starts 169)
put(P, OPTION, 169 + (86 - widths['OPTION']) // 2, 32)             # cell [169,255)
for w, c in ((HARD, 0), (NORMAL, 80), (EASY, 160)): put(P, w, c + (80 - len(w[0])) // 2, 48)
# cell isolation check: each option cell holds only its own word
occ = lambda a, b: [x for x in range(a, b) if any(P[y][x] for y in range(32, 45))]
assert occ(0, 86)[-1] < 86 and not [x for x in occ(86, 172) if x >= 169 and x < 172 and x < 169 + (86 - widths['OPTION']) // 2]
new = from_idx(P, wb, H, len(ppx), ppx); assert len(new) == len(ppx)
os.makedirs(os.path.dirname(OUT), exist_ok=True); open(OUT, 'wb').write(new[:wb*H])   # pixel bytes only (see build_textures.py)
# optional preview (needs Pillow): the texture with palette 0 and palette 1, enlarged 3x. c15: 15-bit BGR -> RGBA
try:
    from PIL import Image
    def c15(v): return ((v & 31)*255//31, ((v >> 5) & 31)*255//31, ((v >> 10) & 31)*255//31, 0 if v == 0 else 255)
    ims = []
    for k in (0, 1):
        pal = struct.unpack_from('<16H', ph, 0x100 + 32*k); im = Image.new('RGBA', (wb*2, H))
        im.putdata([c15(pal[v]) for r in P for v in r]); ims.append(im.resize((wb*6, H*3), Image.NEAREST))
    sheet = Image.new('RGBA', (wb*6, H*6 + 8), (40, 40, 70, 255)); sheet.alpha_composite(ims[0], (0, 0)); sheet.alpha_composite(ims[1], (0, H*3 + 8))
    os.makedirs('build/analysis/tim', exist_ok=True); sheet.save('build/analysis/tim/ntitle2_english_preview.png')
except ImportError: pass
print('title texture:', OUT, len(new), 'bytes; word widths', widths)
