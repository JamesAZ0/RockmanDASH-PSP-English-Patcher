"""Build check (run by build.py): the PSP menu files of the built ISO (tools/build_xmb.py, pack_inplace.py).

Checks: PSP_GAME/PIC0.PNG is build/pict/PIC0.PNG; when build_xmb.py edited it (build/pict/xmb.json), every pixel in
        rows 0-163 is fully transparent and every pixel from row 164 down equals the original's; PSP_GAME/PIC1.PNG is
        byte-identical to the original; PSP_GAME/SND0.AT3 is not in the built image.
Reads:  the built ISO, the original PSP ISO (tools/inputs.py), build/pict/PIC0.PNG, build/pict/xmb.json. Writes nothing.
Failure (exit 1, stops the build): the failed checks are listed.
Usage: python3 tools/checks/verify_xmb.py <tag>"""
import sys, io, json, pycdlib
from PIL import Image
sys.path.insert(0, 'tools'); import inputs as IN
tag = sys.argv[1]; rep = json.load(open('build/pict/xmb.json'))
def files(p):
    i = pycdlib.PyCdlib(); i.open(p); out = {}
    for c in i.list_children(iso_path='/PSP_GAME'):
        n = c.file_identifier().decode().split(';')[0]
        if c.is_file():
            b = io.BytesIO(); i.get_file_from_iso_fp(b, iso_path='/PSP_GAME/' + n); out[n] = b.getvalue()
    i.close(); return out
new, old = files(f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'), files(IN.PSP)
bad = []
if new.get('PIC0.PNG') != open('build/pict/PIC0.PNG', 'rb').read(): bad.append('PIC0.PNG is not the built file')
elif rep['edited']:
    a, b = Image.open(io.BytesIO(new['PIC0.PNG'])).convert('RGBA'), Image.open(io.BytesIO(old['PIC0.PNG'])).convert('RGBA')
    cut = rep['cut']
    if a.size != b.size: bad.append('PIC0.PNG size')
    else:
        if a.crop((0, 0, a.width, cut)).getchannel('A').getextrema() != (0, 0): bad.append('PIC0.PNG: tagline rows not transparent')
        if a.crop((0, cut, a.width, a.height)).tobytes() != b.crop((0, cut, b.width, b.height)).tobytes(): bad.append('PIC0.PNG: copyright rows changed')
elif new['PIC0.PNG'] != old['PIC0.PNG']: bad.append('PIC0.PNG changed although not edited')
if new.get('PIC1.PNG') != old.get('PIC1.PNG'): bad.append('PIC1.PNG changed')
if 'SND0.AT3' in new: bad.append('SND0.AT3 still present')
print(f"PSP menu files: overlay {'edited (tagline removed)' if rep['edited'] else 'unchanged (not the known file)'}, background unchanged, "
      f"music removed; problems: {len(bad)} {bad if bad else ''}")
sys.exit(1 if bad else 0)
