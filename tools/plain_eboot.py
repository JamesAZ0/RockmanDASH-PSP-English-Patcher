"""The game's program as a plain (unencrypted) ELF -> decrypted_eboot/ULJM05030_EBOOT.BIN, made from the user's own
PSP image. Never distributed (.gitignore). First build step (build.py). Reference: docs/RESEARCH.md §5.
Why: the program on the disc (PSP_GAME/SYSDIR/EBOOT.BIN) is encrypted; every patch tool works on the plain ELF, and
the build writes a plain ELF back (custom firmware and PPSSPP run it). Sources, in this order:
  1. the file is already there (an earlier run, or a PPSSPP dump: docs/BUILD.md section 2): checked and kept;
  2. a retail UMD image: PSP_GAME/SYSDIR/BOOT.BIN is the plain program; it is copied;
  3. the PSN release (BOOT.BIN is blank): PSP_GAME/SYSDIR/EBOOT.BIN is decrypted with pyeboot (pip install pyeboot;
     GPL-3, wraps pspdecrypt; THIRD_PARTY.md).
All three give the same 4,162,891-byte ELF (SHA-1 below; a PPSSPP dump has 341 more bytes after it, which nothing uses).
EBOOT.BIN itself is identical on the PSN release and the UMD.
Usage: python3 tools/plain_eboot.py"""
import sys, os, io, struct, hashlib, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import inputs
# SHA1 / SIZE: the expected plain ELF (ULJM05030 v1.01), measured up to the end of the ELF (see elf_end)
OUT = 'decrypted_eboot/ULJM05030_EBOOT.BIN'; SHA1 = 'f615a7040cf809be784780eedb02e3f2c5769235'; SIZE = 4162891
# End of the ELF proper: the furthest of the section-header table (e_shoff 0x20, e_shnum 0x30, 40-byte headers) and
# every section's file bytes (offset [4] + size [5]). Anything after it (a dump's tail) is ignored by the check.
def elf_end(d):
    shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30); end = shoff + 40 * shnum
    for k in range(shnum):
        s = struct.unpack_from('<10I', d, shoff + 40 * k)
        if s[1] != 8: end = max(end, s[4] + s[5])            # (.bss has no file bytes)
    return end
# report whether the ELF is the expected one; a different one is allowed (the patch tools verify what they change)
def check(d, what):
    if d[:4] != b'\x7fELF': raise SystemExit(f'{what}: not a plain ELF program')
    ok = hashlib.sha1(d[:elf_end(d)]).hexdigest() == SHA1
    print(f'plain program from {what}: ' + ('the expected one' if ok else 'NOT the expected one (another game version?): the patches check '
          'each original instruction and stop if it differs'))
if os.path.exists(OUT):
    check(open(OUT, 'rb').read(), OUT); sys.exit(0)
import pycdlib
iso = pycdlib.PyCdlib(); iso.open(inputs.PSP)
def get(q):
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=q); return b.getvalue()
boot = get('/PSP_GAME/SYSDIR/BOOT.BIN')
# a UMD image has the plain program as BOOT.BIN; the PSN release has zeros there and needs the decryption
if boot[:4] == b'\x7fELF':
    d = boot; what = 'the UMD image\'s BOOT.BIN'
else:
    try: import pyeboot
    except ImportError:
        raise SystemExit('This PSP image (PSN release) has no plain program, and pyeboot is not installed. Either: pip install '
                         'pyeboot; or build from a retail UMD image; or put a PPSSPP dump at ' + OUT + ' (docs/BUILD.md section 2)')
    with tempfile.TemporaryDirectory() as t:
        a, b = os.path.join(t, 'EBOOT.BIN'), os.path.join(t, 'BOOT.BIN')
        open(a, 'wb').write(get('/PSP_GAME/SYSDIR/EBOOT.BIN'))
        if not pyeboot.decrypt(a, b) or not os.path.exists(b): raise SystemExit('pyeboot could not decrypt EBOOT.BIN')
        d = open(b, 'rb').read()
    what = 'EBOOT.BIN, decrypted with pyeboot'
check(d, what)
os.makedirs(os.path.dirname(OUT), exist_ok=True); open(OUT, 'wb').write(d)
