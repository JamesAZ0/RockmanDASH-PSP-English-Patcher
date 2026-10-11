"""PS1 title screen, textures part: the US PS1 logo, background and menu colours for the PSP title screen. Part of
`python build.py <tag> --localization=legends` (project decision, 2026-10-01); not run for text / audio, which keep
the PSP title. The program part is tools/patch_ps1_title.py. Inputs: DEMO_DAT.BIN from both discs (read-only).
Writes build/ps1_title/DEMO_DAT/BG/CHAR/, used by tools/pack_inplace.py --ps1-title=build/ps1_title (internal
argument, set by build.py):
  NTITLE.TIM.pix / .hdr    the PS1 logo (DEMO_DAT ..\\BG\\CHAR\\NTITLEU.TIM): the first 160 rows (= the first 0xA000
                           stored bytes, 5 rows of 64x32-byte blocks) and its 256-colour CLUT. Same VRAM place
                           (0x140,0x100), format and CLUT row (0x1F0) as the PSP logo (NTITLE.TIM, 256x160); both
                           games draw only rows 0-159 (the rows below are overwritten in VRAM by the menu words).
  NTITLE2.TIM.head         the menu-word texture's whole entry header with 9 palettes (CLUT count 8 -> 9, size
                           0x2120 -> 0x2140, as the PS1's NTITLE5U): palettes 0-7 carry the PS1 menu colours on the
                           indices build_title.py maps the PS1 word art to; palette 8 = the PSP's own palette 0, which
                           PRESS START / copyright now use (tools/patch_ps1_title.py). The pixels stay build_title.py's.
  NTITLE2.TIM.insert       the PS1 background entry NTITLE3U.TIM, verbatim (header + data, 16 sectors on disc; its
                           sector field says 17, like every TIM on both discs), inserted after NTITLE2 (as on the PS1
                           disc, where it follows the menu words). VRAM 0x240,0x100, CLUT row 0x1F2. The PSP disc has
                           no counterpart, so DEMO_DAT grows by 16 sectors.
Palette mapping (PS1 menu code 0x8001456C vs PSP 0x26BC, read from both programs): PSP palette p gets PS1 palette
  0 <- 1 (unselected option, mint), 1 <- 2 (selected, orange; the PS1 code picks clut x 0x20 for the selected option
  and 0x10 for the others - first read the other way round and corrected after an in-game test showed the colours
  reversed), 2 <- 4, 3 <- 3, 4 <- 6, 5 <- 5, 6 <- 8, 7 <- 7 (difficulty: PSP 2d+2 / 2d+3 unselected / selected,
  PS1 2d+4 / 2d+3).
Container entry header (one 0x800 sector, little-endian u32 fields, as used here): +0 type (1 = TIM), +4 size
(pixel bytes + CLUT bytes + 0x20), +8 sectors, +0x10 CLUT row, +0x14 colours per CLUT, +0x18 CLUT count,
+0x1C / +0x20 VRAM x / y, +0x24 width in 16-bit VRAM units, +0x28 height, +0x40 entry name, +0x100 CLUT data.
See docs/RESEARCH.md §2 (containers, TIM entries) and §8 (title screen).
Usage: python3 tools/build_ps1_title.py"""
import sys, os, io, json, struct, pycdlib
sys.path.insert(0, 'tools'); from rawiso import open_ps1; import inputs as IN
OUT = 'build/ps1_title/DEMO_DAT/BG/CHAR'; os.makedirs(OUT, exist_ok=True)
# PS1 colour index -> PSP colour index of the menu word art (the same table as tools/build_title.py MAP)
MAP = {1: 1, 2: 3, 3: 5, 4: 7, 5: 9, 6: 11, 7: 13, 8: 14, 9: 15}
# PAL_FROM[p] = the PS1 palette whose colours go into PSP palette p (see the palette mapping above)
PAL_FROM = (1, 2, 4, 3, 6, 5, 8, 7)
# get: one file of an ISO as bytes. entry: find a container entry by the name at header + 0x40 ->
# (offset, header sector, sector field)
def get(iso, p):
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=p); return b.getvalue()
def entry(d, name):
    for o in range(0, len(d) - 0x7FF, 0x800):
        if d[o+0x40:o+0x80].split(b'\0')[0] == name.encode():
            return o, bytes(d[o:o+0x800]), struct.unpack_from('<I', d, o + 8)[0]
    raise KeyError(name)
# Stored pixel order -> rows: the data is a sequence of blocks 64 bytes wide and 32 rows high, left to right,
# top to bottom (wb = row width in bytes)
def unswizzle(px, wb, h):
    out = bytearray(wb*h); o = 0
    for y in range(0, h, 32):
        for x in range(0, wb, 64):
            for by in range(32):
                for bx in range(64):
                    if y+by < h and o < len(px): out[(y+by)*wb + x+bx] = px[o]
                    o += 1
    return bytes(out)
