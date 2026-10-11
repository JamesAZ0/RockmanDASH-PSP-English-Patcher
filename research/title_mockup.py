"""Research / review tool (not run by the build; read-only): mock-up pictures made on 2026-10-01 to decide two options
before any of it was built. Both were then built for real and are part of --localization=legends
(tools/build_ps1_title.py, tools/patch_ps1_title.py, tools/build_savepic.py; docs/RESEARCH.md §8, §14). Nothing here
is used by the build.
  1. PS1 title screen on the PSP: the PS1 logo (NTITLEU.TIM, top 160 rows), the PS1 background (NTITLE3U.TIM drawn as
     the PS1 does it: two 160x160 quads, the right one mirrored; a subtractive fade over y 0x90-0xA0; a gradient from
     black to (C0,FF,E0) over y 0xA2-0xF0; PS1 code at ROCK_NEO.EXE 0x80013FB8) and the PS1 menu colours (PS1 title
     menu, code 0x8001456C: selected option = palette 2, unselected = 1; difficulty d selected = palette 2d+3,
     unselected = 2d+4). The PSP's menu layout (positions, dark box) is kept.
  2. Save image: savepic.png (144x80) remade from the PS1 logo over the PS1 title background, in two logo sizes
     (132 and 116 pixels wide; the build uses 132).
Everything is drawn in the game's 320x240 space from the disc data, then scaled to the PSP's 480x272 the way the Wide
screen setting stretches it.

Reads:  DEMO_DAT.BIN from both disc images (tools/inputs.py), and build/tex_psp/DEMO_DAT/BG/CHAR/NTITLE2.TIM.pix if a
        build has made it (the English title-menu words from tools/build_title.py; else the Japanese words are shown).
Writes: build/analysis/ps1_title/: title_now_menu.png (the PSP title as it is), title_ps1opt_press.png,
        title_ps1opt_menu.png, title_ps1opt_menu_aspect.png (logo at its PS1 proportions), menu_palettes_now_vs_ps1.png
        (the menu words under every palette, before and after), savepic_a_logo132.png, savepic_b_logo116.png and
        savepic_options.png (both next to the original).

Usage: python3 research/title_mockup.py      (needs pycdlib + Pillow)"""
import sys, os, io, struct, pycdlib
from PIL import Image, ImageDraw
sys.path.insert(0, 'tools'); from rawiso import open_ps1; import inputs as IN
OUT = 'build/analysis/ps1_title'; os.makedirs(OUT, exist_ok=True)
def get(iso, p):
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=p); return b.getvalue()
psp = pycdlib.PyCdlib(); psp.open(IN.PSP)
# A = PSP DEMO_DAT.BIN (title data), B = the PS1 (USA) one
A = get(psp, '/PSP_GAME/USRDIR/DAT/DEMO_DAT.BIN'); B = get(open_ps1(IN.PS1), '/CDDATA/DAT/DEMO_DAT.BIN;1')
# tim: (0x800-byte header, pixel data) of the container entry with this path; the data size is at header +4
def tim(d, name):
    for o in range(0, len(d) - 0x7FF, 0x800):
        if d[o+0x40:o+0x80].split(b'\0')[0] == name.encode():
            h = d[o:o+0x800]; size = struct.unpack_from('<I', h, 4)[0]; return h, d[o+0x800:o+0x800+size]
    raise KeyError(name)
# unswizzle: pixel data is stored in blocks of 64 bytes x 32 rows; turn it into plain rows of wb bytes
def unswizzle(px, wb, h):
    out = bytearray(wb*h); o = 0
    for y in range(0, h, 32):
        for x in range(0, wb, 64):
            for by in range(32):
                for bx in range(64):
                    if y+by < h and o < len(px): out[(y+by)*wb + x+bx] = px[o]
                    o += 1
    return out
