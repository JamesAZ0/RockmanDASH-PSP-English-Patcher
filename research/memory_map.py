"""Research tool (not run by the build; read-only): where things live in the game's PS1-style RAM
(0x80000000-0x80200000) on the PSP. It was made to find room for the English text: 16-bit English does not fit the
buffers the Japanese text is loaded into, so the buffers had to move (docs/RESEARCH.md §6).

Reads:  the PSP ISO (tools/inputs.py) and decrypted_eboot/ULJM05030_EBOOT.BIN. Needs pycdlib and capstone.
Writes: logs/memory_map.md (also printed).

1. Load regions: every container entry of every DAT/*.BIN that has a load address (entry header +0x0C; +0x04 = size),
   grouped by (address, file type), with the largest size seen.
2. The PSP port keeps the PS1's 2 MB of RAM as one array inside its own data. Code builds a PS1 address p as the
   constant 0x2D2900 + (p - 0x80000000), found by matching lui/addiu constants against the known load addresses (MSG
   0x80157000, IDX 0x8015C000, EBD 0x8016C000, ...). NOTE: that constant is relative to segment 1 (.data, vaddr
   0x245200) - the instructions carry relocations - so the absolute vaddr of PS1 address 0x80000000 is 0x517B00. The
   report's heading calls 0x2D2900 a vaddr; read it as the segment-1-relative value (corrected 2026-09-29).
3. Direct code references (lui + low-half pairs, or lui + a load/store offset) into the gaps between load regions.
4. Where the stage text base 0x80157000 is built in code.

Caution: a gap with no direct code reference is not proven free; memory can be reached through computed pointers.
The free areas actually used were confirmed with save states (research/savestate_check.py).

Usage: python3 research/memory_map.py"""
import io, struct, collections, pycdlib, capstone
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'tools')); import inputs as _IN
ISO = _IN.PSP                    # PSP base image: tools/inputs.py (PSP_ISO=psn|umd|path)
# B = the constant code uses for PS1 address 0x80000000 (segment-1 relative, see the docstring)
E = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read(); B = 0x2D2900
iso = pycdlib.PyCdlib(); iso.open(ISO); R = collections.defaultdict(lambda: [0, set()])
for c in iso.list_children(iso_path='/PSP_GAME/USRDIR/DAT'):
    bn = c.file_identifier().decode().split(';')[0]
    if not c.is_file() or not bn.upper().endswith('.BIN'): continue
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path='/PSP_GAME/USRDIR/DAT/' + bn); d = b.getvalue()
    # container entries: a 0x800-byte header on a sector boundary with the entry path ("..\...") at +0x40
    for off in range(0, len(d) - 0x7FF, 0x800):
        name = d[off+0x40:off+0x80].split(b'\0')[0]
        if name.startswith(b'..\\') and all(32 <= x < 127 for x in name):
            size, addr = struct.unpack_from('<I', d, off+4)[0], struct.unpack_from('<I', d, off+12)[0]
            if addr >= 0x80000000:
                r = R[(addr, name.rsplit(b'.', 1)[-1].decode().upper())]; r[0] = max(r[0], size); r[1].add(bn)
# T: constant -> code addresses that build it. A lui sets the upper half; a following addiu on that register, or a
# load / store using it as base, supplies the signed lower half. Code = file 0xC0.., vaddr 0x40..
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN); md.skipdata = True
T = collections.defaultdict(list); lui = {}
for i in md.disasm(E[0xC0:0xC0 + 0x230BA0], 0x40):
    p = i.op_str.split(', ')
    try:
        if i.mnemonic == 'lui': lui[p[0]] = int(p[1], 16) << 16; continue
        if i.mnemonic == 'addiu' and len(p) == 3 and p[1] in lui:
            v = int(p[2], 16); v -= 0x10000 if v >= 0x8000 else 0; T[(lui[p[1]] + v) & 0xFFFFFFFF].append(i.address)
        elif '(' in p[-1]:
            o, r = p[-1][:-1].split('(')
            if r in lui: T[(lui[r] + (-int(o[1:], 16) if o.startswith('-') else int(o, 16))) & 0xFFFFFFFF].append(i.address)
    except ValueError: pass
out = ['# PS1-style RAM map (PSP)', '', f'Native base of 0x80000000: vaddr 0x{B:X}.', '', '## Load regions (max size over all files)', '',
       '| Start | End | Type | Max size | Files |', '|---|---|---|---|---|']
regs = sorted(R.items())
for (a, t), (s, bins) in regs: out.append(f'| 0x{a:08X} | 0x{a+s:08X} | {t} | {s} | {len(bins)} |')
out += ['', '## Code references into gaps between load regions', '']
# gaps = from the end of each load region to the start of the next, dropping any that another region overlaps
ends = sorted((a + s for (a, _), (s, _) in regs)); starts = sorted(a for (a, _) in R)
gaps = [(e, min([x for x in starts if x >= e], default=0x80200000)) for e in ends]
gaps = sorted({g for g in gaps if g[1] > g[0] and not any(a < g[1] and a + s > g[0] for (a, _), (s, _) in regs)})
for lo, hi in gaps:
    refs = sorted(t for t in T if B + lo - 0x80000000 <= t < B + hi - 0x80000000)
    out.append(f'- gap 0x{lo:08X}-0x{hi:08X} ({hi-lo} bytes): ' + (', '.join(f'0x{t-B+0x80000000:08X} (code {",".join(hex(x) for x in T[t][:3])})' for t in refs[:12]) or 'no direct code references'))
out += ['', '## Stage text base 0x80157000 built at', '', ', '.join(hex(x) for x in T.get(B + 0x157000, [])), '']
open('logs/memory_map.md', 'w').write('\n'.join(out)); print('\n'.join(out))
