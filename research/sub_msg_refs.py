"""Research tool (not run by the build; read-only): find every code reference to the base of the pause / sub-screen
text buffer, PS1 address 0x801F2000, where STFF_FE.MSG is loaded. The first of the text-buffer searches; the general
version for any address is research/msg_base_refs.py.

Background (docs/RESEARCH.md §6): the PSP port keeps PS1 RAM as an array in its data segment: PS1 address p is at
native vaddr 0x517B00 + (p - 0x80000000). Code builds it as a constant relative to segment 1 (vaddr 0x245200), so for
0x801F2000 the instructions are 'lui reg, 0x4C' and a second one with low half 0x4900 (0x4C4900 + 0x245200 = 0x709B00).

Method: take all relocations of type 6 (R_MIPS_LO16) against segment 1 whose instruction has the immediate 0x4900,
follow each one's base register back through straight-line code and branch sources to the instructions defining it,
accept a site only if every definition is 'lui reg, 0x4C', and check that none of those luis feeds any other LO16
instruction (a conflict would make the lui unsafe to change).
Result (2026-09-29): 54 LO16 sites, 38 lui instructions, no conflicts. The lists became the pause-screen entry of
tools/memmap.py SITES (one pair, which loads SUPPORT.EBD at the same address rather than text, was later taken out).

Reads decrypted_eboot/ULJM05030_EBOOT.BIN; needs capstone. Prints counts and the LO / HI site lists; writes nothing.
Usage: python3 research/sub_msg_refs.py"""
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
# L = LO16 relocations against segment 1 (type 6, address base 1) whose instruction immediate is 0x4900
L=[]
for a,i in rel.items():
    if i&0xff!=6 or (i>>16)&0xff!=1 or a not in ins: continue
    m,o=ins[a]; imm=o.split(', ')[-1]
    try: v=int(imm.split('(')[0],16) if '(' in imm else int(imm,16)
    except ValueError: continue
    if v==0x4900: L.append(a)
# good = sites whose base register is only ever set by 'lui reg, 0x4c'; bad = sites where only some definitions are; H
# = the luis involved
good=[];bad=[];H=set()
for a in L:
    m,o=ins[a]; r=base_reg(m,o); ds=defs(a,r)
    his=[d for d in ds if d[1]=='lui']
    if ds and all(d[1]=='lui' and d[2].endswith(', 0x4c') for d in ds): good.append(a); H|={d[0] for d in ds}
    elif any(d[1]=='lui' and d[2].endswith(', 0x4c') for d in ds): bad.append((hex(a),[(hex(x),y,z) for x,y,z in ds]))
print('LO16 imm 0x4900:',len(L),'-> target 0x801F2000 via lui 0x4c only:',len(good),'mixed:',bad[:5],'luis',len(H))
# conflict: other LO16 users of each lui
conf=[]
for h in H:
    reg=ins[h][1].split(', ')[0]
    for a,i in rel.items():
        if i&0xff==6 and a in ins and a not in good and base_reg(*ins[a])==reg and 0<a-h<0x800:
            if (h,ins[h][0],ins[h][1]) in defs(a,reg): conf.append((hex(h),hex(a),ins[a]))
print('conflicts',conf)
print('LO', [hex(x) for x in sorted(good)]); print('HI', [hex(x) for x in sorted(H)])
