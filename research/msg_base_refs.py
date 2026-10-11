"""Research tool (not run by the build; read-only): find every code site that builds the address of a text buffer in
the PS1-style RAM, so that the buffer can be moved by changing instruction immediates only. This is the general form
of research/sub_msg_refs.py; its output is recorded as tools/memmap.py SITES, which tools/patch_eboot.py applies.

Background (docs/RESEARCH.md §6): the PSP port keeps PS1 RAM as an array in its data segment and builds a PS1 address
p as a segment-1-relative constant (memmap.rel_const: 0x2D2900 + (p - 0x80000000)) with a 'lui reg, %hi' and a second
instruction carrying %lo (addiu / ori, or the offset of a load / store). Both instructions have relocation entries.

Method:
  - take every relocation of type 6 (R_MIPS_LO16) against segment 1 whose instruction has the address's %lo;
  - trace that instruction's base register backwards (straight-line code, and into every branch that jumps there)
    to all instructions that define it;
  - a site counts only if EVERY definition is 'lui reg, %hi' of the same address ('mixed' sites, where only some
    are, are listed separately and need a human look);
  - 'conflicts' = other LO16 instructions that use one of those luis with a different low half: changing the lui
    would break them.
Results when this was run (2026-09-29): 0x80157000 (stage text) 1 lo / 1 hi; 0x801E4000 (support car) 24 / 24;
0x801F2000 (pause screens) 54 / 38; no mixed sites, no conflicts. One of the 0x801F2000 pairs loads SUPPORT.EBD
rather than text and is deliberately left out of memmap.SITES.

Reads decrypted_eboot/ULJM05030_EBOOT.BIN; needs capstone. Prints the LO and HI site lists; writes nothing.
Usage: python3 research/msg_base_refs.py 80157000 801E4000 801F2000"""

import struct,capstone,collections
E=open('decrypted_eboot/ULJM05030_EBOOT.BIN','rb').read()
md=capstone.Cs(capstone.CS_ARCH_MIPS,capstone.CS_MODE_MIPS32+capstone.CS_MODE_LITTLE_ENDIAN); md.skipdata=True
# ins: vaddr -> (mnemonic, operands) for the whole code section (file offset 0xC0, vaddr 0x40, 0x230BA0 bytes)
ins={i.address:(i.mnemonic,i.op_str) for i in md.disasm(E[0xC0:0xC0+0x230BA0],0x40)}
# rel: offset -> info for every code relocation (.rel.text: file offset 0x325018, 0x9F3D8 bytes; 8-byte entries). info
# & 0xFF = type (6 = LO16), (info >> 16) & 0xFF = segment whose address is added (1 = .data)
rel={}
for k in range(0x9F3D8//8):
    o,i=struct.unpack_from('<II',E,0x325018+8*k); rel[o]=i
BR=('b','beq','bne','beqz','bnez','bgez','bltz','bgtz','blez','beql','bnel','beqzl','bnezl','bgezl','bltzl','bgtzl','blezl','bgezal','bltzal')
UNC=('j','b','jr')
# src: branch / jump target -> the instructions that jump there
src=collections.defaultdict(list)
for a,(m,o) in ins.items():
    if m in BR or m=='j':
        try: src[int(o.split(', ')[-1],16)].append(a)
        except ValueError: pass
# dest: the register an instruction writes (its first operand), or None for stores, branches, jumps and nop
def dest(m,o):
    if m in ('sb','sh','sw','swc1','swl','swr','nop','break','syscall','jr','j','jal','jalr') or m in BR: return None
    p=o.split(', '); return p[0] if p else None
# preds: the instructions that can execute immediately before a: the one above it (unless that one is the delay slot
# of an unconditional jump), and the delay slot of every branch that targets a
def preds(a):
    ps=[]
    p=a-4
    if p in ins:
        pm=ins[p][0]; pp=p-4
        # if p is itself a jump, a is its delay slot and p still precedes a, so p is kept in that case
        if not (pp in ins and ins[pp][0] in UNC):   # p is a delay slot of unconditional jump -> control goes elsewhere
            ps.append(p)
        elif ins[pp][0] in UNC and False: pass
    for s in src.get(a,[]): ps.append(s+4)   # delay slot then branch target
    return ps
# defs: walk backwards from a (at most `limit` instructions) and collect every instruction that defines reg
def defs(a,reg,limit=800):
    seen=set(); out=set(); stack=[p for p in preds(a)]
    while stack and len(seen)<limit:
        x=stack.pop()
        if x in seen or x not in ins: continue
        seen.add(x); m,o=ins[x]
        if dest(m,o)==reg: out.add((x,m,o)); continue
        stack.extend(preds(x))
    return out
# base_reg: the register a %lo instruction adds to - the source of addiu / ori, or the base of a load / store
def base_reg(m,o):
    p=o.split(', ')
    if m in ('addiu','ori'): return p[1]
    if '(' in p[-1]: return p[-1].split('(')[1][:-1]

import sys; sys.path.insert(0, "tools"); import memmap as MM
def refs(target):
    """LO16 sites building `target` whose base register is only ever defined by the matching lui; plus those luis and
    any other LO16 user of the same luis (conflicts)."""
    hi, lo = MM.hi_lo(MM.rel_const(target))
    # L = LO16 relocations against segment 1 whose instruction immediate equals the target's %lo
    L = [a for a, i in rel.items() if i & 0xff == 6 and (i >> 16) & 0xff == 1 and a in ins
         and struct.unpack_from('<I', E, 0xC0 + a - 0x40)[0] & 0xffff == lo]
    good = []; H = set(); unclear = []
    for a in L:
        m, o = ins[a]; r = base_reg(m, o); ds = defs(a, r)
        if ds and all(d[1] == 'lui' and int(d[2].split(', ')[-1], 16) == hi for d in ds): good.append(a); H |= {d[0] for d in ds}
        elif any(d[1] == 'lui' and int(d[2].split(', ')[-1], 16) == hi for d in ds): unclear.append(hex(a))
    conf = []
    for h in H:
        reg = ins[h][1].split(', ')[0]
        for a, i in rel.items():
            if i & 0xff == 6 and a in ins and a not in good and base_reg(*ins[a]) == reg and 0 < a - h < 0x800:
                if (h, ins[h][0], ins[h][1]) in defs(a, reg): conf.append((hex(h), hex(a)))
    return sorted(good), sorted(H), unclear, conf
if __name__ == '__main__':
    for t in [int(x, 16) for x in sys.argv[1:]]:
        g, h, u, c = refs(t)
        print('%08X: LO %d, HI %d, mixed %s, conflicts %s' % (t, len(g), len(h), u, c))
        print('  LO', [hex(x) for x in g]); print('  HI', [hex(x) for x in h])
