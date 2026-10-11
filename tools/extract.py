"""Extract the inputs the build needs from the two original disc images (read-only). First data step of
build.py, after tools/plain_eboot.py. Reference: docs/RESEARCH.md §2.
Usage: python3 tools/extract.py
Writes:
  extracted/ps1/<BIN stem>/<path inside BIN>.MSG   English PS1 dialogue (129 files)
  extracted/psp/<BIN stem>/<path inside BIN>.MSG   Japanese PSP dialogue (129 files)
  extracted/psp/FONT/bg/char/font.dat              PSP font entry (0x800 header + 32 KB texture; used for letter widths)
  extracted/ps1/ROCK_NEO.EXE                        US executable (source of the English system messages and the
                                                    mission banner layout; also for re-running the opcode analysis)
Each MSG is stored as its container entry: 0x800-byte header + data padded to 0x800 (same as DashEditor's -e output).

Disc layout this relies on (JP/US comparison): the PSP game is a near 1:1 port of the PS1 data. PS1 CDDATA/DAT/*.BIN
(205 files) and PSP PSP_GAME/USRDIR/DAT/*.BIN (204; only the US font KAIFONT.BIN has no PSP counterpart) have the
same names and the same container format: a sequence of entries, each a 0x800-byte header (+0 type, +4 data size,
+0x40 name "..\\PATH\\NAME.EXT") followed by its data padded to 0x800. A dialogue file therefore has the same path
on both discs, e.g. ST00_01/mess/st00_01.msg = entry ..\\mess\\st00_01.msg in ST00_01.BIN.
It also prints which PSP image is used and whether its CRC32 is a known one (tools/inputs.py)."""
import os, io, struct, sys, pycdlib
sys.path.insert(0, os.path.dirname(__file__)); from rawiso import open_ps1
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
# import tools/inputs.py from this file's own folder, wherever the tool is run from
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '')); import inputs as _IN
PSP = _IN.PSP                    # PSP base image: tools/inputs.py (the path build.py passes in PSP_ISO, or the default)
# round up to a whole 0x800-byte sector
def pad(n): return (n + 0x7FF) & ~0x7FF

def entries(data, want):
    """Yield (inner_path, bytes) for container entries whose name ends with one of `want` (lowercase).
    Walks the container sector by sector; an entry header is recognised by a name starting with "..\\" at +0x40 and
    entry type 0 (MSG) or 3 (the font). A matching entry is skipped as a whole; anything else one sector at a time."""
    off = 0
    while off + 0x800 <= len(data):
        name = bytes(data[off+0x40:off+0x80]).split(b'\0')[0]
        if name.startswith(b'..\\') and name.lower().endswith(want) and struct.unpack_from('<I', data, off)[0] in (0, 3):
            size = struct.unpack_from('<I', data, off+4)[0]
            yield name[3:].decode().replace('\\', '/'), bytes(data[off:off + 0x800 + pad(size)])
            off += 0x800 + pad(size); continue
        off += 0x800

# every DAT/*.BIN of one disc: write its .msg entries, and the .dat entry of FONT.BIN only; returns the count
def dump(iso, dat_dir, out_root, suffix=';1'):
    n = 0
    for c in iso.list_children(iso_path=dat_dir):
        if not c.is_file(): continue
        fn = c.file_identifier().decode(); base = fn.split(';')[0]
        if not base.upper().endswith('.BIN'): continue
        b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=f'{dat_dir}/{fn}'); data = b.getvalue()
        stem = base.rsplit('.', 1)[0]
        for inner, blob in entries(data, (b'.msg', b'.dat')):
            if inner.lower().endswith('.dat') and stem != 'FONT': continue
            p = os.path.join(out_root, stem, inner); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'wb').write(blob); n += 1
    return n

import ps1check                                    # is it Track 1 of the US disc? (tools/ps1check.py)
_lvl, _msg = ps1check.check(PS1)
print(f'PS1 image: {PS1}\n  {_msg}')
if _lvl == 'bad': raise SystemExit('PS1 image: ' + _msg)
ps1 = open_ps1(PS1)
print('PS1 MSGs:', dump(ps1, '/CDDATA/DAT', 'extracted/ps1'))
b = io.BytesIO(); ps1.get_file_from_iso_fp(b, iso_path='/ROCK_NEO.EXE;1'); open('extracted/ps1/ROCK_NEO.EXE', 'wb').write(b.getvalue())
_c = _IN.crc32(PSP)
_kind, _txt = _IN.describe(PSP)
print(f'PSP base: {PSP}\n  {_txt}; CRC32 {_c:08X}: ' + _IN.KNOWN.get(_c, 'not in the known list - the build checks every byte it patches, but compare the result'))
psp = pycdlib.PyCdlib(); psp.open(PSP)
print('PSP MSGs + font:', dump(psp, '/PSP_GAME/USRDIR/DAT', 'extracted/psp'))
