"""Build check (run by build.py): every disc area the build writes beyond a file's original size was unused (all zero)
on the original ISO.

Why: the packer (tools/pack_inplace.py) keeps files at their original sectors because the game reads them by disc
position. A file that grows by a few sectors is allowed to run on into the gap before the next file, on the assumption
that the gap is padding. This check proves the assumption for every byte used that way; anything not zero there would
be original data the build has overwritten (docs/RESEARCH.md §15).

Reads:  build/test/<tag>/manifest.json (bins_changed: lba, old and new size, moved_to_lba; eboot: size) and the
        ORIGINAL PSP ISO (tools/inputs.py) - the built ISO is not opened. Writes nothing.
Checks: for each DAT/*.BIN that grew in place, original bytes [lba*2048 + old size, lba*2048 + new size) are zero;
        the same for the program file EBOOT.BIN if it grew in place. Files that were moved (to a slot freed by another
        file, or past the original image end) are only counted here; verify_layout.py checks that they overlap nothing.
Failure (exit 1, stops the build): 'NOT ZERO: tail of <BIN>' or 'NOT ZERO: EBOOT growth area'.

Usage: python3 tools/checks/verify_slack.py <tag>"""
import sys, json, pycdlib
tag = sys.argv[1]; SEC = 2048
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..')); import inputs as _IN
SRC = _IN.PSP                    # PSP base image: tools/inputs.py (PSP_ISO=psn|umd|path)
man = json.load(open(f'build/test/{tag}/manifest.json'))
iso = pycdlib.PyCdlib(); iso.open(SRC); f = open(SRC, 'rb'); end = f.seek(0, 2)
# zero(a, b) -> (bytes a..b of the original image are all 0, how many bytes were read)
def zero(a, b):
    f.seek(a); d = f.read(b - a); return d.count(0) == len(d), len(d)
bad = 0; checked = 0
for b in man['bins_changed']:
    if b['new'] > b['old'] and 'moved_to_lba' not in b:
        a = b['lba'] * SEC + b['old']; ok, n = zero(a, b['lba'] * SEC + b['new']); checked += n
        if not ok: bad += 1; print('NOT ZERO: tail of', b['bin'])
# the program file: its original directory record gives position and size; the manifest gives the built size
er = iso.get_record(iso_path='/PSP_GAME/SYSDIR/EBOOT.BIN'); size = man.get('eboot', {}).get('size', er.data_length)
if size > er.data_length and 'moved_to_lba' not in man.get('eboot', {}):
    ok, n = zero(er.extent_location() * SEC + er.data_length, er.extent_location() * SEC + size); checked += n
    if not ok: bad += 1; print('NOT ZERO: EBOOT growth area')
moved = [b for b in man['bins_changed'] if 'moved_to_lba' in b]
print(f'{checked} bytes of reused slack checked, all zero on the original: {bad == 0}; '
      f'{len(moved)} BINs moved (to freed slots or after the original end, see verify_layout.py)')
sys.exit(1 if bad else 0)