psp = pycdlib.PyCdlib(); psp.open(IN.PSP)
A = get(psp, '/PSP_GAME/USRDIR/DAT/DEMO_DAT.BIN'); B = get(open_ps1(IN.PS1), '/CDDATA/DAT/DEMO_DAT.BIN;1')
# F: the first 11 header fields (+0 .. +0x28) as a tuple
F = lambda h: struct.unpack_from('<11I', h)
# --- logo
_, jh, _ = entry(A, '..\\BG\\CHAR\\NTITLE.TIM'); o1, uh, _ = entry(B, '..\\BG\\CHAR\\NTITLEU.TIM')
j, u = F(jh), F(uh)
# both logos: TIM entries with the same CLUT / VRAM fields and width 0x80 (256 px); height PSP 0xA0, PS1 0x100
assert j[0] == u[0] == 1 and j[3:10] == u[3:10] and (j[9], j[10], u[10]) == (0x80, 0xA0, 0x100), ('logo format', j, u)
assert not any(jh[0x300:0x800]) and not any(uh[0x300:0x800]), 'CLUT area beyond 256 colours not empty'
NPX = 0x80 * 2 * 0xA0                                             # 256 x 160 bytes
upx = B[o1 + 0x800: o1 + 0x800 + 0x80 * 2 * 0x100]
# rows 0-159 must be exactly the first 5 block rows, so the stored prefix can replace the PSP pixels as it is
assert unswizzle(upx[:NPX], 0x100, 0xA0) == unswizzle(upx, 0x100, 0x100)[:NPX], 'first 160 rows are not a block prefix'
# .pix = the stored pixel bytes; .hdr = header bytes 0x100-0x7FF (the CLUT area)
open(f'{OUT}/NTITLE.TIM.pix', 'wb').write(upx[:NPX]); open(f'{OUT}/NTITLE.TIM.hdr', 'wb').write(uh[0x100:0x800])
# --- menu-word palettes
_, nh, _ = entry(A, '..\\BG\\CHAR\\NTITLE2.TIM'); _, wh, _ = entry(B, '..\\BG\\CHAR\\NTITLE5U.TIM')
n, w = F(nh), F(wh)
# PSP menu words: size 0x2120, 16 colours x 8 CLUTs; PS1 NTITLE5U: 16 x 9; same CLUT position fields
assert (n[1], n[5], n[6], w[5], w[6]) == (0x2120, 16, 8, 16, 9) and n[3:5] == w[3:5], ('menu texture format', n, w)
assert not any(nh[0x200:0x800]), 'PSP header after the 8 palettes not empty'
# P2 = the PSP palettes (8), P5 = the PS1 palettes (9), 16 colours of 16 bits each
P2 = [list(struct.unpack_from('<16H', nh, 0x100 + 32*k)) for k in range(8)]
P5 = [list(struct.unpack_from('<16H', wh, 0x100 + 32*k)) for k in range(9)]
pals = []
# new palette p = the PSP palette with the PS1 colours written on the indices the word art uses (MAP)
for p, q in enumerate(PAL_FROM):
    c = list(P2[p])
    for k, i in MAP.items(): c[i] = P5[q][k]
    pals.append(c)
pals.append(P2[0])                                                # palette 8: PRESS START / copyright (PSP colours)
# header + 4: size = 0x2000 pixel bytes + 9 palettes x 32 bytes + 0x20 (= 0x2140); + 0x18: CLUT count 9
head = bytearray(nh); struct.pack_into('<I', head, 4, 0x2000 + 9 * 32 + 0x20); struct.pack_into('<I', head, 0x18, 9)
for k, c in enumerate(pals): struct.pack_into('<16H', head, 0x100 + 32*k, *c)
# the entry keeps its sectors: the sector field must still cover header + pixels
assert struct.unpack_from('<I', head, 8)[0] * 0x800 >= 0x800 + 0x2000
open(f'{OUT}/NTITLE2.TIM.head', 'wb').write(head)
# --- background entry, verbatim
o3, bh, secs = entry(B, '..\\BG\\CHAR\\NTITLE3U.TIM'); b3 = F(bh)
# NTITLE3U as expected: TIM, size 0x7A20, sector field 17; CLUT row 0x1F2, 256 colours x 1, VRAM 0x240,0x100,
# width 0x60 units (192 px), height 0xA0
assert b3[:3] == (1, 0x7A20, 17) and b3[4:11] == (0x1F2, 0x100, 1, 0x240, 0x100, 0x60, 0xA0), b3
# on-disc extent = header + pixel sectors (up to the next entry header); the sector field is one more (as for every TIM)
end = next(o for o in range(o3 + 0x800, len(B), 0x800) if B[o+0x40:o+0x43] == b'..\\')
assert end - o3 == (secs - 1) * 0x800 and (end - o3 - 0x800) >= 0x60 * 2 * 0xA0, (hex(end - o3), secs)
ins = B[o3:end]
open(f'{OUT}/NTITLE2.TIM.insert', 'wb').write(ins)
rep = dict(logo=dict(source='PS1 DEMO_DAT NTITLEU.TIM rows 0-159', bytes=NPX), palettes=dict(psp_from_ps1=list(PAL_FROM), palette8='PSP palette 0 (PRESS START / copyright)'),
           inserted=dict(entry='..\\BG\\CHAR\\NTITLE3U.TIM', after='..\\BG\\CHAR\\NTITLE2.TIM', sectors=len(ins) // 0x800))
json.dump(rep, open('build/ps1_title/report.json', 'w'), indent=1)
print(f'PS1 title textures: logo {NPX} bytes + CLUT, 9 menu palettes, background entry {len(ins) // 0x800} sectors -> build/ps1_title/')
