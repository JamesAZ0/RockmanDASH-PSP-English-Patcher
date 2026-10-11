"""PS1 title screen, program part: the US PS1 background behind the logo, the PS1 menu colours, and no Japanese title
calls. Part of `python build.py <tag> --localization=legends` (project decision, 2026-10-01); build.py passes the
internal argument `ps1` for legends and `psp` for text / audio. The textures are tools/build_ps1_title.py's part.
Runs after build_savetext.py (it needs segment 2, the data area build_sysmsg.py adds), in place on
build/eboot/ULJM05030_EBOOT_en.BIN.
Usage: python3 tools/patch_ps1_title.py ps1|psp   (internal argument, set by build.py)
Addresses below are virtual addresses in the program (file offset = address + 0x80 for the code segment).
  ps1: 1. Background: the PSP title (function 0x2248, after the logo) draws a white/blue gradient (0x2370-0x248C). That
          is replaced by the PS1's background (ROCK_NEO.EXE 0x800140BC-0x80014358): two textured quads from NTITLE3U
          (texels 0-160, the right one mirrored) over y 0-0xA0, a subtractive fade over y 0x90-0xA0 (draw mode
          tpage abr 2) and a gradient black -> (C0,FF,E0) over y 0xA2-0xF0, added to the same ordering-table slots
          (0x8C, 0x88) in the same order. The 5 primitives are constant templates (the values the PS1 library calls
          GetTPage/GetClut/SetDrawMode give; the PSP's 0x216518/0x216554/0x2165C0 are the same code) appended to
          segment 2; a short loop at 0x2370/0x240C copies each into the primitive buffer and calls AddPrim (0x21647C).
          Everything is reached PC-relative (bal; the OT pointer is segment 1 + 0x500800, as the old code's
          relocations say), so no relocation is added or changed: the old code's relocated words (0x2374, 0x23B0/B4,
          0x23F4, 0x2404/08, 0x2474, 0x2484/88) are left as they are and never executed (0x2374 is the bal delay
          slot: lui v0, harmless).
       2. Menu palette: PRESS START and the copyright line use palette 8 (clut x 0x80) instead of 0 (0x253C, 0x25F8),
          so palettes 0-7 can carry the PS1 menu colours (tools/build_ps1_title.py).
       3. Japanese title calls: the PRESS START screen queues two stereo voice clips (sounds 0x1C7+4k/0x1C8+4k at its
          300-frame counter start, 0x1C9+4k/0x1CA+4k at 240; k = 0-2 cycles each time the title is shown; e_title.vab
          program 6). The US PS1 has the same samples but never queues them (all six pairs were checked by ear: none
          belongs in the English title). Both branches are pointed past the queue calls:
          0x19A4 -> 0x1A78 (as after the first pair), 0x19AC -> 0x1A14 (the variant counter still advances).
          The three English title voices (program 2, tools/voice/build_vab.py) are played elsewhere and stay.
  psp: nothing is changed; writes the report only.
How this was established: the PS1 routine and the PSP function 0x2248 were read side by side (static analysis of
ROCK_NEO.EXE and the EBOOT); the title-call code 0x1990-0x1A78 by code reading plus decoded listening copies of the
samples; the result was confirmed in game. See docs/RESEARCH.md §8 (title screen) and §5 (segments, relocations).
Report: build/eboot/ps1_title.json (read by audit_eboot.py and verify_ps1_title.py)."""
import sys, json, struct
MODE = sys.argv[1] if len(sys.argv) > 1 else 'ps1'; assert MODE in ('ps1', 'psp')
# BASE: file offset of virtual address 0 (the code segment starts 0x80 into the ELF)
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/ps1_title.json'
if MODE == 'psp':
    json.dump(dict(mode='psp'), open(REP, 'w')); print('title: PSP (unchanged)'); sys.exit(0)
d = bytearray(open(P, 'rb').read())
# ELF header: e_phoff at 0x1C, e_phnum at 0x2C. A program header is 8 u32:
# [0] type, [1] file offset, [2] vaddr, [3] paddr, [4] file size, [5] memory size, [6] flags, [7] align
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
assert phnum == 3, 'run after build_sysmsg.py / build_savetext.py (segment 2 expected)'
ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
def r32(va): return struct.unpack_from('<I', d, BASE + va)[0]
# words: {address: [old word, new word]} for the report; w32 checks the original word when one is given
words = {}
def w32(va, new, old=None):
    if old is not None: assert r32(va) == old, ('unexpected original word', hex(va), hex(r32(va)), hex(old))
    words[va] = [r32(va), new]; struct.pack_into('<I', d, BASE + va, new)
