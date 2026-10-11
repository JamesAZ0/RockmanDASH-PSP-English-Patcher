"""Is this file a usable PSP image? Used by gui.py when a file is picked; tools/inputs.py takes KNOWN from here.

The build starts from the Japanese Rockman DASH, ULJM05030, as an .iso: the PSN release or a retail UMD image (both
hold the same game files; docs/RESEARCH.md §2).
check(path) -> (level, message):
  'ok'    ULJM05030 and the whole-image CRC32 is one of the known images (KNOWN)
  'warn'  ULJM05030 but not a known image: patching may still work; every step checks what it reads
  'bad'   not usable, with the reason (not a disc image, another game, ...)
How it is recognised: an ISO 9660 image whose PSP_GAME/PARAM.SFO has DISC_ID ULJM05030; PSN release or UMD from
SYSDIR/BOOT.BIN (zero-filled in the PSN release)."""
import os, io, struct, zlib

KNOWN = {  # CRC32 of the whole image -> description (Renascene / preservation lists)
    0xC2E6D0B9: 'PSN release, known good',
    0x78DFD145: 'retail UMD, known good (Redump-size image)',
    0x17F6EDE5: 'retail UMD, known underdump: last (empty) 2048-byte sector missing - content intact, build unaffected',
}
SHOWN = {0xC2E6D0B9: 'PSN release', 0x78DFD145: 'UMD release',
         0x17F6EDE5: 'UMD release'}       # the known dump without its last, empty sector: game data complete


def sfo(data):
    """PARAM.SFO -> dict (index entries of 16 bytes from offset 20; format 0x404 = integer, otherwise a string;
    layout described in tools/build_sfo.py)"""
    kt, dt, n = struct.unpack_from('<III', data, 8); out = {}
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', data, 20 + 16*i)
        k = data[kt+ko:data.index(b'\0', kt+ko)].decode()
        v = data[dt+do:dt+do+ln]
        out[k] = struct.unpack('<I', v)[0] if fmt == 0x0404 else v.rstrip(b'\0').decode('utf-8', 'replace')
    return out


def crc32(path):
    """CRC32 of the whole file, read in 4 MB pieces"""
    c = 0
    with open(path, 'rb') as f:
        while b := f.read(1 << 22):
            c = zlib.crc32(b, c)
    return c


def check(path):
    """-> (level, message) as described at the top; the message is what the patcher shows under the file picker"""
    if not os.path.isfile(path):
        return 'bad', 'Not valid: file not found.'
    try:
        import pycdlib
        iso = pycdlib.PyCdlib(); iso.open(path)
        try:
            def get(q):
                b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=q); return b.getvalue()
            info = sfo(get('/PSP_GAME/PARAM.SFO')); boot = get('/PSP_GAME/SYSDIR/BOOT.BIN')
        finally:
            iso.close()
    except Exception:
        return 'bad', 'Not valid: not a PSP disc image (.iso).'
    if info.get('DISC_ID') != 'ULJM05030':
        return 'bad', 'Not valid: not Rockman DASH (Japan).'
    c = crc32(path)
    if c in SHOWN:
        return 'ok', f'Verified: Rockman DASH (Japan), {SHOWN[c]}.'
    kind = 'UMD release' if any(boot) else 'PSN release'
    return 'warn', f'Unverified: Rockman DASH (Japan), {kind}. Checksum differs.'


if __name__ == '__main__':
    import sys
    print(*check(sys.argv[1]), sep=': ')
