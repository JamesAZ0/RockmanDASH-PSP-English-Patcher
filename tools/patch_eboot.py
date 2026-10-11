"""Patch the game's program (the plain EBOOT of Rockman DASH, ULJM05030) for English text. Three code changes:
variable-width letter spacing, a wider title menu, and the moved text buffers.
Input : decrypted_eboot/ULJM05030_EBOOT.BIN (plain PRX/ELF, made by tools/plain_eboot.py), and the font with the
        added glyphs, build/font/font.dat (tools/build_font.py), for the letter widths
Output: build/eboot/ULJM05030_EBOOT_vwf.BIN (same size; tools/build_sysmsg.py continues from it)
Reference: docs/RESEARCH.md §4 (text rendering), §5 (the program), §6 (text buffers), §8 (title screen).
All addresses are vaddr in the first segment (.text); file offset = vaddr + 0x80 (BASE). Every instruction that is
changed is first compared with the original and the script stops if it differs (another game version).

1. Variable-width text. The Japanese game draws every character in a 12-px cell; the English script's line breaks and
window sizes assume the narrow US font, so with fixed cells lines were clipped at the window edge (seen in the first
English test build).
Text renderer (static analysis, 2026-09-28): the loop at 0x3C810 draws each char as a 12x12 sprite; after drawing,
0x3C98C does x += 12. We replace 0x3C980-0x3C994 with a PC-relative trampoline to a cave that computes
    x += rbx[c] + 1 - lb[next]
using a per-glyph table (lb = first ink column, rbx = last ink column (+1 px gap for Latin)); kana/kanji keep 12.
The trampoline is PC-relative (bal + offset) because the program is relocatable: an absolute jump would need a
relocation entry.
Cave: code at 0x226920, table at 0x226980, inside 0x22691C-0x226BB0: a block of unused libm float helpers
(sqrtf/truncf/fmodf...). Verified dead by whole-program reachability (from every jal/j target, every data word that
looks like a text address, and every lui+addiu/ori pair) and a second lui/lo16 scan; it contains no relocation
entries. (A first cave at 0x4E7E8/0x4E998, inside what looked like one unreferenced function, was really several
small leaf functions that are called, and crashed at the title screen; hence the reachability check.)
research/eboot_findings.py re-finds the draw loop and re-checks the cave on any copy of the program.

2. Title menu: seven immediates in function 0x26BC (TITLE below) widen the three options from 80 to 86 px.
3. Text buffers: the immediates of every instruction pair that builds a moved buffer's address (tools/memmap.py)."""
import struct, sys, os
sys.path.insert(0, 'tools'); import psp_font as F
SRC = 'decrypted_eboot/ULJM05030_EBOOT.BIN'; DST = 'build/eboot/ULJM05030_EBOOT_vwf.BIN'
FONT = 'build/font/font.dat' if len(sys.argv) < 2 else sys.argv[1]   # PSP font + PS1 alpha/omega/;/= (tools/build_font.py)
# BASE: file offset of vaddr 0 (the first segment starts 0x80 bytes into the file).
# TRAMP: first replaced instruction; CAVE / TABLE: the new code and its width table; DEAD: the verified dead block.
BASE = 0x80
TRAMP, CAVE, TABLE = 0x3C980, 0x226920, 0x226980
DEAD = (0x22691C, 0x226BB0)
N = 0x1A7                                  # table covers codes 0x000-0x1A6 (0x1A5 '=' from build_font.py, 0x1A6 English space)
d = bytearray(open(SRC, 'rb').read())
def w32(va, v): struct.pack_into('<I', d, BASE + va, v)
def r32(va): return struct.unpack_from('<I', d, BASE + va)[0]

# sanity: original instructions at trampoline. s0 = the text state: +0x10 pen x (u16), +0x14 pointer to the current
# character. In order: lhu a0,0x10(s0); lw a2,0x6C(s0); lw a1,0x14(s0); addiu a0,a0,12 (the fixed advance);
# sh a0,0x10(s0); addiu v0,a1,2; sw v0,0x14(s0) (the last one is kept: the cave returns to it).
expect = {0x3C980: 0x9604_0010, 0x3C984: 0x8E06_006C, 0x3C988: 0x8E05_0014, 0x3C98C: 0x2484_000C,
          0x3C990: 0xA604_0010, 0x3C994: 0x24A2_0002, 0x3C998: 0xAE02_0014}
for va, v in expect.items(): assert r32(va) == v, (hex(va), hex(r32(va)))

