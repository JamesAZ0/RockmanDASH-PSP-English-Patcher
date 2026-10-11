"""PS1 save image and PSP menu icon. Part of `python build.py <tag> --localization=legends` (project decision,
2026-10-01: logo 132 px wide); text / audio keep the PSP's picture. Input: the PS1 disc's DEMO_DAT.BIN (read-only).
Writes build/pict/savepic.png, the 144x80 picture the game hands the PSP savedata utility (DAT/PICT/savepic.png;
EBOOT 0x4F698/0x4F8B0: loaded into a 30,000-byte buffer), used by tools/pack_inplace.py --pict=build/pict/savepic.png
(and --icon0=, the menu icon ICON0.PNG, which on the original disc is the same picture as savepic.png; both are
internal arguments, set by build.py). No image generation: the picture is only the PS1 disc's own
textures, decoded with their palettes, laid out and scaled:
  background = the PS1 title background as the PS1 draws it (DEMO_DAT NTITLE3U texels 0-160, then the same mirrored,
               the subtractive fade over the bottom 16 rows; ROCK_NEO.EXE 0x800140BC): 320x160, scaled to 160x80
               (Lanczos), the middle 144 columns kept;
  logo       = the PS1 logo (NTITLEU), cropped to its drawn pixels and scaled to 132 px wide (Lanczos), centred.
Same format as the PSP's file (8-bit RGB PNG, no alpha). The PNG bytes depend on the Pillow version (recorded in
build/pict/report.json); the file must fit the original's sectors (<= 26,624 bytes = 13 sectors; the original is
26,087 bytes) and the game's buffer (30,000). The game writes this picture into each save; the companion program fix
is tools/patch_psp_menu.py. See docs/RESEARCH.md §14 (PSP menu and save data) and §2 (TIM entries).
Also writes build/pict/savepic_preview.png (3x). Usage: python3 tools/build_savepic.py   (needs Pillow)"""
import sys, os, io, json, struct, hashlib
import PIL; from PIL import Image
sys.path.insert(0, 'tools'); from rawiso import open_ps1; import inputs as IN
OUT = 'build/pict'; os.makedirs(OUT, exist_ok=True); LOGO_W = 132
b = io.BytesIO(); open_ps1(IN.PS1).get_file_from_iso_fp(b, iso_path='/CDDATA/DAT/DEMO_DAT.BIN;1'); B = b.getvalue()
# tim(name) -> the named 8-bit TIM entry of the PS1 DEMO_DAT as an RGBA image. Entry header: name at +0x40,
# colours per CLUT at +0x14 (256), width in 16-bit VRAM units at +0x24, height at +0x28, CLUT at +0x100;
# pixels follow the 0x800 header in blocks 64 bytes wide and 32 rows high. Colours are 15-bit
# (5 bits each, red lowest); value 0 = transparent
def tim(name):
    for o in range(0, len(B) - 0x7FF, 0x800):
        if B[o+0x40:o+0x80].split(b'\0')[0] == name.encode():
            h = B[o:o+0x800]; w16, H = struct.unpack_from('<II', h, 0x24); assert struct.unpack_from('<I', h, 0x14)[0] == 256
            px = B[o+0x800:o+0x800+w16*2*H]; wb = w16*2; lin = bytearray(wb*H); k = 0
            for y in range(0, H, 32):
                for x in range(0, wb, 64):
                    for by in range(32):
                        for bx in range(64):
                            if y+by < H and k < len(px): lin[(y+by)*wb + x+bx] = px[k]
                            k += 1
            pal = struct.unpack_from('<256H', h, 0x100)
            c = lambda v: (0, 0, 0, 0) if v == 0 else ((v & 31)*255//31, ((v >> 5) & 31)*255//31, ((v >> 10) & 31)*255//31, 255)
            im = Image.new('RGBA', (wb, H)); im.putdata([c(pal[i]) for i in lin]); return im
    raise KeyError(name)
# the PS1 background: texels 0-160 on the left, the same mirrored on the right (320x160)
wall = tim('..\\BG\\CHAR\\NTITLE3U.TIM').crop((0, 0, 160, 160))
bg = Image.new('RGBA', (320, 160), (0, 0, 0, 255)); bg.alpha_composite(wall, (0, 0)); bg.alpha_composite(wall.transpose(Image.FLIP_LEFT_RIGHT), (160, 0))
px = bg.load()
for y in range(0x90, 0xA0):                       # subtractive fade, 0 at y 0x90 -> 255 at 0xA0 (as the PS1 G4 primitive)
    s = round(255 * (y - 0x90) / 16)
    for x in range(320): r, g, bl, a = px[x, y]; px[x, y] = (max(0, r - s), max(0, g - s), max(0, bl - s), 255)
# half size, then columns 8-151 of the 160: the 144x80 picture
pic = bg.resize((160, 80), Image.LANCZOS).crop((8, 0, 152, 80))
# the logo: rows 0-159 are the drawn part; crop to the non-transparent pixels, scale, centre
logo = tim('..\\BG\\CHAR\\NTITLEU.TIM').crop((0, 0, 256, 160)); logo = logo.crop(logo.getbbox())
lh = round(logo.height * LOGO_W / logo.width); logo = logo.resize((LOGO_W, lh), Image.LANCZOS)
pic.alpha_composite(logo, ((144 - LOGO_W) // 2, (80 - lh) // 2)); pic = pic.convert('RGB')
o = io.BytesIO(); pic.save(o, format='PNG', optimize=True); png = o.getvalue()
# 26,624 = the 13 sectors the original file occupies (written in place); 30,000 = the game's buffer
assert len(png) <= 26624 and len(png) <= 30000, ('savepic.png too large', len(png))
open(f'{OUT}/savepic.png', 'wb').write(png); pic.resize((432, 240), Image.NEAREST).save(f'{OUT}/savepic_preview.png')
json.dump(dict(bytes=len(png), md5=hashlib.md5(png).hexdigest(), size=pic.size, logo_width=LOGO_W, pillow=PIL.__version__), open(f'{OUT}/report.json', 'w'), indent=1)
print(f'save image: build/pict/savepic.png {len(png)} bytes (144x80 RGB), md5 {hashlib.md5(png).hexdigest()}')
