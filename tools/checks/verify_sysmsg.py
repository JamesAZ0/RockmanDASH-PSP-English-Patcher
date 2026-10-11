"""Build check (run by build.py; its output is kept as build/test/<tag>/verify_sysmsg.txt): the system-message table in
the built program, read the way the PSP's module loader will see it.

Background (docs/RESEARCH.md §5, §7): menus, save screens, the options screen, item / part / weapon names and help
lines are not in the dialogue files but in the program: 248 pointers at vaddr 0x25451C, each to a string in dialogue
(MSG) format. Entries 0-241 correspond one to one with the US PS1 executable's table; 242-247 are PSP additions.
tools/build_sysmsg.py puts the English strings into added data and retargets each slot's relocation. The program is a
relocatable PRX-style ELF: a slot's stored value is an offset, and its relocation entry says which segment's address
is added to it. A slot whose relocation still names the wrong segment gives a wild pointer on hardware, so this check
resolves every slot from the file's own headers and relocations instead of trusting the builder's arithmetic.

Reads:  PSP_GAME/SYSDIR/EBOOT.BIN from the built ISO, or build/test/<tag>/EBOOT_plain.BIN when that exists (the plain
        ELF the packer wrote). Writes nothing.
Steps:  read the program headers (segment vaddrs and file ranges); collect the R_MIPS_32 entries of every relocation
        section (type 0x700000A0); for each of the 248 slots take its relocation's address-base segment, add that
        segment's vaddr to the stored value, and parse the string there up to its end op (0x91 return, 0x95 or 0x84
        close). Prints the segments, how many slots point into each, and ten sample strings as a visual sanity check.
Failure (exit 1, stops the build): 'NO END <slot> <address>' - the pointer does not lead to a well-formed string. A
        missing relocation for a slot raises KeyError.

Usage: python3 tools/checks/verify_sysmsg.py <tag>"""
import sys, io, struct, pycdlib
sys.path.insert(0, 'tools'); import msgtool as M
tag = sys.argv[1]; iso = pycdlib.PyCdlib(); iso.open(f'build/test/{tag}/RockmanDASH_EN_{tag}.iso')
b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path='/PSP_GAME/SYSDIR/EBOOT.BIN'); d = b.getvalue()
import os
if d[:4] == b'~PSP' or os.path.exists(f'build/test/{tag}/EBOOT_plain.BIN'):   # if the disc copy is encrypted (~PSP header) or a plain copy was kept: check the plain ELF pack_inplace.py wrote
    d = open(f'build/test/{tag}/EBOOT_plain.BIN', 'rb').read()
# ELF header: e_phoff at 0x1C, e_phnum at 0x2C; a program header is 8 u32: type, file offset, vaddr, paddr, filesz,
# memsz, ...
phoff, phnum = struct.unpack_from('<I', d, 0x1C)[0], struct.unpack_from('<H', d, 0x2C)[0]
ph = [struct.unpack_from('<8I', d, phoff + 32*k) for k in range(phnum)]
SEG = [p[2] for p in ph]
# foff: vaddr -> file offset, through the segment that contains it
def foff(va):
    for p in ph:
        if p[2] <= va < p[2] + p[4]: return va - p[2] + p[1]
    raise ValueError(hex(va))
rel = {}   # every relocation section (their file offsets move when tools/flatten_eboot.py rebuilds the file)
# section headers (e_shoff 0x20, e_shnum 0x30; 40 bytes each): s_[1] = type, s_[4] = file offset, s_[5] = size
shoff, shnum = struct.unpack_from('<I', d, 0x20)[0], struct.unpack_from('<H', d, 0x30)[0]
for sk in range(shnum):
    s_ = struct.unpack_from('<10I', d, shoff + 40*sk)
    # 0x700000A0 = PSP relocation section. Entry = (offset, info): info & 0xFF = type (2 = R_MIPS_32), (info >> 8) &
    # 0xFF = segment the offset is relative to, (info >> 16) & 0xFF = segment whose address is added
    if s_[1] != 0x700000A0: continue
    for k in range(s_[5] // 8):
        o, i = struct.unpack_from('<II', d, s_[4] + 8*k)
        if (i & 0xFF) == 2: rel[o + SEG[(i >> 8) & 0xFF]] = i
from jptable import T
bad = 0; segs = [0]*phnum; out = []
# 248 slots of 4 bytes at vaddr 0x25451C; ab = address-base segment of the slot's relocation
for j in range(248):
    slot = 0x25451C + 4*j; i = rel[slot]; ab = (i >> 16) & 0xFF; segs[ab] += 1
    tgt = struct.unpack_from('<I', d, foff(slot))[0] + SEG[ab]
    # 3000 bytes is more than the longest system string; parsing simply stops being used after the end op
    t, _ = M.parse(d[foff(tgt): foff(tgt) + 3000], True, True)
    end = next((k for k, x in enumerate(t) if x[0] == 'op' and x[1] in (0x91, 0x95, 0x84)), None)
    if end is None: bad += 1; print('NO END', j, hex(tgt)); continue
    # rough decode for the samples: PSP symbol glyphs, then the kana/kanji table; op A0 (padding) shown as a space
    SYM = {0x4F: ' ', 0x105: ',', 0x106: '"', 0x107: '.', 0x108: '…', 0x10A: '+', 0x10B: '%', 0x10C: ''}
    s = ''.join(('/' if x[1] == 0x86 else SYM.get(x[1], T.get(x[1], '·'))) if x[0] == 'c' else ' ' if x[1] == 0xA0 else '' for x in t[:end])
    out.append((j, ab, s))
print(f'{phnum} segments at {[hex(s) for s in SEG]}; slots by segment {segs}; strings without end op: {bad}')
for j, ab, s in out:
    # a fixed handful of slots printed for eyeballing (the choice of these ten is not significant)
    if j in (37, 47, 50, 54, 64, 183, 204, 221, 236, 241): print(j, 'seg', ab, s[:90])
sys.exit(1 if bad else 0)
