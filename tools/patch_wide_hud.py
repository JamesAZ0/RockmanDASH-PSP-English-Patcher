"""HUD, windows and text at correct proportions in the Wide screen mode, game world untouched. Build option:
`python build.py <tag> --hud=off|center|edge|hud-only` (default hud-only; project decision, 2026-10-02). build.py
passes this script the internal argument off|center|edges|hudonly. center and edge are kept but have not been
tested in play.
In Wide the game stretches its whole 320x240 frame to 480x272, so the HUD and text are 1.32x too wide. The frame is drawn
by the native DrawOTag (0x216F0C), which walks one primitive list. Its top-level ordering table (8 slots at
*(segment 1 + 0x500800) + 0x70..0x8C, walked from +0x8C down) keeps the layers apart: +0x8C..+0x84 = backdrops,
+0x80 = the 3D world, +0x7C = windows and text, +0x78 = HUD, +0x74 = front. Every primitive handler converts
x coordinates and widths with one tiny function, 0x217214 (x*2), after adding the draw offset (segment 1 + 0x15AD58).
What the option does, only while the Screen setting is Wide (segment 1 + 0x15AD50 == 0) and only for primitives after
the +0x7C slot node (2D):
  - x scale 2 -> 1.5 (three quarters): the handlers' calls of 0x217214 go to a new function;
  - a bias added to the draw offset so the squeeze is about the screen centre (53: 0.75*(x+53.3) = 160+0.75*(x-160));
  - 'hudonly' (--hud=hud-only; project decision 2026-10-02): as 'edges', but only the HUD slot is squeezed, and only
    while a world is drawn; windows, text, subtitles and menus keep the original proportions (squeezed text is
    harder to read, most of all on real hardware);
  - 'edges': in the HUD slot, pieces wholly left of x 80 keep to the left edge (bias 0) and pieces wholly right of
    x 240 to the right edge (bias 107); everything else is centred. Only while the world slot has primitives (menus,
    which draw no world, stay centred as a whole);
  - a layer of tiles running unbroken across the screen in the HUD slot (overlays in cutscenes: pieces in the middle
    joined exactly to pieces in both edge bands) turns the squeeze off for the whole HUD slot that frame (one look
    over the slot when it starts);
  - clip rectangles (E3: x, y, w, h) get the same squeeze and bias, chosen from the rectangle like a primitive (the
    handler's left-edge call goes to a variant that adds the bias itself, since clip positions don't use the draw offset);
  - primitives 300 or more units wide (fades, full-screen backdrops) are left alone.
The 3D world (slot +0x80) and the backdrop slots are never changed.
How: existing jal instructions are retargeted (their relocation entries stay valid): DrawOTag's call of 0x2172E0
(start: reset, look at the first primitive), its call of 0x2212D8 after each primitive (look ahead to the next
primitive: zone, squeeze or not, bias), its call of 0x217530 at the end (squeeze off), and the 0x217214 calls. The new
code and its 8 state words are appended to segment 2 and are position-independent (bal), so no relocation is added.
How this was established: the Screen flag by comparing the memory of two save states (Wide / Original); DrawOTag,
the slot layout and the single x-scale function by reading the code against the primitive lists in save states; the
'edges' rules from save states of screens an earlier per-piece rule tore apart (title, banners, menus, cutscene
overlays). research/verify_wide_hud.py (a separate command) runs this code in a MIPS emulator over the
save-state frames and compares every decision with a Python model. Not yet known: whether 2D markers tied to world
positions shift. See docs/RESEARCH.md §13, and §16 for the open points.
Primitive node layout used below: +0 tag (low 24 bits = link to the next node, byte +3 = length in words; length 0 =
an ordering-table slot or other empty node), byte +7 = primitive code, +8 = first vertex (x at +8, y at +0xA).
Runs after build_savetext.py (segment 2 needed) on build/eboot/ULJM05030_EBOOT_en.BIN.
Usage: python3 tools/patch_wide_hud.py off|center|edges   (internal argument)     Report: build/eboot/wide_hud.json"""
import sys, json, struct
# BASE: file offset of virtual address 0 (code segment)
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/wide_hud.json'
# The game's functions whose calls are retargeted: x scale (x*2), DrawOTag's start call, its call after each
# primitive, and its final call (the paste of the finished frame to the screen)
F_OLD, START_OLD, POST_OLD, END_OLD = 0x217214, 0x2172E0, 0x2212D8, 0x217530
# the 20 `jal 0x217214` instructions in the primitive handlers (polygons, lines, sprites/tiles, special) that
# convert an x position or width, plus the clip-rectangle (E3) width call
F_SITES = [0x217D34, 0x217E8C, 0x218018, 0x218194, 0x2182E8, 0x2184BC, 0x2186C0, 0x21873C, 0x21878C, 0x2187A4, 0x2187D8,
           0x218900, 0x218940, 0x218994, 0x2189BC, 0x218AA0, 0x218AE0, 0x218B14, 0x218B4C,
           0x217A08]                                    # the last one: E3 clip width
