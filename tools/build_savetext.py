"""English save-screen text (2026-09-30; script/savedata_rules.json). Runs after build_sysmsg.py, in place on
build/eboot/ULJM05030_EBOOT_en.BIN. Reference: docs/RESEARCH.md §7, §14.
The strings the game hands the PSP savedata utility (title, details: difficulty, play time, location) and its two
Memory Stick errors are UTF-8 in .rodata (va 0x23CE1C-0x23DD8C), reached through R_MIPS_32 pointers in .data
(0x263344-0x2633EC table, 0x250704/08 errors). Unlike the in-game text they are ordinary UTF-8, because the PSP's own
system software draws them. Each English string is written over the Japanese one when it fits in
that string's space (up to the next string; zero-filled); otherwise it is appended to segment 2 (build_sysmsg.py's
added data) and that one pointer's relocation is retargeted there (like the system messages).
Save compatibility with the unmodified game: only these display strings change. The save identity strings are
checked to be unchanged: game name "ULJM05030", save-name format "%04d", "DATA.BIN" (and the utility parameters
are built by code we don't touch).
Format strings ("formats" in the rules): changed in place at a fixed address, e.g. the play-time format, whose
minutes the original never pads (it shows 0:7:34).
Save name: with --menu=localized a rule's "en_ps1_save" is used instead of "en" (the save title "Mega Man Legends",
which goes with the PS1 save image); --menu=original (default) keeps "en".
Usage: python3 tools/build_savetext.py [--menu=original|localized]
--menu is an internal argument, set by build.py: localized for --localization=legends, original otherwise."""
import json, struct, sys
# BASE: file offset of vaddr 0. SEG1: vaddr of segment 1 (.data). RELD / RELN: .rel.data file offset and entry count
# (8-byte entries: offset, info; info = type | offset-base segment << 8 | address-base segment << 16).
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; SEG1 = 0x245200; RELD, RELN = 0x3CF6D0, 0x1E6F0 // 8
R = json.load(open('script/savedata_rules.json'))
MENU = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--menu=')), 'original'); assert MENU in ('original', 'localized')
d = bytearray(open(P, 'rb').read())
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
assert phnum == 3, 'run after build_sysmsg.py (segment 2 expected)'
ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
# rel = {vaddr of each relocated word: index of its entry}
rel = {}
for k in range(RELN):
    o, i = struct.unpack_from('<II', d, RELD + 8 * k); rel[o + (SEG1 if (i >> 8) & 0xFF == 1 else 0)] = k
# ptr(slot): the string address stored in a pointer slot. The slot must be a R_MIPS_32 (type 2) whose address base is
# segment 0 (.rodata lies in the first segment), so the stored word is the string's vaddr.
# cstr(va): the NUL-terminated string there. space(va): bytes from va up to the next non-zero byte after its NUL,
# i.e. the string plus the zero padding that follows it = what a replacement may occupy.
def ptr(slot):
    i = struct.unpack_from('<II', d, RELD + 8 * rel[slot])[1]; assert i & 0xFF == 2 and (i >> 16) & 0xFF == 0, hex(i)
    return struct.unpack_from('<I', d, BASE + slot)[0]
def cstr(va): e = d.index(b'\0', BASE + va); return bytes(d[BASE + va:e])
def space(va):
    k = d.index(b'\0', BASE + va)
    while d[k] == 0: k += 1
    return k - (BASE + va)
for ident in (b'ULJM05030\0', b'%04d\0', b'DATA.BIN\0'):             # save identity: must stay as the original's
    assert d.count(ident) >= 1
# ph[2] = the third program header (file offset at [1], file size at [4]); seg2 = its current contents
seg2 = bytearray(d[ph[2][1]:ph[2][1] + ph[2][4]]); moved = []; inplace = 0
for s in R['strings']:
    slot = int(s['slot'], 16); va = ptr(slot); jp = cstr(va).decode('utf-8')
    # the rule quotes the Japanese string (or its start) it replaces: stop if the program holds something else
    assert jp == s['jp'] if 'jp' in s else jp.startswith(s['jp_start']), ('Japanese text changed?', s['slot'], jp[:20])
    en = (s.get('en_ps1_save', s['en']) if MENU == 'localized' else s['en']).encode('utf-8') + b'\0'
    if len(en) <= space(va):
        d[BASE + va:BASE + va + space(va)] = en + bytes(space(va) - len(en)); inplace += 1
    else:
        off = len(seg2); seg2 += en
        while len(seg2) % 4: seg2 += b'\0'
        # retarget: address base -> segment 2, stored word -> offset inside segment 2
        k = rel[slot]; o, i = struct.unpack_from('<II', d, RELD + 8 * k)
        struct.pack_into('<II', d, RELD + 8 * k, o, (i & ~0xFF0000) | (2 << 16)); struct.pack_into('<I', d, BASE + slot, off)
        moved.append((s['en'], off))
# format strings changed in place (script/savedata_rules.json formats; e.g. the play-time format). Must fit before the
# next non-zero byte (the save identity string follows) and the original must match exactly.
for f in R.get('formats', []):
    va = int(f['va'], 16); jp = f['jp'].encode() + b'\0'; en = f['en'].encode() + b'\0'
    assert bytes(d[BASE + va:BASE + va + len(jp)]) == jp, ('format string changed?', f['va'])
    assert len(en) <= space(va), ('format string does not fit', f['va'], len(en), space(va))
    d[BASE + va:BASE + va + space(va)] = en + bytes(space(va) - len(en))
# segment 2 grows: it is followed only by the program headers (build_sysmsg.py), rewrite them after it
while len(seg2) % 16: seg2 += b'\0'
del d[ph[2][1]:]; d += seg2; ph[2][4] = ph[2][5] = len(seg2)
while len(d) % 4: d += b'\0'
new_phoff = len(d)
for p in ph: d += struct.pack('<8I', *p)
struct.pack_into('<I', d, 0x1C, new_phoff)
open(P, 'wb').write(d)
print(f'save text ({MENU} save name): {len(R.get("formats", []))} format(s), {inplace} strings in place, {len(moved)} moved to segment 2 {moved}; segment 2 now {len(seg2)} bytes')
