"""Research tool (not run by the build; read-only): render the TIM textures of a data file from both discs to PNG, for
looking at them.

Usage: python3 research/tim_dump.py DEMO_DAT SUB_KEY ...     (needs pycdlib + Pillow)
Reads:  DAT/<name>.BIN from the PS1 disc image and the PSP ISO.
Writes: build/analysis/tim/<ps1|psp>_<BIN>_<texture>_pal<k>.png

Texture entries in the game's containers are not plain .TIM files (docs/RESEARCH.md §2, layout from DashEditor's
Formats/TIM.py): an entry of type 1 has a 0x800-byte header and then the pixel data.
  header +0x14 colours per palette (16 or 256)     +0x18 number of palettes
         +0x24 width in 16-bit VRAM words          +0x28 height
         +0x100 the palettes, 15-bit colours (value 0 = transparent)
  pixels are stored in blocks of 64 bytes x 32 rows, block after block, left to right then top to bottom (the same
  on PS1 and PSP); 4-bit textures hold two pixels per byte, low nibble first.
One image is written per palette (at most 8) because the game picks the palette when it draws: a texture often
holds several things that only look right under their own palette."""
import sys, os, io, struct, pycdlib
from PIL import Image
sys.path.insert(0, 'tools'); from rawiso import open_ps1
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'tools')); import inputs as _IN
PSP = _IN.PSP                    # PSP base image: tools/inputs.py (PSP_ISO=psn|umd|path)
OUT = 'build/analysis/tim'; os.makedirs(OUT, exist_ok=True)
# c15: 15-bit colour (5 bits each of red, green, blue from the low end) -> RGBA; colour value 0 is transparent
def c15(v):
    r, g, b = v & 31, (v >> 5) & 31, (v >> 10) & 31
    return (r*255//31, g*255//31, b*255//31, 0 if v == 0 else 255)
# unswizzle: stored 64x32-byte blocks -> plain rows of wbytes bytes
def unswizzle(px, wbytes, h):
    out = bytearray(len(px)); o = 0
    for y in range(0, h, 32):
        for x in range(0, wbytes, 64):
            for by in range(32):
                for bx in range(64):
                    if y+by < h and x+bx < wbytes and o < len(px): out[(y+by)*wbytes + x+bx] = px[o]
                    o += 1
    return bytes(out)
def render(hdr, px, stem):
    """hdr = the 0x800-byte container header (CLUTs at +0x100), px = pixel data (stored in 64x32-byte blocks,
    same on PS1 and PSP; layout from DashEditor Formats/TIM.py)."""
    colors, ncl = struct.unpack_from('<I', hdr, 0x14)[0], struct.unpack_from('<I', hdr, 0x18)[0]
    w16, h = struct.unpack_from('<I', hdr, 0x24)[0], struct.unpack_from('<I', hdr, 0x28)[0]
    if colors not in (16, 256) or not w16 or not h: return []
    cl = struct.unpack_from(f'<{colors*ncl}H', hdr, 0x100) if 0x100 + colors*ncl*2 <= 0x800 else ()
    cluts = [cl[r*colors:(r+1)*colors] for r in range(ncl)] if cl else [None]
    # row length in bytes = 2 per VRAM word; pixels per row = 4 per word at 4 bits, 2 at 8 bits. Without palettes in
    # the header the indices are drawn as greys
    wbytes = w16*2; px = unswizzle(px, wbytes, h); W = w16*4 if colors == 16 else w16*2; res = []
    for k, c in enumerate(cluts[:8]):
        data = []
        for y in range(h):
            row = px[y*wbytes:(y+1)*wbytes]
            idx = [v for b in row for v in ((b & 15, b >> 4) if colors == 16 else (b,))]
            data += [c15(c[i]) if c else ((i*17) % 256,)*3 + (255,) for i in idx[:W]]
        im = Image.new('RGBA', (W, h)); im.putdata(data); q = f'{OUT}/{stem}_pal{k}.png'; im.save(q); res.append(q)
    return res
# entries: every container entry of a BIN as (type, name, header, data); the size is at header +4
def entries(d):
    for off in range(0, len(d) - 0x7FF, 0x800):
        name = d[off+0x40:off+0x80].split(b'\0')[0]
        if name.startswith(b'..\\') and all(32 <= x < 127 for x in name):
            typ, size = struct.unpack_from('<II', d, off)
            yield typ, name.decode(), d[off:off+0x800], d[off+0x800: off+0x800+size]
ps1 = open_ps1(PS1); psp = pycdlib.PyCdlib(); psp.open(PSP)
for stem in sys.argv[1:]:
    for side, iso, path in (('ps1', ps1, f'/CDDATA/DAT/{stem}.BIN;1'), ('psp', psp, f'/PSP_GAME/USRDIR/DAT/{stem}.BIN')):
        b = io.BytesIO()
        try: iso.get_file_from_iso_fp(b, iso_path=path)
        except Exception as e: print(side, stem, 'missing', e); continue
        for typ, name, hdr, data in entries(b.getvalue()):
            if name.upper().endswith('.TIM') and typ == 1:
                n = name.split('\\')[-1][:-4]
                print(side, stem, name, len(render(hdr, data, f'{side}_{stem}_{n}')), 'palettes')
