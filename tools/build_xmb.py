"""PSP menu (XMB) overlay without the Japanese tagline; run by build.py for every localization.

When the game is highlighted in the PSP's menu, the menu shows PSP_GAME/PIC1.PNG (480x272 background artwork, no
text) with PSP_GAME/PIC0.PNG (310x180, transparent) drawn over it, and plays PSP_GAME/SND0.AT3. PIC0.PNG holds two
things: a Japanese tagline in rows 130-158 with a soft drop shadow that fades out by row 165, and the line
"(c) CAPCOM CO., LTD. 1997, 2005 ALL RIGHTS RESERVED." in rows 164-173 (first lettering pixels in row 164).
Project decision (2026-10-05): the tagline is removed by making rows 0-163 fully transparent; nothing is drawn and
no other picture is added. Rows 164 and below are kept exactly, so the copyright line and its soft edges are
unchanged (what is left of the shadow there is at most 5/255 opaque). PIC1.PNG is not touched. The music SND0.AT3
is removed from the image by tools/pack_inplace.py (--drop-snd0).

Reads:  PSP_GAME/PIC0.PNG from the PSP image (tools/inputs.py).
Writes: build/pict/PIC0.PNG (must fit the original file's sectors; pack_inplace.py --pic0= puts it in place) and
        build/pict/xmb.json. If the image's PIC0.PNG is not the known file (SHA-1 below) it is copied unchanged and
        the report says so.
The exact bytes of the new PNG depend on the imaging library version (as for the save picture).
Usage: python3 tools/build_xmb.py   (needs Pillow)"""
import sys, os, io, json, hashlib, pycdlib
import PIL; from PIL import Image
sys.path.insert(0, 'tools'); import inputs as IN
OUT = 'build/pict'; os.makedirs(OUT, exist_ok=True)
SHA1 = '073fba44f134a8e15dce7f113505ec2bb501a100'    # PIC0.PNG of ULJM05030 (13,228 bytes; same in the PSN and UMD images)
CUT = 164                                            # first row kept: the top of the copyright line
iso = pycdlib.PyCdlib(); iso.open(IN.PSP); b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path='/PSP_GAME/PIC0.PNG'); iso.close()
# known: only the file this cut was measured on is edited
orig = b.getvalue(); known = hashlib.sha1(orig).hexdigest() == SHA1
if known:
    im = Image.open(io.BytesIO(orig)).convert('RGBA'); assert im.size == (310, 180), im.size
    im.paste((0, 0, 0, 0), (0, 0, im.width, CUT))    # rows 0..CUT-1 transparent
    o = io.BytesIO(); im.save(o, 'PNG', optimize=True); png = o.getvalue()
    # the new file replaces the old one in place, so it may not need more 2048-byte sectors
    pad = lambda n: (n + 2047) // 2048 * 2048
    assert pad(len(png)) <= pad(len(orig)), ('the new PIC0.PNG does not fit the original sectors', len(png), len(orig))
else:
    png = orig
open(f'{OUT}/PIC0.PNG', 'wb').write(png)
json.dump(dict(edited=known, cut=CUT, bytes=len(png), original_bytes=len(orig), md5=hashlib.md5(png).hexdigest(), pillow=PIL.__version__),
          open(f'{OUT}/xmb.json', 'w'), indent=1)
print(f'PSP menu overlay: tagline rows 0-{CUT - 1} cleared, {len(orig)} -> {len(png)} bytes' if known else
      'PSP menu overlay: PIC0.PNG is not the known file, left unchanged')
