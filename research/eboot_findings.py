"""Research tool (not run by the build): re-derive, from the original program, the three facts the first program patches
rest on. The build uses the resulting constants directly; run this to see where they come from, or to test another
dump of the program. See docs/RESEARCH.md §4, §5.

Reads: decrypted_eboot/ULJM05030_EBOOT.BIN (the original program as a plain ELF) and the PSP ISO (tools/inputs.py).
Needs capstone and pycdlib. Writes nothing; prints three lines.
Addresses: vaddr = file offset - 0x80 (the code section starts at vaddr 0x40 / file offset 0xC0).

 1. DAT file table. The game opens its data files by disc position, not by name: at file offset 0x247A54 there are
    204 entries of (u32 LBA, u32 size, u32 0), one per DAT/*.BIN. Shown by matching each entry against the ISO
    directory. This is why the packer keeps files in place and rewrites this table when one must move.
 2. Text draw loop. 'sltiu ..., 0x372' at vaddr 0x3C814 is the test "is this code a glyph" (codes from 0x372 up are
    control codes: PS1 0x84 + 0x2EE), and the only place a 12-pixel advance is added to the pen position
    ('addiu a0,a0,0xc' followed by a store to +0x10) is 0x3C98C. That instruction is what the variable-width-font
    patch replaces.
 3. Code cave. 0x22691C-0x226BB0, a block of maths library routines, is unreachable: it is not reached by control
    flow from any jal / j target, from any word in the file that looks like a code address, or from any lui + low-half
    pair, and it contains no relocation entries. The variable-width code and its width table live there."""
import struct, pycdlib, capstone
E = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'tools')); import inputs as _IN
ISO = _IN.PSP                    # PSP base image: tools/inputs.py (PSP_ISO=psn|umd|path)
# 1 ---------------------------------------------------------------
iso = pycdlib.PyCdlib(); iso.open(ISO); bylba = {}
for c in iso.list_children(iso_path='/PSP_GAME/USRDIR/DAT'):
    if c.is_file(): bylba[c.extent_location()] = c.data_length
# ok(o): the 12 bytes at file offset o are (LBA, size, 0) of a real file in the DAT directory
ok = lambda o: (lambda l, s, z: l in bylba and bylba[l] == s and z == 0)(*struct.unpack_from('<III', E, o))
n = 0
while ok(0x247A54 + 12*n): n += 1
print(f'1. file table at 0x247A54: {n} valid entries (expected 204)')
# 2 ---------------------------------------------------------------
# the code, disassembled from vaddr 0 (file offset 0x80) to 0x230BE0, the end of the code as used here
TEXT = E[0x80:0x80 + 0x230BE0]
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN); md.skipdata = True
ins = [(i.address, i.mnemonic, i.op_str) for i in md.disasm(TEXT, 0)]
print('2. draw-loop char test:', [hex(a) for a, m, o in ins if m == 'sltiu' and o.endswith('0x372')],
      '| advance-by-12 sites:', [hex(a) for k, (a, m, o) in enumerate(ins)
                                 if m == 'addiu' and o == '$a0, $a0, 0xc' and ins[k+1][1] == 'sh' and '0x10(' in ins[k+1][2]])
# 3 ---------------------------------------------------------------
# entries = every address execution could start from: the entry at 0x40, jump / call targets, any word in the file
# that looks like a code address, and every address built by a lui + addiu / ori pair
END = 0x230BE0; I = {a: (m, o) for a, m, o in ins}
entries = {0x40}
for a, m, o in ins:
    if m in ('jal', 'j'):
        try: entries.add(int(o, 16))
        except ValueError: pass
for x in struct.unpack_from(f'<{len(E)//4}I', E[:len(E)//4*4]):
    if 0x40 <= x < END and x % 4 == 0: entries.add(x)
lui = {}
for a, m, o in ins:
    p = o.split(', ')
    try:
        if m == 'lui': lui[p[0]] = int(p[1], 16) << 16
        elif m in ('addiu', 'ori') and len(p) == 3 and p[1] in lui:
            t = (lui[p[1]] + int(p[2], 16)) & 0xFFFFFFFF if m == 'addiu' else lui[p[1]] | int(p[2], 16)
            if 0x40 <= t < END: entries.add(t)
    except ValueError: pass
# flood fill along control flow: follow branches, stop after an unconditional b / j / jr (plus its delay slot)
reach = set(); stack = list(entries)
while stack:
    a = stack.pop()
    while a in I and a not in reach:
        reach.add(a); m, o = I[a]
        if m.startswith('b') and m != 'break':
            try: stack.append(int(o.split(', ')[-1], 16))
            except ValueError: pass
            if m == 'b': reach.add(a + 4); break
        if m in ('j', 'jr'): reach.add(a + 4); break
        a += 4
S, Eend = 0x22691C, 0x226BB0
# offsets of the code relocation entries (.rel.text: file offset 0x325018, 0x9F3D8 bytes, 8 bytes per entry)
rel = [struct.unpack_from('<II', E, 0x325018 + 8*k)[0] for k in range(0x9F3D8 // 8)]
dead = all(a not in reach for a in range(S, Eend, 4))
print(f'3. cave 0x{S:X}-0x{Eend:X}: unreachable={dead}, relocations inside={sum(S <= r < Eend for r in rel)}')
