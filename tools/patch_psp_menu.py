"""Program part of the localized PSP menu / save picture: keep the new save image from being replaced by an old
save's. Part of `python build.py <tag> --localization=legends`; build.py passes the internal argument `localized`
for legends and `original` for text / audio (2026-10-01).
The game loads DAT/PICT/savepic.png once at start into a 30,000-byte buffer (segment 1 + 0x111D48) and hands that buffer
to the PSP save utility as the save's ICON0 when saving (0x4F698). But its load setup (function 0x4F370) hands the
SAME buffer to the utility as the place to load the chosen save's ICON0 into (buffer + size 0x7530, no data size), so
after a save is loaded the buffer holds that save's picture, and every later save writes it back. With the original
game all pictures are the same, so it never shows; with the localized picture, any save loaded from an older build
brought the Japanese picture back (seen in an in-game test: new saves and overwrites still had the old icon; the cause
was then found by reading the save and load setup code).
Fix (localized only): the load setup gives the utility the spare 30,000-byte buffer right after it instead
(segment 1 + 0x119278, which the same code sets up as the ICON1 load buffer; saves have no ICON1, so it is unused):
  0x4F464  sw v0,0x584(s2)  -> nop               (ICON0 load buffer no longer = the savepic buffer)
  0x4F47C  sw v1,0x594(s2)  -> sw v1,0x584(s2)   (ICON0 load buffer = the spare buffer; v1 already holds its address)
  0x4F480  sw a1,0x598(s2)  -> nop               (no ICON1 load buffer; its pointer/size stay 0)
The size at 0x588 (0x7530) is still set at 0x4F48C. No relocated word is touched. Runs after build_savetext.py on
build/eboot/ULJM05030_EBOOT_en.BIN. Usage: python3 tools/patch_psp_menu.py original|localized   (internal argument)
Report: build/eboot/psp_menu.json (checked by audit_eboot.py and verify_ps1_title.py). See docs/RESEARCH.md §14."""
import sys, json, struct
MODE = sys.argv[1] if len(sys.argv) > 1 else 'original'; assert MODE in ('original', 'localized')
# BASE: file offset of virtual address 0 (code segment)
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/psp_menu.json'
if MODE == 'original':
    json.dump(dict(mode='original'), open(REP, 'w')); print('save icon buffer: original'); sys.exit(0)
d = bytearray(open(P, 'rb').read()); words = {}
# r32 / w32: read a word; replace a word after checking its original value (kept in `words` for the report)
def r32(va): return struct.unpack_from('<I', d, BASE + va)[0]
def w32(va, old, new):
    assert r32(va) == old, ('unexpected original word', hex(va), hex(r32(va))); words[va] = [old, new]; struct.pack_into('<I', d, BASE + va, new)
# rel = the code addresses Sony's relocation table rewrites at load (table at file offset 0x325018, 0x9F3D8 bytes,
# 8-byte entries offset + info; bits 8-15 of info = the segment the offset is in, 0 = code)
o = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8]
rel = {struct.unpack_from('<I', o, k)[0] for k in range(0, len(o), 8) if (struct.unpack_from('<I', o, k + 4)[0] >> 8) & 0xFF == 0}
# the code as described: lui/addiu 0x111D48 -> v0, lui/addiu 0x119278 -> v1, a1 = 0x7530, sizes stored at 0x588 / 0x598
# 0x3C020011 lui v0,0x11 / 0x24421D48 addiu v0,v0,0x1D48; 0x3C030012 lui v1,0x12 / 0x24639278 addiu v1,v1,-0x6D88;
# 0x24057530 addiu a1,zero,0x7530 (30,000); 0xAE450588 sw a1,0x588(s2)
assert (r32(0x4F44C), r32(0x4F454), r32(0x4F460), r32(0x4F474), r32(0x4F46C), r32(0x4F48C)) == (0x3C020011, 0x24421D48, 0x3C030012, 0x24639278, 0x24057530, 0xAE450588)
# the spare buffer starts exactly where the savepic buffer ends
assert 0x111D48 + 0x7530 == 0x119278
# 0xAE420584 sw v0,0x584(s2); 0xAE430594 sw v1,0x594(s2); 0xAE450598 sw a1,0x598(s2)
w32(0x4F464, 0xAE420584, 0); w32(0x4F47C, 0xAE430594, 0xAE430584); w32(0x4F480, 0xAE450598, 0)
assert not (set(words) & rel), 'relocated word patched'
open(P, 'wb').write(d)
json.dump(dict(mode='localized', words={hex(k): [hex(a), hex(v)] for k, (a, v) in sorted(words.items())}), open(REP, 'w'), indent=1)
print(f'save icon buffer: loads go to the spare buffer ({len(words)} EBOOT words changed)')