# A minimal MIPS assembler: register numbers, I-type (op rs rt imm) and R-type (rs rt rd sa fn) encoders,
# br = a branch from address `at` to `to` (offset counted from the delay slot), hi = the upper half for a
# lui/addiu pair (addiu sign-extends, hence + 0x8000)
R = {'zero': 0, 'at': 1, 'v0': 2, 'v1': 3, 'a0': 4, 'a1': 5, 's0': 16, 's1': 17, 's2': 18, 's3': 19, 's4': 20, 'fp': 30, 'ra': 31}
def I(op, rs, rt, imm): return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)
def rr(rs, rt, rd, fn, sa=0): return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn
def br(op, rs, rt, at, to): off = (to - (at + 4)) // 4; assert -0x8000 <= off < 0x8000; return I(op, rs, rt, off)
def hi(x): return ((x + 0x8000) >> 16) & 0xFFFF
# opcodes: lui 0x0F, addiu 0x09, lw 0x23, sw 0x2B, andi 0x0C; functions: addu 0x21, srl 0x02, jalr 0x09
lui = lambda rt, imm: I(0x0F, 'zero', rt, imm); addiu = lambda rt, rs, imm: I(0x09, rs, rt, imm)
lw = lambda rt, o, rs: I(0x23, rs, rt, o); sw = lambda rt, o, rs: I(0x2B, rs, rt, o); andi = lambda rt, rs, imm: I(0x0C, rs, rt, imm)
addu = lambda rd, rs, rt: rr(rs, rt, rd, 0x21); srl = lambda rd, rt, sa: rr('zero', rt, rd, 0x02, sa)
jalr = lambda rs: rr(rs, 'zero', 'ra', 0x09); NOP = 0

