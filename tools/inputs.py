"""Input disc images for the build (one place, used by every tool).
PSP base image: the path in the environment variable PSP_ISO (python build.py <tag> [iso] sets it). If none is given,
the single .iso in originalDiskImages/psp/ is used; if there are several, the PSN release is preferred (it reproduces
the reference MD5 in docs/BUILD.md).
The image is identified from its contents, not its name (describe()): the game ID and version from PARAM.SFO, and PSN
release vs. retail UMD from SYSDIR/BOOT.BIN (the PSN release has it zero-filled, a UMD has the unencrypted game program).
Both releases hold identical game files (EBOOT.BIN and every DAT file byte-for-byte, same disc positions; checked
2026-09-29 by a file-by-file comparison), so the build treats them the same; they differ only in SYSDIR/BOOT.BIN and
SYSDIR/UPDATE/*, which the build never touches. Known whole-image CRC32s: KNOWN. Reference: docs/RESEARCH.md §2."""
import os, io, sys, glob, struct, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pspcheck import KNOWN                           # CRC32 -> description of the known images (tools/pspcheck.py)
# PS1 image: the data track of the .bin/.cue dump (raw 2352-byte sectors, read through tools/rawiso.py)
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
PSN_NAME = 'originalDiskImages/psp/Rockman Dash - Hagane no Boukenshin (Japan) (PSP) (PSN).iso'
# PSP_ISO if set, else the only .iso in the folder, else the PSN release by its usual file name
def _pick():
    p = os.environ.get('PSP_ISO', '')
    if p: return p
    isos = sorted(glob.glob('originalDiskImages/psp/*.iso'))
    if len(isos) == 1: return isos[0]
    if PSN_NAME in isos: return PSN_NAME
    raise SystemExit('No PSP image: put one .iso in originalDiskImages/psp/ or pass it: python build.py <tag> <iso>')
PSP = _pick()
if not os.path.exists(PSP): raise SystemExit(f'PSP base image not found: {PSP}')

def _sfo(data):
    """PARAM.SFO -> dict (index entries of 16 bytes from offset 20; format 0x404 = integer, otherwise a string;
    layout described in tools/build_sfo.py)"""
    kt, dt, n = struct.unpack_from('<III', data, 8); out = {}
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', data, 20 + 16*i)
        k = data[kt+ko:data.index(b'\0', kt+ko)].decode()
        v = data[dt+do:dt+do+ln]
        out[k] = struct.unpack('<I', v)[0] if fmt == 0x0404 else v.rstrip(b'\0').decode('utf-8', 'replace')
    return out
def describe(path=PSP):
    """Identify an image by content -> (kind 'psn'|'umd', text)."""
    import pycdlib
    iso = pycdlib.PyCdlib(); iso.open(path)
    def get(q):
        b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=q); return b.getvalue()
    sfo = _sfo(get('/PSP_GAME/PARAM.SFO')); boot = get('/PSP_GAME/SYSDIR/BOOT.BIN'); iso.close()
    if sfo.get('DISC_ID') != 'ULJM05030': raise SystemExit(f'{path}: not Rockman DASH ULJM05030 (DISC_ID {sfo.get("DISC_ID")})')
    kind = 'umd' if any(boot) else 'psn'
    return kind, f'ULJM05030 v{sfo.get("DISC_VERSION", "?")}, ' + ('retail UMD (BOOT.BIN present)' if kind == 'umd' else 'PSN release (BOOT.BIN blank)')
# CRC32 of the whole image, read in 4 MB pieces
def crc32(path):
    c = 0
    with open(path, 'rb') as f:
        while b := f.read(1 << 22): c = zlib.crc32(b, c)
    return c
BASE_NAME = os.path.basename(PSP)
