"""English audio, program part: point the free PSP voice-bank slots at the English clips. Run by build.py for
--localization=audio|legends, after build_sysmsg.py / build_savetext.py / build_subtitles.py, in place on
build/eboot/ULJM05030_EBOOT_en.BIN. Report: logs/voice_eboot_report.json; check: tools/checks/verify_voice_eboot.py.
Adds a 4th PT_LOAD segment (after segment 2) holding, per English bank, an array of path pointers followed by the path
strings ("disc0:/PSP_GAME/USRDIR/DAT/at3/xaen/eBB_CC.at3", files written by pack_inplace.py --audio, an internal flag
set by build.py). The bank-table
slot (seg-1 offset 0xA864 + 4*slot, zero in the original) gets the array's offset. Every new pointer needs a
relocation, so a new relocation section (type 0x700000A0, entries R_MIPS_32 = 2 | ofs_base<<8 | addr_base<<16, like
.rel.data) is appended with a copy of the section-header table that includes it; e_shoff/e_shnum and the program
headers (now 4) are moved to the file end. Nothing already in the file changes except those header fields, the
36 zero slots, and (since 2026-09-30) the path-array entries of the 5 news reports the game code starts directly
(script/voice_rules.json code_voice: bank 6 clips rn00-rn03 and rm now point at the English clips; the code's ids and
so its subtitle trigger are unchanged).
Game side (static analysis of the voice lookup, EBOOT 0xACA0 / 0xADAC; see voice_banks.py): a sound id is
type<<28 | bank<<16 | clip; the bank table gives a bank's path array; only null checks, so a free slot can simply
be filled. The 5 news reports were found by an audit of every caller of the lookup: they are the only voice clips
started by code rather than by a dialogue AUDIO op. See docs/RESEARCH.md §10, and §5 for segments and relocations.
Usage: python3 tools/voice/patch_eboot_voice.py"""
import sys, os, struct, json
sys.path.insert(0, os.path.dirname(__file__)); import voice_banks as VB
# BASE: file offset of virtual address 0; SEG1: virtual address of segment 1 (.data)
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; SEG1 = 0x245200
d = bytearray(open(P, 'rb').read())
# ELF header: e_phoff 0x1C / e_phnum 0x2C; e_shoff 0x20 / e_shnum 0x30. Program header = 8 u32 (type, offset, vaddr,
# paddr, file size, memory size, flags, align); section header = 10 u32 ([1] type, [4] file offset, [5] size)
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
shoff, = struct.unpack_from('<I', d, 0x20); shnum, shstr = struct.unpack_from('<HH', d, 0x30)
assert phnum == 3, ('expected the 3 segments from build_sysmsg.py', phnum)
ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
sh = [list(struct.unpack_from('<10I', d, shoff + 40 * k)) for k in range(shnum)]
reld = next(s for s in sh if s[1] == 0x700000A0 and s[4] == 0x3CF6D0)      # .rel.data: template for the new section
# rel_existing: the offsets .rel.data already relocates (a free bank slot must not be among them)
rel_existing = {struct.unpack_from("<I", d, reld[4] + 8 * k)[0] for k in range(reld[5] // 8)}
# --- segment 3 blob
# blob: first one pointer array per bank (4 bytes per clip, filled with segment-3 offsets below), then the path
# strings, each 0-terminated and padded to 4 bytes. strings: [(offset of the pointer, offset of its string)]
C = VB.clips(); blob = bytearray(); arrays = {}; strings = []
for b in sorted(C):
    arrays[b] = len(blob); blob += b'\0' * (4 * len(C[b]))
for b in sorted(C):
    for c in range(len(C[b])):
        strings.append((arrays[b] + 4 * c, len(blob))); blob += VB.game_path(b, c).encode() + b'\0'
        while len(blob) % 4: blob += b'\0'
for slot_off, s_off in strings: struct.pack_into('<I', blob, slot_off, s_off)
while len(blob) % 16: blob += b'\0'
# segment 3's virtual address: the end of segment 2 in memory, rounded up to 0x40
NEWV = (ph[2][2] + ph[2][5] + 0x3F) & ~0x3F
# Relocations (offset, info). Bank slot: R_MIPS_32, offset in segment 1, address in segment 3 (2 | 1<<8 | 3<<16).
# Path pointer: offset and address both in segment 3 (2 | 3<<8 | 3<<16)
relocs = []
for b in sorted(C):
    slot_off = VB.BANK_TABLE_SEG1 + 4 * VB.SLOTS[b]
    assert struct.unpack_from('<I', d, BASE + SEG1 + slot_off)[0] == 0 and slot_off not in rel_existing, ('slot in use', b)
    struct.pack_into('<I', d, BASE + SEG1 + slot_off, arrays[b]); relocs.append((slot_off, 2 | (1 << 8) | (3 << 16)))
for slot_off, _ in strings: relocs.append((slot_off, 2 | (3 << 8) | (3 << 16)))
# --- append: segment 3, relocations, section headers, program headers
while len(d) % 0x40: d += b'\0'
seg_off = len(d); d += blob
rel_off = len(d)
for o, i in relocs: d += struct.pack('<II', o, i)
while len(d) % 4: d += b'\0'
new = list(reld); new[4] = rel_off; new[5] = 8 * len(relocs)   # sh_offset, sh_size (sh_info stays .data)
sh.append(new)
new_shoff = len(d)
for s in sh: d += struct.pack('<10I', *s)
# the new program header: PT_LOAD (1), file offset, vaddr, paddr 0, file size = memory size, flags 4 (read), align 0x10
ph.append([1, seg_off, NEWV, 0, len(blob), len(blob), 4, 0x10])
new_phoff = len(d)
for p in ph: d += struct.pack('<8I', *p)
struct.pack_into('<I', d, 0x1C, new_phoff); struct.pack_into('<H', d, 0x2C, len(ph))
struct.pack_into('<I', d, 0x20, new_shoff); struct.pack_into('<H', d, 0x30, len(sh))
# --- voice clips started by game code (City Hall news reports, script/voice_rules.json code_voice; 2026-09-30)
# The code keeps its Japanese ids (bank 6, clips 0x12-0x15 / 0x2E). Instead, those clips' entries in the bank-6 path
# array now point at the English clip's path string in segment 3 (relocation retargeted seg 0 -> seg 3). Being bank 6,
# the ids still start the subtitle scenes C00-C04 (EBOOT 0xAD08 jump table), which build_subtitles.py fills in English
# (an earlier version changed the ids in the code instead, which stopped the news subtitles).
# spath: {(English bank, clip): segment-3 offset of its path string}; en_bc: clip name bBB_cCC_K -> (bank, clip number)
CV = json.load(open('script/voice_rules.json'))['code_voice']
spath = {}
for b in sorted(C):
    for c in range(len(C[b])): spath[(b, c)] = None
it = iter(strings)
for b in sorted(C):
    for c in range(len(C[b])): spath[(b, c)] = next(it)[1]
def en_bc(name):
    b = int(name[1:3]); c = [k for k, f in enumerate(C[b]) if f.endswith('/' + name + '.xa')]; assert len(c) == 1, name
    return b, c[0]
# bank6: segment-1 offset of bank 6's path array (the stored word, before relocation). allrel: {segment-1 offset:
# file offset of its relocation entry} over every relocation section but the new one
bank6 = struct.unpack_from('<I', d, BASE + SEG1 + VB.BANK_TABLE_SEG1 + 4 * 6)[0]
allrel = {}
for s_ in sh:
    if s_[1] != 0x700000A0 or s_[4] == rel_off: continue
    for k in range(s_[5] // 8):
        o, i = struct.unpack_from('<II', d, s_[4] + 8 * k)
        if (i >> 8) & 0xFF == 1: allrel[o] = s_[4] + 8 * k
code_ids = {}
# Each code-started clip: its Japanese id (bank 6, clip = low 16 bits) gives the path-array entry. Its relocation
# must be R_MIPS_32 with address base 0 (the Japanese path strings are in segment 0) and the old string must be
# the expected Japanese file; then the entry gets the English string's offset and address base 3
for e in CV['table']['entries'] + [CV['constant']]:
    jid = int(e['jp_id'], 16); assert jid >> 16 == 6, e
    slot = bank6 + 4 * (jid & 0xFFFF); ro = allrel[slot]; o, i = struct.unpack_from('<II', d, ro)
    assert (i & 0xFF) == 2 and (i >> 16) & 0xFF == 0, ('path slot relocation', hex(slot), hex(i))
    old = struct.unpack_from('<I', d, BASE + SEG1 + slot)[0]; oe = d[BASE + old:d.index(b'\0', BASE + old)].decode()
    assert oe.endswith('/' + e['jp']), (oe, e['jp'])
    b, c = en_bc(e['en']); struct.pack_into('<I', d, BASE + SEG1 + slot, spath[(b, c)])
    struct.pack_into('<II', d, ro, o, (i & ~0xFF0000) | (3 << 16)); code_ids[e['scene']] = VB.game_path(b, c)
open(P, 'wb').write(d)
json.dump({'segment3_vaddr': hex(NEWV), 'bytes': len(blob), 'banks': {str(b): dict(slot=VB.SLOTS[b], clips=len(C[b])) for b in C},
           'relocations': len(relocs), 'code_voice': dict(sorted(code_ids.items()))}, open('logs/voice_eboot_report.json', 'w'), indent=1)
print(f'English voice banks: {len(C)} banks, {sum(map(len, C.values()))} clips -> slots {VB.SLOTS[0]}..{VB.SLOTS[-1]}; '
      f'segment 3 at vaddr {NEWV:#x} ({len(blob)} bytes); {len(relocs)} relocations; news reports {len(code_ids)} -> English; EBOOT {len(d)} bytes')