# --- 1. background primitives (PS1 0x800140BC-0x80014358), as words after AddPrim's tag; control = words | OT offset << 8
# Texture page word 0xD9 = 8-bit texture (0x80) | abr 2 (0x40) | y 0x100 (0x10) | x 0x240/64 (9);
# CLUT word 0x7C80 = row 0x1F2 << 6 | x 0. NTITLE3U sits at VRAM 0x240,0x100 with its CLUT on row 0x1F2
TP, CL = 0xD9, 0x7C80          # GetTPage(1, 2, 0x240, 0x100), GetClut(0, 0x1F2)
DRM = 0xE1000000 | 0xC0        # SetDrawMode(p, 0, 0, GetTPage(1, 2, 0, 0), NULL): E1 word; second word 0
# xy: a vertex word (y << 16 | x). uv: a texture word (u, v in the low bytes; CLUT or tpage in the high half)
def xy(x, y): return (y << 16) | x
def uv(u, v, hiw=0): return (hiw << 16) | (v << 8) | u
# Primitive words after the tag: colour + code, then per vertex xy (+ uv for textured, + colour for gouraud).
# 0x2C = textured quad (colour 808080 = texture unchanged); 0x3A = gouraud quad, semi-transparent (with the
# draw mode below: subtractive); 0x38 = gouraud quad. Colours are 00BBGGRR: 00FFFFFF subtracts everything
# (fade to black at y 0xA0), 00E0FFC0 = (C0,FF,E0). Screen 0x140 wide; the second quad runs u 0xA0 -> 0
# (mirrored). Slots and order as in the PS1 routine.
PRIMS = [  # (OT offset, words: tag (length byte), then the primitive)
 (0x8C, [9 << 24, 0x2C808080, xy(0, 0), uv(0, 0, CL), xy(0xA0, 0), uv(0xA0, 0, TP), xy(0, 0xA0), uv(0, 0xA0), xy(0xA0, 0xA0), uv(0xA0, 0xA0)]),
 (0x8C, [9 << 24, 0x2C808080, xy(0xA0, 0), uv(0xA0, 0, CL), xy(0x140, 0), uv(0, 0, TP), xy(0xA0, 0xA0), uv(0xA0, 0xA0), xy(0x140, 0xA0), uv(0, 0xA0)]),
 (0x88, [8 << 24, 0x3A000000, xy(0, 0x90), 0x00000000, xy(0x140, 0x90), 0x00FFFFFF, xy(0, 0xA0), 0x00FFFFFF, xy(0x140, 0xA0)]),
 (0x88, [2 << 24, DRM, 0]),
 (0x8C, [8 << 24, 0x38000000, xy(0, 0xA2), 0x00000000, xy(0x140, 0xA2), 0x00E0FFC0, xy(0, 0xF0), 0x00E0FFC0, xy(0x140, 0xF0)]),
]
# Template block: per primitive one control word (number of words | OT offset << 8) then the words; a zero
# control word ends the list
data = b''.join(struct.pack('<I', len(w) | (ot << 8)) + struct.pack(f'<{len(w)}I', *w) for ot, w in PRIMS) + b'\0' * 4
# the copy loop advances the primitive-buffer pointer by 0x28 bytes per primitive
for _, w in PRIMS: assert 4 * len(w) <= 0x28, 'primitive larger than the 0x28-byte stride'
# the templates go at the end of segment 2 (word-aligned); DATA_VA = their virtual address
seg2 = bytearray(d[ph[2][1]:ph[2][1] + ph[2][4]])
while len(seg2) % 4: seg2 += b'\0'
DATA_VA = ph[2][2] + len(seg2); seg2 += data
# entry (0x2370, right after the logo's AddPrim): bal -> ra = 0x2378; s0 = data, s3 = AddPrim,
# s4 = &OT pointer (segment 1 + 0x500800)
PC = 0x2378; ADDPRIM, EXIT, LOOP = 0x21647C, 0x2490, 0x240C
# The old code reads the ordering-table pointer with lui 0x50 / lw 0x800: those immediates are relocated against segment
# 1 (relocation addr_base 1), so the real address is segment 1's vaddr + 0x500800 (checked on the relocation entries)
# Sony's program: the code relocation table is at file offset 0x325018 (0x9F3D8 bytes of 8-byte entries:
# offset, info; info = type | offset base << 8 | address base << 16). 0x10005 / 0x10006 = HI16 / LO16 against
# segment 1
_o = bytes(open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8])
_r = {struct.unpack_from('<I', _o, k)[0]: struct.unpack_from('<I', _o, k + 4)[0] for k in range(0, len(_o), 8)}
assert _r[0x2474] == 0x10005 and _r[0x2484] == 0x10006, 'OT pointer relocation not against segment 1'
OTPTR = ph[1][2] + 0x500800
# identification: 0x2368 is `jal AddPrim` (the logo), 0x2374 and 0x2490 `lui v0,0x50`, 0x2484 `lw a0,0x800(v0)`
assert r32(0x2368) >> 26 == 3 and (r32(0x2368) & 0x3FFFFFF) << 2 == ADDPRIM, 'logo AddPrim call not where expected'
assert r32(0x2374) == 0x3C020050, 'bal delay slot (lui v0,0x50) changed'
assert r32(0x2490) == 0x3C020050 and r32(0x2484) == 0x8C440800, 'tail of 0x2248 not as expected'
# bal = bgezal zero (opcode 1, rt 0x11) with offset +1: continues at 0x2378 with ra = 0x2378, the base for all
# PC-relative addresses below. It replaces the old code's first word (0xA3D70003, sb s7,3(fp))
code = [I(0x01, 'zero', 'zero', 0) | (0x11 << 16) | 1]               # bal 0x2378 (bgezal zero, +1)
w32(0x2370, code[0], 0xA3D70003)
# s0 = template data, s3 = AddPrim, s4 = address of the OT pointer; each = ra + (target - 0x2378)
entry = [lui('at', hi(DATA_VA - PC)), addiu('at', 'at', DATA_VA - PC), addu('s0', 'ra', 'at'),
         lui('at', hi(ADDPRIM - PC)), addiu('at', 'at', ADDPRIM - PC), addu('s3', 'ra', 'at'),
         lui('at', hi(OTPTR - PC)), addiu('at', 'at', OTPTR - PC), addu('s4', 'ra', 'at')]