# c15: 15-bit colour -> RGB, colour value 0 = transparent (None)
def c15(v): return None if v == 0 else ((v & 31)*255//31, ((v >> 5) & 31)*255//31, ((v >> 10) & 31)*255//31)
# indices: the texture as rows of palette indices. Header +0x14 colours per palette, +0x24 width in 16-bit VRAM words,
# +0x28 height; 8-bit: one pixel per byte, 4-bit: two per byte, low nibble first
def indices(h, px):
    colors, w16, H = struct.unpack_from('<I', h, 0x14)[0], struct.unpack_from('<I', h, 0x24)[0], struct.unpack_from('<I', h, 0x28)[0]
    lin = unswizzle(px, w16*2, H)
    if colors == 256: return [[lin[y*w16*2 + x] for x in range(w16*2)] for y in range(H)]
    return [[(lin[y*w16*2 + x//2] >> (4*(x & 1))) & 15 for x in range(w16*4)] for y in range(H)]
# pals: the palettes in the header (count at +0x18, colours from +0x100)
def pals(h):
    colors, n = struct.unpack_from('<I', h, 0x14)[0], struct.unpack_from('<I', h, 0x18)[0]
    cl = struct.unpack_from(f'<{colors*n}H', h, 0x100); return [cl[k*colors:(k+1)*colors] for k in range(n)]
# image: indices + one palette -> RGBA picture, optionally only rows[0]..rows[1]
def image(I, pal, rows=None):
    rows = rows or (0, len(I)); im = Image.new('RGBA', (len(I[0]), rows[1]-rows[0]), (0, 0, 0, 0))
    im.putdata([(c + (255,)) if c else (0, 0, 0, 0) for r in I[rows[0]:rows[1]] for c in (c15(pal[v]) for v in r)]); return im

logo_h, logo_p = tim(B, '..\\BG\\CHAR\\NTITLEU.TIM'); LOGO = indices(logo_h, logo_p); LPAL = pals(logo_h)[0]
bg_h, bg_p = tim(B, '..\\BG\\CHAR\\NTITLE3U.TIM'); BG = indices(bg_h, bg_p); BPAL = pals(bg_h)[0]
w5_h, _ = tim(B, '..\\BG\\CHAR\\NTITLE5U.TIM'); P5 = pals(w5_h)              # PS1 menu palettes (9)
jp_h, jp_p = tim(A, '..\\BG\\CHAR\\NTITLE.TIM'); JLOGO = indices(jp_h, jp_p); JPAL = pals(jp_h)[0]
n2_h, n2_p = tim(A, '..\\BG\\CHAR\\NTITLE2.TIM'); P2 = pals(n2_h)              # PSP menu palettes (8)
built = 'build/tex_psp/DEMO_DAT/BG/CHAR/NTITLE2.TIM.pix'                         # current English menu words
W2 = indices(n2_h, open(built, 'rb').read() if os.path.exists(built) else n2_p)
# the PS1 word art (NTITLE5U) uses palette indices 0-9; build_title.py redraws it in the PSP texture on these indices
MAP = {0: 0, 1: 1, 2: 3, 3: 5, 4: 7, 5: 9, 6: 11, 7: 13, 8: 14, 9: 15}        # PS1 word index -> PSP index (build_title.py)
def psp_pal(ps1pal, base):
    """A 16-colour PSP palette carrying a PS1 word palette on the indices build_title.py maps the PS1 indices to;
    the other entries (used only by PRESS START / copyright art) keep the base palette."""
    out = list(base)
    for k, i in MAP.items():
        if k: out[i] = ps1pal[k]
    return out
# PSP palette p <- PS1 palette: 0 unselected option <- 1, 1 selected <- 2, difficulty 2d+2 unselected <- 2d+4,
# 2d+3 selected <- 2d+3; PRESS START / copyright move to a new palette 8 = the PSP's own palette 0
NEWPAL = [psp_pal(P5[q], P2[p]) for p, q in enumerate((1, 2, 4, 3, 6, 5, 8, 7))] + [P2[0]]

# quad: draw src stretched into the screen rectangle box = (x0, y0, x1, y1), optionally mirrored left-right
def quad(canvas, src, box, flip=False):
    im = src.resize((box[2]-box[0], box[3]-box[1]), Image.NEAREST)
    if flip: im = im.transpose(Image.FLIP_LEFT_RIGHT)
    canvas.alpha_composite(im, (box[0], box[1]))
def ps1_background(c):
    t = image(BG, BPAL).crop((0, 0, 160, 160))
    quad(c, t, (0, 0, 160, 160)); quad(c, t, (160, 0, 320, 160), flip=True)
    px = c.load()
    for y in range(0x90, 0xA0):                       # subtractive G4: 0 at y 0x90 -> 0xFF at y 0xA0
        s = round(255 * (y - 0x90) / 16)
        for x in range(320): r, g, b, a = px[x, y]; px[x, y] = (max(0, r-s), max(0, g-s), max(0, b-s), 255)
    for y in range(0xA2, 0xF0):                       # G4: black -> (C0,FF,E0)
        f = (y - 0xA2) / (0xF0 - 0xA2); col = (round(0xC0*f), round(0xFF*f), round(0xE0*f), 255)
        ImageDraw.Draw(c).line([(0, y), (319, y)], fill=col)
# the PSP title background: white to y 0xA1, a gradient to (10,80,E0) over y 0xA2-0xB3, then that blue to y 0xEF
def psp_background(c):
    d = ImageDraw.Draw(c); d.rectangle((0, 0, 319, 0xA1), fill=(255, 255, 255, 255))
    d.rectangle((0, 0xB4, 319, 0xEF), fill=(0x10, 0x80, 0xE0, 255))
    for y in range(0xA2, 0xB4):
        f = (y - 0xA2) / 18; d.line([(0, y), (319, y)], fill=tuple(round(255 + (t - 255)*f) for t in (0x10, 0x80, 0xE0)) + (255,))
# logo: rows 0-159 of the logo texture into x 0x20-0x120, y 8-0xA8, or into the narrower x 0x40-0x101 for the
# proportions variant
def logo(c, I, pal, wide):
    quad(c, image(I, pal, (0, 160)), (0x20, 8, 0x120, 0xA8) if wide else (0x40, 8, 0x101, 0xA8))
# words: the 2D text. 'press' = the PRESS START line (texture rows 0-15) and the copyright line (rows 16-31);
# otherwise the half-transparent dark box and the three menu options (texture rows 32-47, three cells of 86 pixels,
# drawn at x 0x75-0xCB, 16 pixels apart from y 0xA4 - the option positions of the patched PSP title-menu code). The
# other screen rectangles here were read off the PSP title code when the mock-up was made; their derivation is not
# recorded
def words(c, pal_of, state):
    def cell(u0, u1, v0, v1, pal): return image([r[u0:u1] for r in W2[v0:v1]], pal)
    if state == 'press':
        quad(c, cell(0, 0xD0, 0, 16, pal_of('press')), (0x38, 0xB0, 0x108, 0xC0))
        quad(c, cell(0, 0x100, 16, 32, pal_of('press')), (0x20, 0xD0, 0x120, 0xE0)); return
    box = Image.new('RGBA', (0xD0-0x70, 0xD5-0xA0), (0, 0, 0, 128)); c.alpha_composite(box, (0x70, 0xA0))
    for k, (u0, u1) in enumerate(((0, 0x56), (0x56, 0xAC), (0xA9, 0xFF))):
        quad(c, cell(u0, u1, 32, 48, pal_of('sel' if k == 0 else 'unsel')), (0x75, 0xA4 + 16*k, 0xCB, 0xB4 + 16*k))
def screen(bg, logo_args, pal_of, state, wide=True):
    c = Image.new('RGBA', (320, 240), (0, 0, 0, 255)); bg(c); logo(c, *logo_args, wide); words(c, pal_of, state)
    return c.resize((480, 272), Image.BILINEAR)
# cur / new: which palette a piece of text gets now (PSP: selected = palette 1, the rest palette 0) and with the PS1
# option (selected / unselected from NEWPAL 1 / 0, PRESS START and copyright from the new palette 8)
cur = lambda w: P2[1] if w == 'sel' else P2[0]
new = lambda w: NEWPAL[8] if w == 'press' else NEWPAL[1] if w == 'sel' else NEWPAL[0]
shots = {'now_menu': screen(psp_background, (JLOGO, JPAL), cur, 'menu'),
         'ps1opt_press': screen(ps1_background, (LOGO, LPAL), new, 'press'),
         'ps1opt_menu': screen(ps1_background, (LOGO, LPAL), new, 'menu'),
         'ps1opt_menu_aspect': screen(ps1_background, (LOGO, LPAL), new, 'menu', wide=False)}
for k, im in shots.items(): im.convert('RGB').save(f'{OUT}/title_{k}.png')
# palette strip: current vs PS1-option words, every palette
strip = Image.new('RGBA', (2*256 + 8, 9*20), (30, 30, 40, 255))
for p in range(9):
    for side, pl in ((0, P2[p] if p < 8 else None), (1, NEWPAL[p])):
        if pl: strip.alpha_composite(image([r[:256] for r in W2[32:48]] if p < 8 else [r[:256] for r in W2[0:16]], pl), (side*264, p*20))
strip.resize((strip.width*2, strip.height*2), Image.NEAREST).convert('RGB').save(f'{OUT}/menu_palettes_now_vs_ps1.png')

# --- save image (savepic.png, 144x80)
L = image(LOGO, LPAL, (0, 160)); L = L.crop(L.getbbox())
def savepic(logo_w):
    bg = Image.new('RGBA', (320, 240), (0, 0, 0, 255)); ps1_background(bg)
    # top 320x160 of the screen (the part the background texture covers) halved to 160x80, middle 144 columns kept
    bg = bg.crop((0, 0, 320, 160)).resize((160, 80), Image.LANCZOS).crop((8, 0, 152, 80))
    lw = logo_w; lh = round(L.height * lw / L.width); lg = L.resize((lw, lh), Image.LANCZOS)
    bg.alpha_composite(lg, ((144 - lw)//2, (80 - lh)//2)); return bg.convert('RGB')
orig = Image.open(io.BytesIO(get(psp, '/PSP_GAME/USRDIR/DAT/PICT/savepic.png'))).convert('RGB')
cands = {'a_logo132': savepic(132), 'b_logo116': savepic(116)}
sheet = Image.new('RGB', (3*(144*3 + 12), 80*3 + 24), (40, 40, 40)); d = ImageDraw.Draw(sheet)
for i, (k, im) in enumerate([('now (PSP)', orig)] + list(cands.items())):
    sheet.paste(im.resize((432, 240), Image.NEAREST), (i*444, 22)); d.text((i*444 + 4, 4), k, fill=(255, 255, 0))
    if k != 'now (PSP)': im.save(f'{OUT}/savepic_{k}.png', optimize=True)
sheet.save(f'{OUT}/savepic_options.png')
for k in cands: print(k, os.path.getsize(f'{OUT}/savepic_{k}.png'), 'bytes (original', len(get(psp, '/PSP_GAME/USRDIR/DAT/PICT/savepic.png')), '; game buffer 30000)')
print('wrote', sorted(os.listdir(OUT)))
