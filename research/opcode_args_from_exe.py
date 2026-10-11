"""Research tool (not run by the build): re-derive the dialogue control codes' argument lengths from the US executable.
The result is already stored in script/opcode_args_exe.json, which tools/msgtool.py loads; this script recomputes it
and reports any mismatch with that file. See docs/RESEARCH.md §3.

Usage: python3 research/opcode_args_from_exe.py      (needs: pip install capstone; run tools/extract.py first)
Reads extracted/ps1/ROCK_NEO.EXE and script/opcode_args_exe.json; writes nothing; prints one line.

How it works:
- ROCK_NEO.EXE is a PS-X EXE: the header at 0x10 gives pc, gp, the load address of the code (0x80010000) and its
  size; the code itself starts at file offset 0x800.
- The text engine is at 0x80053CD4. Bytes below 0x84 are glyphs; bytes 0x84-0xED are control codes, dispatched
  through two handler tables indexed by byte * 4:
    table A 0x8008A91C (draw pass, text pointer kept at state+0x6C)
    table B 0x8008AAC4 (scan pass, text pointer kept at state+0x14)
- For each handler we find the constant added to the text pointer before it is stored back:
  that constant = 1 + number of argument bytes. If both passes agree on one value, it is taken.
- Handlers that push a return address (sub-string calls) or loop are resolved by hand from their disassembly;
  those are listed in MANUAL with the reason.
- Limits: the handlers tell how far the US engine advances, not how the data is laid out on the PSP. E2 / E4 advance
  by 2 in the scan pass but carry 4 argument bytes in the data of both discs, and B9 / CE / E9 are laid out
  differently on the PSP; tools/msgtool.py overrides those, and tools/checks/verify_msg_args.py checks the result
  against the Japanese data in every build."""
import struct, json, sys, capstone
EXE = 'extracted/ps1/ROCK_NEO.EXE'
d = open(EXE, 'rb').read()
# PS-X EXE header at 0x10: initial pc, gp, load address of the code, its size; the code follows the 0x800-byte header
pc, gp, taddr, tsize = struct.unpack_from('<IIII', d, 0x10)
code = d[0x800:0x800 + tsize]
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN); md.skipdata = True
ins = list(md.disasm(code, taddr)); idx = {i.address: k for k, i in enumerate(ins)}
# rd: u32 at a PS1 address
def rd(a): return struct.unpack_from('<I', d, 0x800 + a - taddr)[0]

def incs(fa, field, seen=None):
    """Set of constants added to `field(a0)` before it is stored back (follows jal, handles delay slots)."""
    seen = set() if seen is None else seen
    if fa in seen or fa not in idx: return set()
    seen.add(fa); loaded = {}; res = set(); stop = False
    # scan at most 500 instructions of the handler: track registers loaded from the text-pointer field and constants
    # added to them, record the constant when such a register is stored back, follow calls, stop after "jr ra" and its
    # delay slot
    for i in ins[idx[fa]: idx[fa] + 500]:
        m = i.mnemonic; ops = i.op_str.split(', ')
        if m == 'lw' and len(ops) == 2 and ops[1].startswith(field + '('): loaded[ops[0]] = 0
        elif m == 'addiu' and len(ops) == 3 and ops[1] in loaded and isinstance(loaded[ops[1]], int):
            loaded[ops[0]] = loaded[ops[1]] + int(ops[2], 16)
        elif m == 'move' and ops[1] in loaded: loaded[ops[0]] = loaded[ops[1]]
        elif m == 'sw' and ops[1].startswith(field + '(') and ops[0] in loaded: res.add(loaded[ops[0]])
        elif m == 'jal': res |= incs(int(ops[0], 16), field, seen)
        if stop: break
        if m == 'jr' and i.op_str == '$ra': stop = True
    return res

MANUAL = {  # opcode: (arg bytes, reason)
    0x90: (1, 'pushes return address ptr+2 (0x80054A04)'),
    0x91: (0, 'pops return address'),
    0x93: (2, 'DECOR; dispatches via a second table; 2 args per DashEditor and all data'),
    0x97: ('var', 'MULTI: type byte + one byte per choice; scan pass 0x80055304 skips 2 + state+0x72, which SEL 0x96/AD/B7/D7/DD add to, CE/E9 set and CLEAR/MULTI/... reset (research/multi_choice_count.py). 0xED does not count.'),
    0xBF: (2, 'JUMP: scan pass adds 3; draw pass branches (shares handler with D5)'),
    0xC1: (0, 'pushes ptr+1 then jumps to a string table (0x80057708)'),
    0xC7: (0, 'pushes ptr+1 (0x80057A94)'), 0xCF: (0, 'same handler as C7'),
    0xC9: (1, 'pushes ptr+2 (0x80057D60)'), 0xD0: (1, 'pushes ptr+2 (0x80057B24)'),
    0xD4: (4, 'pushes ptr+5 (0x80058740)'), 0xD5: ('list', 'branch list terminated by 0xFF (data ST05_00E 0x6D)'),
    0xDA: (2, 'pushes ptr+3 (0x80058CC8)'), 0xE0: (0, 'pushes ptr+1 (0x80059530)'),
    0xE1: (2, 'pushes ptr+3 (0x80059660)'), 0xE7: (1, 'pushes ptr+2 (0x80059E24)'),
    0xE8: ('var', 'same handler as MULTI'), 0xEA: ('var', 'same handler as MULTI'),
    # E2/E4: scan pass adds 2, but the data (STFF_FE blocks 07/24, both discs) has 4 argument bytes; tools/msgtool.py
    # overrides them to 4. Kept at the handler value here so the comparison with script/opcode_args_exe.json
    # still holds.
}
# the two handler tables (draw pass, scan pass); entry = 4 bytes per code
A, B = 0x8008A91C, 0x8008AAC4
out = {}
for c in range(0x84, 0xEE):
    if c == 0x86: continue                      # newline glyph
    if c in MANUAL: out[f'{c:02X}'] = MANUAL[c][0]; continue
    ia = incs(rd(A + 4*c), '0x6c') if rd(A + 4*c) else set()
    ib = incs(rd(B + 4*c), '0x14') if rd(B + 4*c) else set()
    s = {v for v in ia | ib if isinstance(v, int)}
    if len(s) == 1: out[f'{c:02X}'] = s.pop() - 1
# compare with the stored table; variable-length ops are compared as "var"; D5 (a list) is exempt
known = json.load(open('script/opcode_args_exe.json'))['args']
norm = lambda v: v if isinstance(v, int) else 'var'
mism = {k: (out.get(k), v) for k, v in known.items() if norm(out.get(k, 'missing')) != norm(v) and not (k == 'D5')}
print(f'derived {len(out)} opcodes; mismatches vs script/opcode_args_exe.json: {mism or "none"}')