for k, v in enumerate(entry): w32(PC + 4*k, v)
w32(PC + 36, br(0x04, 'zero', 'zero', PC + 36, LOOP)); w32(PC + 40, NOP)        # b LOOP
# Copy loop (L = 0x240C, C = the inner word loop at L + 0x14). fp is the function's primitive-buffer pointer.
#   L:  s2 = control word; s0 += 4; if s2 == 0 goto EXIT (0x2490, the old code's end); s1 = word count;
#       a1 = fp
#   C:  copy one word [s0] -> [a1], s0 += 4, a1 += 4, s1 -= 1; loop while s1 != 0
#       a0 = OT pointer + (s2 >> 8); AddPrim(a0, a1 = fp); fp += 0x28; goto L
L, C = LOOP, LOOP + 0x14
loop = [lw('s2', 0, 's0'), addiu('s0', 's0', 4), br(0x04, 's2', 'zero', L + 8, EXIT), andi('s1', 's2', 0xFF), addu('a1', 'fp', 'zero'),
        lw('v0', 0, 's0'), addiu('s0', 's0', 4), addiu('s1', 's1', -1), sw('v0', 0, 'a1'), br(0x05, 's1', 'zero', C + 16, C), addiu('a1', 'a1', 4),
        lw('a0', 0, 's4'), srl('v1', 's2', 8), addu('a0', 'a0', 'v1'), jalr('s3'), addu('a1', 'fp', 'zero'),
        br(0x04, 'zero', 'zero', L + 64, L), addiu('fp', 'fp', 0x28)]
for k, v in enumerate(loop): w32(L + 4*k, v)
# the old code's relocated words inside 0x2370-0x2490: the loader still rewrites them, so nothing may be put there
RELOCATED = (0x2374, 0x23B0, 0x23B4, 0x23F4, 0x2404, 0x2408, 0x2474, 0x2484, 0x2488)
assert not [va for va in words if va in RELOCATED], 'a relocated word was overwritten'
assert L + 4*len(loop) <= 0x2474, 'loop runs into the relocated words at 0x2474'
# --- 2. PRESS START / copyright palette 0 -> 8
# 0x00002021 = move a0,zero (clut x 0 = palette 0) -> 0x24040080 = addiu a0,zero,0x80 (palette 8: 16 colours each)
for va in (0x253C, 0x25F8): w32(va, 0x24040080, 0x00002021)                   # move a0,zero -> addiu a0,zero,0x80
# --- 3. Japanese title calls: branch past the sound-queue calls
# 0x19A4 beq v1,v0 (opcode 4): target 0x1A40 -> 0x1A78; 0x19AC beql v1,v0 (opcode 0x14): 0x19E0 -> 0x1A14.
# The new targets are checked below: 0x1A78 = `j 0x19B4`, 0x1A14 = 0x92030002 (lbu v1,2(s0))
w32(0x19A4, br(0x04, 'v1', 'v0', 0x19A4, 0x1A78), br(0x04, 'v1', 'v0', 0x19A4, 0x1A40))
w32(0x19AC, br(0x14, 'v1', 'v0', 0x19AC, 0x1A14), br(0x14, 'v1', 'v0', 0x19AC, 0x19E0))
assert r32(0x1A78) == 0x08000000 | (0x19B4 >> 2) and r32(0x1A14) == 0x92030002, 'branch targets not as expected'
# segment 2 grows: it is followed only by the program headers (build_sysmsg.py), rewrite them after it
while len(seg2) % 16: seg2 += b'\0'
del d[ph[2][1]:]; d += seg2; ph[2][4] = ph[2][5] = len(seg2)
while len(d) % 4: d += b'\0'
new_phoff = len(d)
for p in ph: d += struct.pack('<8I', *p)
struct.pack_into('<I', d, 0x1C, new_phoff)
open(P, 'wb').write(d)
json.dump(dict(mode='ps1', data_va=DATA_VA, data_len=len(data), data=data.hex(), code_range=[0x2370, 0x2490],
               words={hex(k): [hex(a), hex(b)] for k, (a, b) in sorted(words.items())}), open(REP, 'w'), indent=1)
print(f'title: PS1 background code + {len(PRIMS)} primitives ({len(data)} bytes at {DATA_VA:#x}), PRESS START palette 8, title calls removed; {len(words)} words changed')