# --- MIPS encoders (I-type: opcode << 26 | rs << 21 | rt << 16 | imm16; R-type: function code in the low 6 bits)
R = {'zero':0,'at':1,'v0':2,'v1':3,'a0':4,'a1':5,'a2':6,'s0':16,'ra':31}
def I(op, rs, rt, imm): return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xFFFF)
def lhu(rt, off, rs): return I(0x25, rs, rt, off)
def lw(rt, off, rs):  return I(0x23, rs, rt, off)
def lbu(rt, off, rs): return I(0x24, rs, rt, off)
def sh(rt, off, rs):  return I(0x29, rs, rt, off)
def addiu(rt, rs, imm): return I(0x09, rs, rt, imm)
def sltiu(rt, rs, imm): return I(0x0B, rs, rt, imm)
def andi(rt, rs, imm): return I(0x0C, rs, rt, imm)
def ori(rt, rs, imm):  return I(0x0D, rs, rt, imm)
def lui(rt, imm):      return I(0x0F, 'zero', rt, imm)
def beq(rs, rt, off):  return I(0x04, rs, rt, off)
# bgezal zero,off is 'bal': always branches and sets ra = address of the instruction after the delay slot
def bgezal(rs, off):   return (0x01 << 26) | (R[rs] << 21) | (0x11 << 16) | (off & 0xFFFF)
def addu(rd, rs, rt):  return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | 0x21
def subu(rd, rs, rt):  return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | 0x23
def srl(rd, rt, sa):   return (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | 0x02
def jr(rs):            return (R[rs] << 21) | 0x08
def jalr(rs):          return (R[rs] << 21) | (31 << 11) | 0x09
NOP = 0

# --- trampoline (0x3C980..0x3C994), returns to 0x3C998 (sw v0,0x14(s0))
#   0x3C980 lui  v1,hi(delta)
#   0x3C984 bal  +1               ra = 0x3C98C (its own address + 8)
#   0x3C988 ori  v1,v1,lo(delta)  (delay slot)
#   0x3C98C addu v1,v1,ra         v1 = 0x3C98C + delta = CAVE, wherever the program was loaded
#   0x3C990 jalr v1               ra = 0x3C998
#   0x3C994 nop
delta = CAVE - 0x3C98C
tr = [lui('v1', delta >> 16), bgezal('zero', 1), ori('v1', 'v1', delta & 0xFFFF),
      addu('v1', 'v1', 'ra'), jalr('v1'), NOP]
for k, v in enumerate(tr): w32(TRAMP + 4*k, v)

# --- cave (v1 = CAVE on entry, ra = 0x3C998). T = offset of the width table from CAVE, so table[c] is at v1 + c + T.
# Table byte = lb << 4 | rbx. Codes outside the table (>= N: kanji, control codes) use 0x0B = lb 0, rbx 11 -> 12 px.
T = TABLE - CAVE
code = [
    lhu('a0', 0x10, 's0'),        # x
    lw('a2', 0x6C, 's0'),         # displaced original instruction, re-run (s0+0x6C: origin not recorded)
    lw('a1', 0x14, 's0'),         # text pointer
    lhu('v0', 0, 'a1'),           # c
    sltiu('at', 'v0', N),
    beq('at', 'zero', 3),         # -> L1 (skip 2 + delay)
    addiu('at', 'zero', 0x0B),    # delay: default = lb 0, rbx 11 (advance 12)
    addu('at', 'v0', 'v3' if False else 'v1'),   # at = CAVE + c (the conditional always yields v1)
    lbu('at', T, 'at'),           # at = table[c]
    # L1:
    andi('v0', 'at', 0x0F),       # rbx
    addu('a0', 'a0', 'v0'),
    addiu('a0', 'a0', 1),         # x += rbx + 1
    lhu('v0', 2, 'a1'),           # next char
    sltiu('at', 'v0', N),
    beq('at', 'zero', 5),         # -> L2
    NOP,
    addu('at', 'v0', 'v1'),
    lbu('at', T, 'at'),
    srl('at', 'at', 4),           # lb of next
    subu('a0', 'a0', 'at'),
    # L2:
    sh('a0', 0x10, 's0'),
    jr('ra'),
    addiu('v0', 'a1', 2),         # delay: v0 = ptr + 2 (stored by 0x3C998)
]
assert CAVE + 4*len(code) <= TABLE, 'code overlaps table'
for k, v in enumerate(code): w32(CAVE + 4*k, v)

# --- width table from the actual PSP font: measured only for the glyphs English text uses. 0x00-0x53 = digits,
# punctuation and Latin letters; 0xFD-0x10B = the symbol set (button icons , " . ... hand + %); then the four glyphs
# added by build_font.py. An empty cell (F.ink() is None, e.g. 0x4F the full-width space) keeps the default 12 px,
# as does everything not listed (kana, 0x10C the empty choice-cursor slot, kanji).
P = F.pages(open(FONT, 'rb').read())
tbl = bytearray([0x0B] * N)
widths = {}
def setw(c, lb, rbx):
    tbl[c] = (lb << 4) | rbx; widths[c] = rbx + 1 - lb
latin = list(range(0x00, 0x54)) + list(range(0xFD, 0x10C)) + [0x10D, 0x10E, 0x10F, 0x1A5]
for c in latin:
    e = F.ink(F.glyph(P, c))
    if e is None: continue
    lb, rb = e
    setw(c, lb, min(rb + 1, 12))          # 1 px gap after the glyph
setw(0x1A6, 0, 4)                          # English space (msgtool maps PS1 0x4F here): 5 px. 0x4F keeps 12 px (Japanese
                                           # full-width space; the engine uses it to position menu cursors)
assert DEAD[0] <= CAVE and TABLE + N <= DEAD[1], 'cave outside the verified dead block'
# no relocation may touch the cave: scan the first relocation table (file offset 0x325018, 0x9F3D8 bytes of 8-byte
# (offset, info) entries); the offsets are compared directly with the cave's vaddr range
_rel = [struct.unpack_from('<II', d, 0x325018 + 8*k)[0] for k in range(0x9F3D8 // 8)]
assert not [a for a in _rel if CAVE <= a < TABLE + N], 'relocation inside cave'
d[BASE + TABLE: BASE + TABLE + N] = tbl

# --- Title menu (project decision 2026-09-29): English option words from PS1 NTITLE5U, re-spaced to 1 px letter gaps
# (tools/build_title.py). Function 0x26BC draws NEW GAME / CONTINUE / OPTION as POLY_FT4 quads sharing one screen
# width (s4..s5) with side-by-side u cells in texture row v 0xC0-0xD0. Width 80 -> 86 (x 0x75-0xCB, centred on 160);
# u cells 0-0x56 | 0x56-0xAC | 0xA9-0xFF (cell 3 overlaps cell 2's blank last 3 columns). Only immediates change.
# 86 is the widest that fits: the three cells share one 256-px texture row. Each entry: vaddr: (original, new word).
# The original u values appear as negative immediates (-0x60 = 0xA0, -0x10 = 0xF0): they are stored as bytes.
TITLE = {0x277C: (0x24140078, 0x24140075),   # addiu s4,zero,0x78  -> 0x75   screen x left  (all three options)
         0x2780: (0x241500C8, 0x241500CB),   # addiu s5,zero,0xC8  -> 0xCB   screen x right
         0x278C: (0x24130050, 0x24130056),   # addiu s3,zero,0x50  -> 0x56   u: option1 right / option2 left
         0x2860: (0x2404FFA0, 0x240400AC),   # addiu a0,zero,-0x60 -> 0xAC   u: option2 right
         0x2920: (0x2402FFA0, 0x240200A9),   # addiu v0,zero,-0x60 -> 0xA9   u: option3 left (u2)
         0x2944: (0x2404FFA0, 0x240400A9),   # addiu a0,zero,-0x60 -> 0xA9   u: option3 left (u0)
         0x2928: (0x2406FFF0, 0x240600FF)}   # addiu a2,zero,-0x10 -> 0xFF   u: option3 right
for va, (old, new) in TITLE.items():
    assert r32(va) == old, ('title', hex(va), hex(r32(va))); w32(va, new)

# --- Text buffers moved into the unused PS1 program area (tools/memmap.py MOVES/SITES; project decision 2026-09-29):
# pause/sub-screen text, stage text and support-car text. Each site is a clean lui/lo pair found by
# research/msg_base_refs.py; only the 16-bit immediates change. 'hi' sites must be a lui (opcode 0x0F) holding
# the old high half; 'lo' sites (addiu or a load/store) must hold the old low half.
sys.path.insert(0, 'tools'); import memmap as MM
for key, (old, new, _lim) in MM.MOVES.items():
    oh, ol = MM.hi_lo(MM.rel_const(old)); nh, nl = MM.hi_lo(MM.rel_const(new))
    for va in MM.SITES[key]['hi']:
        v = r32(va); assert v >> 26 == 0x0F and v & 0xFFFF == oh, (key, 'hi', hex(va), hex(v)); w32(va, (v & ~0xFFFF) | nh)
    for va in MM.SITES[key]['lo']:
        v = r32(va); assert v & 0xFFFF == ol, (key, 'lo', hex(va), hex(v)); w32(va, (v & ~0xFFFF) | nl)
os.makedirs('build/eboot', exist_ok=True); open(DST, 'wb').write(d)
print('wrote', DST, 'size', len(d))
# a few table entries for a quick look: some letters, the full-width space 0x4F (must stay 0,11) and symbols
print('sample advances (lb,rbx):', {hex(c): (tbl[c] >> 4, tbl[c] & 15) for c in (0x15, 0x1D, 0x21, 0x2C, 0x30, 0x38, 0x3B, 0x3C, 0x4F, 0x0D, 0x105, 0x107, 0x100)})
