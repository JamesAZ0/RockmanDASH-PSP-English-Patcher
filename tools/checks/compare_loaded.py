"""Build check (run by build.py) and shared loader: load two program files (plain ELFs) the way the PSP / PPSSPP module
loader does, and compare the resulting memory images word by word.

build.py runs it on build/test/<tag>/EBOOT_unflat.BIN and EBOOT_plain.BIN, i.e. the program before and after
tools/flatten_eboot.py. The patch steps add program segments (English system messages, voice path tables, ...); a
real PSP did not accept a program with more than Sony's two segments (it crashed with three and refused four with error
80020148), so flatten_eboot.py folds the added data back into segment 1 and rewrites the relocations to match. That
rewrite must change nothing the game can see, and this is the proof: identical memory after loading. See
docs/RESEARCH.md §5.

How loading is modelled (load()):
  - every program header's file bytes are copied to its vaddr; memory beyond the file bytes (.bss) stays zero;
  - every relocation section of type 0x700000A0 (the PSP's own format) is applied. An entry is two u32, (offset,
    info): info & 0xFF = type, (info >> 8) & 0xFF = index of the segment the offset is relative to,
    (info >> 16) & 0xFF = index of the segment whose load address is added;
  - types handled: 2 R_MIPS_32, 4 R_MIPS_26 (jump targets), 5 R_MIPS_HI16 and 6 R_MIPS_LO16 (a lui is completed by
    the LO16 entry that follows it); other types are ignored;
  - BASE 0x08804000 is the address the game module gets in PSP memory (as PPSSPP save states show).
load() returns (memory indexed by vaddr, number of relocations applied, number of segments).

Other checks reuse the loader: verify_savetext, verify_subtitles, verify_ps1_title, verify_wide_hud and audit_eboot
read this file as text and execute everything above the command-line part at the bottom. Keep that part last, and
keep everything above it free of side effects.

Reads the two files named on the command line; writes nothing.
Failure (exit 1, stops the build): any differing word, or different image sizes - the flattened program would not
behave like the unflattened one.

Usage: python3 tools/checks/compare_loaded.py a.elf b.elf"""
import sys, struct
BASE = 0x08804000
def load(p):
    d = open(p, 'rb').read()
    # ELF header: e_phoff at 0x1C, e_phnum at 0x2C, e_shoff at 0x20, e_shnum at 0x30
    phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
    shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
    # program header (32 bytes) as 8 u32: p[1] file offset, p[2] vaddr, p[4] size in the file, p[5] size in memory
    ph = [struct.unpack_from('<8I', d, phoff + 32 * k) for k in range(phnum)]
    mem = bytearray(max(p[2] + p[5] for p in ph))
    for p in ph: mem[p[2]:p[2] + p[4]] = d[p[1]:p[1] + p[4]]
    # V = segment vaddrs; hi = pending HI16 sites waiting for their LO16
    V = [p[2] for p in ph]; n = 0; hi = []
    for k in range(shnum):
        # section header (40 bytes) as 10 u32: s[1] type, s[4] file offset, s[5] size
        s = struct.unpack_from('<10I', d, shoff + 40 * k)
        if s[1] != 0x700000A0: continue
        for j in range(s[5] // 8):
            o, i = struct.unpack_from('<II', d, s[4] + 8 * j); t, ob, ab = i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF
            # a = vaddr of the word to fix; rel = load address of the segment the value refers to; w = the word as
            # stored
            a = V[ob] + o; rel = BASE + V[ab]; w = struct.unpack_from('<I', mem, a)[0]
            # R_MIPS_32: add the address. R_MIPS_26: the 26-bit jump field holds target / 4
            if t == 2: w = (w + rel) & 0xFFFFFFFF
            elif t == 4: w = (w & 0xFC000000) | ((((w & 0x03FFFFFF) << 2) + rel) >> 2 & 0x03FFFFFF)
            # HI16 (lui): cannot be finished until the low half is known, so it is remembered
            elif t == 5: hi.append(a); continue
            elif t == 6:
                # LO16: its signed low half completes every pending lui: full = (hi16 << 16) + lo + address, and the
                # lui gets the upper half rounded for the sign of the low half (+0x8000); then the low 16 bits go into
                # this instruction
                lo = struct.unpack_from('<h', mem, a)[0]
                for h in hi:
                    hw = struct.unpack_from('<I', mem, h)[0]; full = ((hw & 0xFFFF) << 16) + lo + rel
                    struct.pack_into('<I', mem, h, (hw & 0xFFFF0000) | (((full + 0x8000) >> 16) & 0xFFFF))
                hi = []; w = (w & 0xFFFF0000) | ((lo + rel) & 0xFFFF)
            else: continue
            struct.pack_into('<I', mem, a, w); n += 1
    return mem, n, len(ph)
a, na, pa = load(sys.argv[1]); b, nb, pb = load(sys.argv[2])
# compare word by word over the common length; different lengths are a failure too
n = min(len(a), len(b)); diff = sum(1 for k in range(0, n, 4) if a[k:k+4] != b[k:k+4])
print(f'{sys.argv[1]}: {pa} segments, {na} relocations; {sys.argv[2]}: {pb} segments, {nb} relocations; '
      f'memory {len(a)} vs {len(b)} bytes; differing words: {diff}')
sys.exit(1 if diff or len(a) != len(b) else 0)