FPOS_SITES = [0x2179F0]                                # E3 clip left edge (a position without the draw offset)
# the three jal instructions inside DrawOTag (0x216F0C) that become the start / post / end hooks
START_SITE, POST_SITE, END_SITE = 0x216F58, 0x217018, 0x217198
# bias in 320-wide units: 53 centres the squeezed picture, 107 (twice that) puts x 320 back on the right edge;
# FULL: primitives this wide or wider are never squeezed
CENTER, RIGHT, FULL = 53, 107, 300
LEFT_MAX, RIGHT_MIN = 80, 240                         # 'edges': HUD pieces wholly left of x 80 / right of x 240 keep to that edge
# MIPS register numbers
R = dict(zero=0, at=1, v0=2, v1=3, a0=4, a1=5, a2=6, a3=7, t0=8, t1=9, t2=10, t3=11, t4=12, t5=13, t6=14, t7=15, s0=16,
         t8=24, t9=25, sp=29, ra=31)
# State words (byte offsets from label 'vars'): MODEV = squeeze on for the next primitive; BIASV = the bias
# currently added to the draw offset; BIASED = 1 while that bias is in the offset; ZONE = 0 backdrops/world,
# 1 windows and text, 2 HUD, 3 front; EDGES = 1 for the 'edges' variant (constant); W80 = the walk has reached
# the world slot; WORLD = the world slot had a primitive this frame; MASK0, MASK1 = the HUD slot's column mask (prescan); (was HUDMODE) in the
# HUD slot, don't squeeze it
MODEV, BIASV, BIASED, ZONE, EDGES, W80, WORLD, MASK0, HUDOFF, MASK1 = 0, 4, 8, 12, 16, 20, 24, 28, 32, 36   # state words at 'vars'
CELLS, PANEL = 40, 20       # 8-unit columns across the screen; a left/right run spanning more than PANEL columns is a panel
# --- Triangle toggle on the options screen (project decision 2026-10-02; docs/RESEARCH.md section 13) --------------
# The options screen is run by the text engine. Its selection handler (0x3ED60-0x3F0C0; s0 = window context, newly
# pressed pad bits at +0xBA in the PS1 layout, Triangle = 0x1000) shows the help text of the highlighted choice every
# frame with 'jal 0x3C00C' at 0x3EE18 (a1 = the string, taken from the system-message table at segment 1 + 0xF31C).
# Entry 242 is the help text of Screen = Wide. That call is retargeted to 'opt' below: when a1 is entry 242's string,
# Triangle flips HUDOFF (1 = adjustment off; kept in memory only, so it is on again after a restart and nothing is
# written to the save), plays the menu sound 0x82 (0x7728, as the handler does when a choice changes), and a1 is
# replaced by a copy of the string with a second row "(triangle) HUD Size: Corrected" / "... Default" (approved new
# text; first wording "HUD Adjustment: On / Off", changed 2026-10-02).
OPT_SITE, OPT_OLD, SND_FN, SYSMSG_TABLE, WIDE_HELP = 0x3EE18, 0x3C00C, 0x7728, 0xF31C, 242
HINT_LABEL, HINT = ' HUD Size:', (' Corrected', ' Default')   # (adjustment on, off); wording: project decision 2026-10-02
# the EDGES state word per variant: bit 0 = edge anchoring in the HUD slot, bit 1 = HUD slot only ('hudonly')
FLAGS = {'center': 0, 'edges': 1, 'hudonly': 3}
def assemble(origin, seg1, edges, strings=None):
    """-> (words, labels). Position-independent; 'origin' = vaddr of the first word; seg1 = segment 1's vaddr."""
    # prog: one function per word, called with the word's address once all labels (L) are known.
    # I / RR = I-type and R-type encoders; br = branch to a label; bal = bgezal zero (branch and link, used both
    # as a local call and to get the current address into ra); seh = 0x7C000620 | rt | rd (sign-extend halfword)
    prog = []; L = {}
    def lab(n): L[n] = origin + 4 * len(prog)
    def emit(f): prog.append(f)
    def I(op, rs, rt, imm): emit(lambda pc: (op << 26) | (R[rs] << 21) | (R[rt] << 16) | ((imm(pc) if callable(imm) else imm) & 0xFFFF))
    def RR(rs, rt, rd, fn, sa=0): emit(lambda pc: (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | fn)
    def br(op, rs, rt, to):
        def f(pc):
            off = (L[to] - (pc + 4)) >> 2; assert -0x8000 <= off < 0x8000, to
            return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (off & 0xFFFF)
        emit(f)
    beq = lambda rs, rt, to: br(4, rs, rt, to); bne = lambda rs, rt, to: br(5, rs, rt, to); b = lambda to: br(4, 'zero', 'zero', to)
    def bal(to): emit(lambda pc: (1 << 26) | (0x11 << 16) | (((L[to] - (pc + 4)) >> 2) & 0xFFFF))
    nop = lambda: emit(lambda pc: 0)
    addiu = lambda rt, rs, imm: I(9, rs, rt, imm); lw = lambda rt, o, rs: I(0x23, rs, rt, o); sw = lambda rt, o, rs: I(0x2B, rs, rt, o)
    lh = lambda rt, o, rs: I(0x21, rs, rt, o); lhu = lambda rt, o, rs: I(0x25, rs, rt, o); sh = lambda rt, o, rs: I(0x29, rs, rt, o)
    lbu = lambda rt, o, rs: I(0x24, rs, rt, o); andi = lambda rt, rs, imm: I(0xC, rs, rt, imm); ori = lambda rt, rs, imm: I(0xD, rs, rt, imm)
    slti = lambda rt, rs, imm: I(0xA, rs, rt, imm); sltiu = lambda rt, rs, imm: I(0xB, rs, rt, imm); lui = lambda rt, imm: I(0xF, 'zero', rt, imm)
    addu = lambda rd, rs, rt: RR(rs, rt, rd, 0x21); subu = lambda rd, rs, rt: RR(rs, rt, rd, 0x23); and_ = lambda rd, rs, rt: RR(rs, rt, rd, 0x24)
    or_ = lambda rd, rs, rt: RR(rs, rt, rd, 0x25); sltu = lambda rd, rs, rt: RR(rs, rt, rd, 0x2B); slt = lambda rd, rs, rt: RR(rs, rt, rd, 0x2A)
    sllv = lambda rd, rt, rs: RR(rs, rt, rd, 4); srlv = lambda rd, rt, rs: RR(rs, rt, rd, 6)
    xori = lambda rt, rs, imm: I(0xE, rs, rt, imm); xor = lambda rd, rs, rt: RR(rs, rt, rd, 0x26)
    sll = lambda rd, rt, sa: RR('zero', rt, rd, 0, sa); srl = lambda rd, rt, sa: RR('zero', rt, rd, 2, sa); sra = lambda rd, rt, sa: RR('zero', rt, rd, 3, sa)
    jr = lambda rs: RR(rs, 'zero', 'zero', 8); jalr = lambda rs: RR(rs, 'zero', 'ra', 9)
    seh = lambda rd, rt: emit(lambda pc: 0x7C000620 | (R[rt] << 16) | (R[rd] << 11))
    def V(off, here): return lambda pc: L['vars'] + off - L[here]     # displacement of a state word from label 'here'
    def la(reg, base, target, here):                                   # reg = base + (target - here); base holds address 'here'
        d = lambda: (target if isinstance(target, int) else L[target]) - L[here]
        emit(lambda pc: (0xF << 26) | (1 << 16) | (((d() + 0x8000) >> 16) & 0xFFFF))          # lui at, hi
        emit(lambda pc: (9 << 26) | (1 << 21) | (1 << 16) | (d() & 0xFFFF))                  # addiu at, at, lo
        addu(reg, base, 'at')
    # ---- f (replaces 0x217214): v0 = a0*2, or a0*3/2 while squeezing. Uses v0 and at only (the original uses v0)
    # Entry: a0 = x; return address kept in `at`; `bal f1` puts f1's address in ra (to reach 'vars') while its
    # delay slot computes v0 = a0*2. If MODEV != 0: v0 = (a0*2 + a0) >> 1. Returns seh(v0), as the original
    # (sll v0,a0,1 ; jr ra ; seh v0,v0).
    lab('f'); addu('at', 'ra', 'zero'); bal('f1'); sll('v0', 'a0', 1)
    lab('f1'); lw('ra', V(MODEV, 'f1'), 'ra'); beq('ra', 'zero', 'f2'); nop(); addu('v0', 'v0', 'a0'); sra('v0', 'v0', 1)
    lab('f2'); jr('at'); seh('v0', 'v0')
    # ---- fpos: positions that don't include the draw offset (clip corners): (a0 + bias)*3/2 while squeezing
    # As f, but when squeezing the bias is added to the position first: v0 = 3*(a0 + BIASV) >> 1
    # (ra is free as a scratch register here: the return address is in `at`).
    lab('fpos'); addu('at', 'ra', 'zero'); bal('p1'); nop()
    lab('p1'); lw('v0', V(MODEV, 'p1'), 'ra'); beq('v0', 'zero', 'p2'); sll('v0', 'a0', 1)
    lw('ra', V(BIASV, 'p1'), 'ra'); addu('v0', 'a0', 'ra'); sll('ra', 'v0', 1); addu('v0', 'v0', 'ra'); sra('v0', 'v0', 1)
    lab('p2'); jr('at'); seh('v0', 'v0')
    # ---- extent(a0 = primitive, v0 = its code byte) -> v1 = left x, t3 = width (>= 0). Uses at. Leaf (bal).
    # E3 (clip): x = low 10 bits of the word at +4, width = bits 9-18 of the word at +8 (second word = width/height,
    # as seen in save-state frames, e.g. clips (14,36,54,54) and (0,0,320,240)).
    lab('extent'); addiu('at', 'zero', 0xE3); bne('v0', 'at', 'x1'); nop()
    lhu('v1', 4, 'a0'); andi('v1', 'v1', 0x3FF); lw('t3', 8, 'a0'); srl('t3', 't3', 9); jr('ra'); andi('t3', 't3', 0x3FF)       # E3: x, w
    # Everything else: v1 = x of the first vertex (+8). Codes 0x60-0x7F are rectangles (sprites, tiles):
    # size bits 0x18 clear = free size, width at +0xC, or +0x10 when textured (code & 4: a uv word comes first).
    lab('x1'); sltiu('at', 'v0', 0x60); bne('at', 'zero', 'x2'); lh('v1', 8, 'a0')
    andi('at', 'v0', 0x18); bne('at', 'zero', 'xr0'); nop()
    andi('at', 'v0', 4); addu('at', 'at', 'a0'); jr('ra'); lh('t3', 12, 'at')                                 # rect: w at +0xC (+4 if textured)
    lab('xr0'); srl('at', 'at', 3); addiu('at', 'at', -1); jr('ra'); sll('t3', 'at', 3)                        # fixed sizes: about 0 / 8 / 16
    # Codes 0x40-0x5F (lines) and below 0x20: width 0. Codes 0x20-0x3F (polygons): width = x of vertex 1 minus x
    # of vertex 0; vertex 1 is at +0xC, + 4 when textured (code & 4), + 4 when gouraud (code & 0x10: a colour word per
    # vertex). A negative width is turned round (v1 = the smaller x).
    lab('x2'); sltiu('at', 'v0', 0x40); bne('at', 'zero', 'x3'); nop(); jr('ra'); addu('t3', 'zero', 'zero')    # lines
    lab('x3'); sltiu('at', 'v0', 0x20); beq('at', 'zero', 'x4'); nop(); jr('ra'); addu('t3', 'zero', 'zero')    # < 0x20: unknown
    lab('x4'); andi('t3', 'v0', 4); andi('at', 'v0', 0x10); srl('at', 'at', 2); addu('t3', 't3', 'at'); addu('t3', 't3', 'a0'); lh('t3', 12, 't3')   # x of vertex 1
    subu('t3', 't3', 'v1'); slti('at', 't3', 0); beq('at', 'zero', 'x5'); nop(); addu('v1', 'v1', 't3'); subu('t3', 'zero', 't3')
    lab('x5'); jr('ra'); nop()
    # ---- prescan(a0 = the +0x78 slot node): look over the HUD slot's primitives once (those narrower than FULL) and
    # mark which 8-unit columns of the 320-unit screen they cover: 40 bits, MASK0 = columns 0-31, MASK1 = 32-39.
    # Pieces that touch or overlap in x then form unbroken runs of set bits; the decision below treats a run as one
    # object, so a gauge and its frame, or a banner made of several sprites, can't be pulled apart. (y is ignored.)
    # Keeps a0, t0-t2, t4-t8. Called from look (its frame: 4(sp) = ra, 8(sp) = a0). a2 / a3 = the two mask words.
    lab('prescan'); sw('ra', 4, 'sp'); sw('a0', 8, 'sp'); addu('a2', 'zero', 'zero'); addu('a3', 'zero', 'zero')
    # Step to the next node exactly as DrawOTag does: link = tag & 0xFFFFFF (t2); 0xFFFFFF ends the list; the
    # address is link | t1, with 0x1000000 added to t1 when link < t0 (t0, t1 = the walker's two pointer-rule
    # words, loaded in look). a0 - t5 = offset inside the ordering-table structure: +0x74 is the next slot, so the
    # HUD slot is over. Skipped: empty nodes (length byte 0) and commands (code >= 0x80).
    lab('ps'); lw('v0', 0, 'a0'); and_('v1', 'v0', 't2'); beq('v1', 't2', 'ps_end'); sltu('at', 'v1', 't0')
    beq('at', 'zero', 'ps1'); addu('a1', 't1', 'zero'); lui('at', 0x100); addu('a1', 'a1', 'at')
    lab('ps1'); or_('a0', 'v1', 'a1'); and_('at', 'a0', 't2'); beq('at', 'zero', 'ps_end'); subu('v0', 'a0', 't5')
    addiu('at', 'zero', 0x74); beq('v0', 'at', 'ps_end'); nop()
    lbu('v0', 3, 'a0'); beq('v0', 'zero', 'ps'); nop()
    lbu('v0', 7, 'a0'); sltiu('at', 'v0', 0x80); beq('at', 'zero', 'ps'); nop()
    bal('extent'); nop()
    slti('at', 't3', FULL); beq('at', 'zero', 'ps'); nop()
    # first column v1 = left >> 3, last column v0 = (left + max(width, 1) - 1) >> 3, both clamped to 0..39
    addu('v0', 'v1', 't3'); bne('t3', 'zero', 'pc0'); nop(); addiu('v0', 'v0', 1)
    lab('pc0'); addiu('v0', 'v0', -1); sra('v0', 'v0', 3); sra('v1', 'v1', 3)
    slt('at', 'v1', 'zero'); beq('at', 'zero', 'pc1'); nop(); addu('v1', 'zero', 'zero')
    lab('pc1'); slti('at', 'v1', CELLS); bne('at', 'zero', 'pc2'); nop(); addiu('v1', 'zero', CELLS - 1)
    lab('pc2'); slt('at', 'v0', 'zero'); beq('at', 'zero', 'pc3'); nop(); addu('v0', 'zero', 'zero')
    lab('pc3'); slti('at', 'v0', CELLS); bne('at', 'zero', 'pc4'); nop(); addiu('v0', 'zero', CELLS - 1)
    lab('pc4'); slt('at', 'v0', 'v1'); bne('at', 'zero', 'ps'); nop()
    # set bits v1 .. v0 (sllv uses the low 5 bits of the count, so 1 << (column & 31) serves both words)
    lab('pb'); addiu('at', 'zero', 1); sllv('at', 'at', 'v1'); slti('t3', 'v1', 32); beq('t3', 'zero', 'pbh'); nop(); b('pbn'); or_('a2', 'a2', 'at')
    lab('pbh'); or_('a3', 'a3', 'at')
    lab('pbn'); bne('v1', 'v0', 'pb'); addiu('v1', 'v1', 1)
    b('ps'); nop()
    lab('ps_end'); sw('a2', MASK0, 't8'); sw('a3', MASK1, 't8'); lw('ra', 4, 'sp'); jr('ra'); lw('a0', 8, 'sp')
    # ---- bit(a1 = column) -> at = 1 if that column is covered. Uses t3. Leaf (bal).
    lab('bit'); lw('t3', MASK0, 't8'); slti('at', 'a1', 32); bne('at', 'zero', 'bt1'); nop(); lw('t3', MASK1, 't8')
    lab('bt1'); srlv('t3', 't3', 'a1'); jr('ra'); andi('at', 't3', 1)
    # ---- look(a0 = node, t8 = &vars): find the next real primitive; decide squeeze + bias for it. Frame: 32 bytes,
    # 0(sp) = ra, 4..16(sp) used by prescan.
    lab('look'); addiu('sp', 'sp', -32); sw('ra', 0, 'sp')
    # t6 = segment 1 + 0x508000, t7 = segment 1 + 0x15AD50 (Screen flag; the draw offset x is the halfword at
    # t7 + 8). t5 = *(segment 1 + 0x500800), the ordering-table structure; t0 / t1 = the words at segment 1 +
    # 0x509668 / 0x509678 that DrawOTag's own next-node rule uses; t2 = 0xFFFFFF; t4 = the current zone.
    la('t6', 't8', seg1 + 0x508000, 'vars'); la('t7', 't8', seg1 + 0x15AD50, 'vars')
    lw('t5', -0x7800, 't6'); lw('t0', 0x1668, 't6'); lw('t1', 0x1678, 't6'); lui('t2', 0xFF); ori('t2', 't2', 0xFFFF); lw('t4', ZONE, 't8')
    # Next node (same pointer rule as in prescan). v0 = its offset in the ordering-table structure: passing the
    # +0x80 / +0x7C / +0x78 / +0x74 slot nodes sets W80 / zone 1 / zone 2 (and runs prescan) / zone 3. Nodes with
    # length 0 are skipped; the first real primitive is the one decided on.
    lab('lk'); lw('v0', 0, 'a0'); and_('v1', 'v0', 't2'); beq('v1', 't2', 'lk_end'); sltu('at', 'v1', 't0')
    beq('at', 'zero', 'lk1'); addu('a1', 't1', 'zero'); lui('at', 0x100); addu('a1', 'a1', 'at')
    lab('lk1'); or_('a0', 'v1', 'a1'); and_('at', 'a0', 't2'); beq('at', 'zero', 'lk_end'); subu('v0', 'a0', 't5')
    addiu('at', 'zero', 0x80); bne('v0', 'at', 'z0'); nop(); addiu('at', 'zero', 1); sw('at', W80, 't8')         # the world slot starts
    lab('z0'); addiu('at', 'zero', 0x7C); bne('v0', 'at', 'z1'); nop(); addiu('t4', 'zero', 1)
    lab('z1'); addiu('at', 'zero', 0x78); bne('v0', 'at', 'z2'); nop(); addiu('t4', 'zero', 2); bal('prescan'); nop(); subu('v0', 'a0', 't5')
    lab('z2'); addiu('at', 'zero', 0x74); bne('v0', 'at', 'z3'); nop(); addiu('t4', 'zero', 3)
    lab('z3'); lbu('v0', 3, 'a0'); beq('v0', 'zero', 'lk'); nop()
    # a2 = squeeze (0 / 1), a3 = bias. Zone 0 (backdrops, world): never squeezed; after the world slot node it is
    # a world primitive, remembered in WORLD.
    sw('t4', ZONE, 't8'); bne('t4', 'zero', 'dec'); addu('a2', 'zero', 'zero')
    lw('at', W80, 't8'); beq('at', 'zero', 'apply'); nop(); addiu('at', 'zero', 1); b('apply'); sw('at', WORLD, 't8')   # a world primitive exists
    lab('dec'); lw('v0', 0, 't7'); bne('v0', 'zero', 'apply'); nop()                                           # Screen = Original: nothing
    lw('at', HUDOFF, 't8'); bne('at', 'zero', 'apply'); nop()                                                  # switched off with Triangle: nothing
    if int(edges) & 2:
        # 'hudonly' variant (these 6 instructions exist only in it): squeeze nothing but the HUD slot, and that only
        # while a world is drawn. Windows, text, subtitles (slot +0x7C), the front slot and whole-screen menus keep the
        # game's own stretched proportions, so text stays as legible as in the original. a2 is still 0 (no squeeze).
        addiu('at', 'zero', 2); bne('t4', 'at', 'apply'); nop(); lw('at', WORLD, 't8'); beq('at', 'zero', 'apply'); nop()
    # 2D zones in Wide: default bias = centre. Commands other than E3 (code >= 0x80: draw mode, offset, ...)
    # have no extent: squeeze state on, centred. Primitives and E3 go through extent.
    addiu('a3', 'zero', CENTER); lbu('v0', 7, 'a0')
    sltiu('at', 'v0', 0x80); bne('at', 'zero', 'dx'); nop(); addiu('at', 'zero', 0xE3); beq('v0', 'at', 'dx'); nop()
    b('apply'); addiu('a2', 'zero', 1)                                                                       # other commands: squeeze state on
    lab('dx'); bal('extent'); nop()
    slti('at', 't3', FULL); beq('at', 'zero', 'apply'); nop()                                                 # full width: leave alone
    addiu('a2', 'zero', 1); addiu('at', 'zero', 2); bne('t4', 'at', 'apply'); nop()                           # not the HUD slot: centre
    # HUD slot: find the run of covered columns this piece belongs to. v0 = its first column L, v1 = its last R.
    sra('v0', 'v1', 3); slt('at', 'v0', 'zero'); beq('at', 'zero', 'r0'); nop(); addu('v0', 'zero', 'zero')
    lab('r0'); slti('at', 'v0', CELLS); bne('at', 'zero', 'r1'); nop(); addiu('v0', 'zero', CELLS - 1)
    lab('r1'); addu('v1', 'v0', 'zero')
    lab('rl'); beq('v0', 'zero', 'rr'); addiu('a1', 'v0', -1); bal('bit'); nop(); beq('at', 'zero', 'rr'); nop(); b('rl'); addu('v0', 'a1', 'zero')
    lab('rr'); addiu('at', 'zero', CELLS - 1); beq('v1', 'at', 'dz'); addiu('a1', 'v1', 1); bal('bit'); nop(); beq('at', 'zero', 'dz'); nop(); b('rr'); addu('v1', 'a1', 'zero')
    # Decision for the run (a2 = 1, a3 = CENTER so far):
    #   covers every column (tiled overlay)                              -> not squeezed
    #   no world drawn (menus)                                           -> centred
    #   starts in the left band and stays out of the right band: 'left';  ends in the right band and starts
    #   right of the left band: 'right';  anything else (banners, the title line) -> centred
    #   left / right and more than PANEL columns wide (a panel that frames world-drawn content, e.g. the weapon
    #   preview on the development screen)                                -> not squeezed
    #   left / right with edge anchoring (EDGES bit 0)                    -> bias 0 / RIGHT; without it centred
    lab('dz'); bne('v0', 'zero', 'dz1'); addiu('at', 'zero', CELLS - 1); bne('v1', 'at', 'dz1'); nop(); b('apply'); addu('a2', 'zero', 'zero')
    lab('dz1'); lw('at', WORLD, 't8'); beq('at', 'zero', 'apply'); nop()
    slti('at', 'v0', LEFT_MAX // 8); beq('at', 'zero', 'dzr'); nop()
    slti('at', 'v1', RIGHT_MIN // 8); beq('at', 'zero', 'apply'); nop()
    b('dzw'); addu('t3', 'zero', 'zero')
    lab('dzr'); slti('at', 'v1', RIGHT_MIN // 8); bne('at', 'zero', 'apply'); nop(); addiu('t3', 'zero', RIGHT)
    lab('dzw'); subu('at', 'v1', 'v0'); slti('at', 'at', PANEL); bne('at', 'zero', 'dzb'); nop(); b('apply'); addu('a2', 'zero', 'zero')
    lab('dzb'); lw('at', EDGES, 't8'); andi('at', 'at', 1); beq('at', 'zero', 'apply'); nop(); b('apply'); addu('a3', 't3', 'zero')
    lab('lk_end'); addu('a2', 'zero', 'zero')
    # apply: v1 = draw offset x; take out the bias added for the previous primitive (if BIASED), add the new one
    # when squeezing (BIASV = a3, BIASED = 1), store the offset back, MODEV = a2. lk_end (list finished): squeeze off.
    lab('apply'); lw('v0', BIASED, 't8'); beq('v0', 'zero', 'ap1'); lhu('v1', 8, 't7'); lw('at', BIASV, 't8'); subu('v1', 'v1', 'at')
    lab('ap1'); beq('a2', 'zero', 'ap2'); sw('zero', BIASED, 't8'); addu('v1', 'v1', 'a3'); sw('a3', BIASV, 't8'); addiu('at', 'zero', 1); sw('at', BIASED, 't8')
    lab('ap2'); sh('v1', 8, 't7'); sw('a2', MODEV, 't8'); lw('ra', 0, 'sp'); jr('ra'); addiu('sp', 'sp', 32)
    # ---- start hook (replaces the call of 0x2172E0 in DrawOTag; s0 = list head)
    # Calls the original 0x2172E0 (address built PC-relative from label s1), clears the per-frame state words
    # (all but BIASV and EDGES), then looks ahead from the list head.
    lab('start'); addiu('sp', 'sp', -16); sw('ra', 0, 'sp'); bal('s1'); nop()
    lab('s1'); la('t7', 'ra', START_OLD, 's1'); jalr('t7'); nop(); bal('s2'); nop()
    lab('s2'); addiu('t8', 'ra', V(0, 's2')); sw('zero', MODEV, 't8'); sw('zero', BIASED, 't8'); sw('zero', ZONE, 't8'); sw('zero', W80, 't8'); sw('zero', WORLD, 't8'); sw('zero', MASK0, 't8'); sw('zero', MASK1, 't8')
    bal('look'); addu('a0', 's0', 'zero'); lw('ra', 0, 'sp'); jr('ra'); addiu('sp', 'sp', 16)
    # ---- post hook (replaces the call of 0x2212D8 after each primitive; s0 = the primitive just drawn)
    # t9 = return address. If the primitive just drawn was E5 (set draw offset) the game has rewritten the offset,
    # so the bias is no longer in it: BIASED = 0. Then look ahead from s0, and continue in the original 0x2212D8
    # with the caller's ra (tail jump).
    lab('post'); addu('t9', 'ra', 'zero'); bal('q1'); nop()
    lab('q1'); addiu('t8', 'ra', V(0, 'q1')); lbu('v0', 7, 's0'); addiu('at', 'zero', 0xE5); bne('v0', 'at', 'q2'); nop(); sw('zero', BIASED, 't8')
    lab('q2'); bal('look'); addu('a0', 's0', 'zero'); bal('q3'); nop()
    lab('q3'); la('t7', 'ra', POST_OLD, 'q3'); addu('ra', 't9', 'zero'); jr('t7'); nop()
    # ---- end hook (replaces the call of 0x217530, the paste, at the end of the list)
    # Squeeze off; if a bias is still in the draw offset, take it out; then continue in the original 0x217530
    # (tail jump).
    lab('end'); addu('t9', 'ra', 'zero'); bal('e1'); nop()
    lab('e1'); addiu('t8', 'ra', V(0, 'e1')); lw('v0', BIASED, 't8'); beq('v0', 'zero', 'e2'); sw('zero', MODEV, 't8')
    la('t7', 't8', seg1 + 0x15AD58, 'vars'); lhu('v1', 0, 't7'); lw('at', BIASV, 't8'); subu('v1', 'v1', 'at'); sh('v1', 0, 't7'); sw('zero', BIASED, 't8')
    lab('e2'); bal('e3'); nop()
    lab('e3'); la('t7', 'ra', END_OLD, 'e3'); addu('ra', 't9', 'zero'); jr('t7'); nop()
    # the 10 state words (see MODEV .. MASK1 above); only EDGES has a non-zero initial value
    if strings:
        # ---- opt: replaces 'jal 0x3C00C' in the options handler. In: a0, a1 (string), a2 = the call's arguments,
        # s0 = window context, ra = return into the handler. Uses at, v0, v1, t7-t9; a 16-byte frame around the sound call.
        lab('opt'); addu('t9', 'ra', 'zero'); bal('o1'); nop()
        lab('o1'); addiu('t8', 'ra', V(0, 'o1')); la('t7', 'ra', seg1 + SYSMSG_TABLE + 4 * WIDE_HELP, 'o1'); lw('t7', 0, 't7')
        bne('a1', 't7', 'o_pass'); nop()                                         # not the Screen = Wide help text
        lhu('v0', 0xBA, 's0'); andi('v1', 'v0', 0x1000); beq('v1', 'zero', 'o_sel'); nop()   # Triangle newly pressed?
        lw('v1', HUDOFF, 't8'); xori('v1', 'v1', 1); sw('v1', HUDOFF, 't8'); andi('v0', 'v0', 0xEFFF); sh('v0', 0xBA, 's0')
        addiu('sp', 'sp', -16); sw('a0', 0, 'sp'); sw('a2', 4, 'sp'); sw('t9', 8, 'sp'); sw('t8', 12, 'sp')
        la('t7', 'ra', SND_FN, 'o1'); addiu('a0', 'zero', 0x82); addiu('a1', 'zero', 1); jalr('t7'); addu('a2', 'zero', 'zero')
        lw('a0', 0, 'sp'); lw('a2', 4, 'sp'); lw('t9', 8, 'sp'); lw('t8', 12, 'sp'); addiu('sp', 'sp', 16)
        lab('o_sel'); bal('o2'); nop()
        lab('o2'); lw('v1', HUDOFF, 't8'); la('a1', 'ra', 'str_on', 'o2'); beq('v1', 'zero', 'o_go'); nop(); la('a1', 'ra', 'str_off', 'o2')
        lab('o_go'); la('t7', 'ra', OPT_OLD, 'o2'); addu('ra', 't9', 'zero'); jr('t7'); nop()
        lab('o_pass'); bal('o3'); nop()
        lab('o3'); la('t7', 'ra', OPT_OLD, 'o3'); addu('ra', 't9', 'zero'); jr('t7'); nop()
        for name, data in zip(('str_on', 'str_off'), strings):                  # the two help strings, as data words
            lab(name); data = data + b'\0' * (-len(data) % 4)
            for k in range(0, len(data), 4): emit(lambda pc, w=struct.unpack_from('<I', data, k)[0]: w)
    lab('vars'); [emit(lambda pc: 0) for _ in range(4)]; emit(lambda pc: int(edges)); [emit(lambda pc: 0) for _ in range(5)]
    return [f(origin + 4 * k) & 0xFFFFFFFF for k, f in enumerate(prog)], L
def hint_strings(d, ph):
    """The Screen = Wide help string (system message 242, already English in segment 2) with a second row added:
    newline, PAD 6, the triangle glyph (PSP code 0xFE) and label in colour 3, the value in colour 0.
    -> (on, off) as PSP MSG bytes ending in the END op (0x95 + 0x2EE) and a zero unit."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import msgtool as M
    TBL = {}
    for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
        k, v = l.rstrip('\n').split('=', 1)
        if len(v) == 1: TBL.setdefault(v, int(k, 16))
    codes = lambda t: [0x1A6 if ch == ' ' else M.PS1_TO_PSP_CHAR.get(TBL[ch], TBL[ch]) for ch in t]
    u16 = lambda *v: struct.pack(f'<{len(v)}H', *v)
    off = struct.unpack_from('<I', d, BASE + ph[1][2] + SYSMSG_TABLE + 4 * WIDE_HELP)[0]; s = bytes(d[ph[2][1] + off: ph[2][1] + off + 400])
    tail = u16(0x378) + b'\x01\x00' + u16(0x383)                               # op 8A 01 00, END: where the text stops
    k = s.index(tail); assert k % 2 == 0 and s[:2] == u16(0x38F), 'help string 242 not as expected'
    # row: newline, PAD 6, colour 3 (the light green of the ATK / ENG / ... labels in the weapon development text),
    # triangle glyph + label, colour 0, the value
    row = lambda t: (u16(0x374, 0x38E) + b'\x06\x00' + u16(0x377) + b'\x03\x00' + u16(0xFE, *codes(HINT_LABEL))
                     + u16(0x377) + b'\x00\x00' + u16(*codes(t)))
    return tuple(s[:k] + row(t) + tail + u16(0) for t in HINT)
def main():
    MODE = sys.argv[1] if len(sys.argv) > 1 else 'off'; assert MODE in ('off', 'center', 'edges', 'hudonly')
    if MODE == 'off':
        json.dump(dict(mode='off'), open(REP, 'w')); print('wide HUD: off'); return
    d = bytearray(open(P, 'rb').read())
    phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C); assert phnum == 3, 'segment 2 expected (run after build_savetext.py)'
    ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
    def r32(va): return struct.unpack_from('<I', d, BASE + va)[0]
    # jal encoding (opcode 3, target >> 2)
    jal = lambda to: 0x0C000000 | (to >> 2)
    # Sony's code relocation table (file offset 0x325018, 0x9F3D8 bytes; 8-byte entries offset + info): rel maps a
    # code address to its info word. 4 = R_MIPS_26 with both segment bases 0: a jal whose target the loader rebases,
    # so a retargeted jal stays a valid relocated call
    o = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8]
    rel = {struct.unpack_from('<I', o, k)[0]: struct.unpack_from('<I', o, k + 4)[0] for k in range(0, len(o), 8)}
    # the x-scale function as expected: sll v0,a0,1 ; jr ra ; seh v0,v0
    assert (r32(F_OLD), r32(F_OLD + 4), r32(F_OLD + 8)) == (0x00041040, 0x03E00008, 0x7C021620), 'x-scale function not as expected'
    # the new code goes at the end of segment 2 (word-aligned); origin = its virtual address
    seg2 = bytearray(d[ph[2][1]:ph[2][1] + ph[2][4]])
    while len(seg2) % 4: seg2 += b'\0'
    origin = ph[2][2] + len(seg2); strings = hint_strings(d, ph); code, L = assemble(origin, ph[1][2], FLAGS[MODE], strings); seg2 += struct.pack(f'<{len(code)}I', *code)
    words = {}
    # every retargeted word must be the expected `jal old` and carry a jal relocation
    def w32(va, old, new):
        assert r32(va) == old and rel.get(va) == 4, ('not the expected relocated jal', hex(va), hex(r32(va)), rel.get(va))
        words[va] = [old, new]; struct.pack_into('<I', d, BASE + va, new)
    for va in F_SITES: w32(va, jal(F_OLD), jal(L['f']))
    for va in FPOS_SITES: w32(va, jal(F_OLD), jal(L['fpos']))
    w32(OPT_SITE, jal(OPT_OLD), jal(L['opt'])); w32(START_SITE, jal(START_OLD), jal(L['start'])); w32(POST_SITE, jal(POST_OLD), jal(L['post'])); w32(END_SITE, jal(END_OLD), jal(L['end']))
    ph[2][6] |= 1                                              # segment 2 also holds code now (flags + X)
    # write segment 2 back (the last thing in the file before the program headers, build_sysmsg.py's layout) and
    # rewrite the three program headers after it; e_phoff (ELF header 0x1C) points at them
    while len(seg2) % 16: seg2 += b'\0'
    del d[ph[2][1]:]; d += seg2; ph[2][4] = ph[2][5] = len(seg2)
    while len(d) % 4: d += b'\0'
    new_phoff = len(d)
    for p in ph: d += struct.pack('<8I', *p)
    struct.pack_into('<I', d, 0x1C, new_phoff); open(P, 'wb').write(d)
    json.dump(dict(mode=MODE, strings=[x.hex() for x in strings], origin=origin, size=4 * len(code), code=struct.pack(f'<{len(code)}I', *code).hex(),
                   labels={k: v for k, v in L.items() if k in ('f', 'fpos', 'look', 'start', 'post', 'end', 'vars', 'opt', 'str_on', 'str_off')},
                   words={hex(k): [hex(a), hex(b_)] for k, (a, b_) in sorted(words.items())}), open(REP, 'w'), indent=1)
    print(f'wide HUD ({MODE}): {len(code)} words of code+state at {origin:#x}, {len(words)} calls retargeted')
if __name__ == '__main__': main()
