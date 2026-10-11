"""Fold the extra EBOOT segments back into Sony's two-segment layout (2026-09-30, for real PSPs).
Reference: docs/RESEARCH.md §5.
build_sysmsg.py adds a 3rd PT_LOAD (English system messages, banner lists) and patch_eboot_voice.py a 4th (English
voice paths) plus a new relocation section. PPSSPP accepts that; on a PSP Go with ARK-5 the 3-segment EBOOT
booted but crashed at the title screen, and the 4-segment one failed with 80020148 (unsupported PRX type). With two
segments the plain, unsigned program runs there.
This keeps the ELF exactly as Sony's (program headers at 0x34, 2 PT_LOADs, the original section-header table and
relocation sections) and instead extends segment 1: its file image becomes .data + .bss (as zeros) + the extra
segments at their own addresses, so every address the extra data had is unchanged (segment 2/3 vaddr - seg-1 vaddr
= its seg-1 offset). The file is rebuilt compactly (segment 1 at Sony's .data offset, then the non-loaded sections and the
section-header table in Sony's order); with no extra segments the result is Sony's BOOT.BIN byte for byte. Relocations:
ofs_base/addr_base 2 or 3 -> 1, offsets and stored words rebased (R_MIPS_32 only; asserted). The extra relocation
section's entries are appended to .rel.data. The file grows by ~5.4 MB
(the .bss zeros).
Proof that nothing changes for the game: tools/checks/compare_loaded.py loads the unflattened and the flattened file
the way the PSP loader does (segments + every relocation) and compares the memory images; build.py runs it on every
build.
Usage: python3 tools/flatten_eboot.py in.elf out.elf    (also used as a module by pack_inplace.py, for every build
unless its internal argument --no-flat is given)"""
import sys, struct
def flatten(d):
    d = bytearray(d)
    # ELF header: e_phoff 0x1C, e_shoff 0x20, e_phnum 0x2C, e_shnum 0x30. ph = program headers (8 words: type, offset,
    # vaddr, paddr, filesz, memsz, flags, align); sh = section headers (10 words: name, type, flags, addr, offset, size,
    # link, info, addralign, entsize). Expected: only PT_LOADs, segment 0 at vaddr 0 and segment 1 at 0x245200.
    phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
    shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
    ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
    sh = [list(struct.unpack_from('<10I', d, shoff + 40 * k)) for k in range(shnum)]
    assert all(p[0] == 1 for p in ph) and ph[0][2] == 0 and ph[1][2] == 0x245200, 'unexpected layout'
    # V = segment vaddrs, S1 = segment 1 vaddr; img = the new file image of segment 1 (starts as its current bytes)
    V = [p[2] for p in ph]; S1 = V[1]
    img = bytearray(d[ph[1][1]:ph[1][1] + ph[1][4]])
    if phnum > 2: img += bytes(ph[1][5] - ph[1][4])   # .bss as file zeros only when data must follow it
    for p in ph[2:]:
        o = p[2] - S1; assert o >= len(img), 'extra segment overlaps segment 1'
        img += bytes(o - len(img)) + d[p[1]:p[1] + p[4]] + bytes(p[5] - p[4])
    if phnum > 2:
        while len(img) % 16: img += b'\0'
    def word_at(base, off):          # (buffer, index) of a word in the new layout
        return (d, 0x80 + off) if base == 0 else (img, off)
    # relocation sections have the PSP's own section type 0x700000A0; .rel.data is the one at file offset 0x3CF6D0.
    # Sony's file has 34 sections: a section index >= 34 is the relocation section added by patch_eboot_voice.py.
    # Entry = (offset, info); info = type | offset-base segment << 8 | address-base segment << 16.
    rels = [k for k, s in enumerate(sh) if s[1] == 0x700000A0]
    reld = next(k for k in rels if sh[k][4] == 0x3CF6D0)
    orig_shnum = 34; extra_entries = []
    for k in rels:
        s = sh[k]
        for j in range(s[5] // 8):
            at = s[4] + 8 * j; o, i = struct.unpack_from('<II', d, at)
            t, ob, ab = i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF
            # an entry that involves only segments 0/1 is unchanged (kept, or collected if it is in the added section)
            if ob < 2 and ab < 2:
                if k >= orig_shnum: extra_entries.append((o, i))
                continue
            assert t == 2, ('non R_MIPS_32 relocation into an extra segment', hex(i))
            # the relocated word lies in an extra segment: its offset becomes segment-1 relative.
            # it points into an extra segment: the stored word (segment-relative) is rebased to segment 1 as well.
            if ob >= 2: o = o + V[ob] - S1; ob = 1
            if ab >= 2:
                buf, w = word_at(ob, o); struct.pack_into('<I', buf, w, struct.unpack_from('<I', buf, w)[0] + V[ab] - S1); ab = 1
            i = t | (ob << 8) | (ab << 16)
            if k >= orig_shnum: extra_entries.append((o, i))
            else: struct.pack_into('<II', d, at, o, i)
    # rebuild the file compactly, in Sony's order: header + segment 0 (unchanged), the new segment-1 image at the
    # same offset as Sony's .data, then the non-loaded sections (relocations, .shstrtab, .comment) and the
    # section-header table in their original order and alignment; the extra relocation entries extend .rel.data.
    # With no extra segments this reproduces Sony's BOOT.BIN byte for byte (and drops the dump's 341-byte tail).
    add = b''.join(struct.pack('<II', o, i) for o, i in extra_entries)
    # S1OFF: file offset of segment 1 in Sony's file (0x80 + 0x245200). items = everything that follows segment 1 in the
    # file: the sections that are not loaded (type not NOBITS 8, no ALLOC flag 2, non-empty) and the section headers,
    # sorted by their original position (0x324AB8 = Sony's e_shoff, used when an earlier step moved the table).
    S1OFF = 0x245280; assert ph[0][1] == 0x80 and ph[0][4] == S1 and ph[1][1] == S1OFF
    items = [(sh[k][4], 'sec', k) for k in range(orig_shnum) if sh[k][1] != 8 and sh[k][2] & 2 == 0 and sh[k][5]]
    items.append((shoff if shnum == orig_shnum else 0x324AB8, 'shtab', None)); items.sort()
    out = bytearray(d[:S1OFF]) + img
    def align(n):
        while len(out) % n: out.append(0)
    newsh = [list(x) for x in sh[:orig_shnum]]   # the extra relocation section is folded into .rel.data
    for _, kind, k in items:
        if kind == 'shtab': align(4); shtab_at = len(out); out += bytes(40 * orig_shnum); continue
        align(max(sh[k][8], 1)); newsh[k][4] = len(out)
        out += d[sh[k][4]:sh[k][4] + sh[k][5]]
        if k == reld: out += add; newsh[k][5] += len(add)
    data_sec = next(k for k in range(orig_shnum) if sh[k][3] == S1 and sh[k][1] == 1)
    newsh[data_sec][4] = S1OFF
    # segment 1: file size = the new image; memory size at least that (unchanged when nothing was added)
    ph1 = list(ph[1]); ph1[4] = len(img); ph1[5] = max(ph[1][5], len(img))
    for k, p in enumerate([ph[0], ph1]): struct.pack_into('<8I', out, 0x34 + 32 * k, *p)
    for k, x in enumerate(newsh): struct.pack_into('<10I', out, shtab_at + 40 * k, *x)
    struct.pack_into('<I', out, 0x1C, 0x34); struct.pack_into('<H', out, 0x2C, 2)
    struct.pack_into('<I', out, 0x20, shtab_at); struct.pack_into('<H', out, 0x30, orig_shnum)
    return bytes(out)
if __name__ == '__main__':
    out = flatten(open(sys.argv[1], 'rb').read()); open(sys.argv[2], 'wb').write(out); print('flattened ->', sys.argv[2], len(out))
