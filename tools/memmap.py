"""Text-buffer relocation table: where the three dialogue buffers are moved to, and every code site that names them.
Imported by tools/patch_eboot.py (rewrites the code), tools/pack_inplace.py (rewrites the load addresses in the data
files, enforces the size limits) and the checks (tools/checks/verify_headers.py, savestate_check.py, audit_eboot.py).
No input or output of its own. Reference: docs/RESEARCH.md §6.

Why buffers move. The PSP stores text as 16 bits per character, so the PS1 English script roughly doubles in size and
37 of the 129 dialogue files no longer fit where the Japanese ones load:
  - stage text: every stage's MSG loads at 0x80157000; the game's event-flag bit arrays start at 0x8015BC00, so the
    room is 0x4C00 (19,456) bytes. 33 English stage files are 22-36 KB.
  - support-car text (SUPPORT / SUPPORT2 STFF_FD.MSG) at 0x801E4000: about 28 KB of room, English 47.5 KB.
  - pause / sub-screen text (SUB_KEY / SUB_WPN STFF_FE.MSG) at 0x801F2000: about 21 KB of room, English 23.7 KB.

The memory model (static analysis of the EBOOT, 2026-09-29). The PSP version is a native port that keeps the PS1's
2 MB of RAM as one array inside its own data, and the data files still carry PS1 addresses (0x80xxxxxx) as load
addresses in their entry headers (+0x0C). A PS1 address p lives at
    segment 1 (vaddr 0x245200) + 0x2D2900 + (p - 0x80000000)        (= vaddr 0x517B00 + offset)
Code reaches a buffer with a lui / low-half pair whose immediates the loader relocates against segment 1, so the
constant stored in the instructions is 0x2D2900 + offset (rel_const). Example: the stage buffer 0x80157000 is
0x429900 = "lui a1,0x43; addiu a1,a1,-0x6700" at 0x3C1E4 / 0x3C1F4. The mapping was found by matching code constants
against the load addresses in the container headers. Other variables follow directly after the array, so it cannot
simply be made bigger.

Where they move to: the PS1 program area, 0x80040100-0x800D9B00 (FREE). On the PS1 the executable itself sat there;
the PSP runs native code, and this part of the array is never used. Evidence:
  - static: no code reference (dataflow over every LO16 relocation; the first referenced address is 0x800D9B00) and no
    relocated data pointer into it;
  - save states: all zero in every PPSSPP save state taken from the original Japanese game (pause menu, Apple Market,
    junk shop, ruins, boss fight, cutscene; research/savestate_check.py re-checks any set of states);
  - play: long test play with all three buffers there.
A first attempt used 0x801B4E28-0x801D8000, which also has no code references; but the save states show the game using
0x801B8000-0x801C5B00 as working memory during stages, and stage text placed there crashed as soon as it loaded. "No
static reference" alone is not proof that RAM is free - hence the save-state check.

What must change for a move, and who does it:
  - every instruction pair that builds the old base address (SITES; tools/patch_eboot.py changes the two immediates);
  - the load address in the entry header of every MSG that loads at an old address, Japanese or English
    (tools/pack_inplace.py, from MOVED);
Nothing else points into the buffers: the code only ever forms the base address and passes it to the text opener
(0x3C00C), and the files are loaded by their headers.
Project decisions: pause text move 2026-09-29; stage and support-car text 2026-09-29."""
def rel_const(ps1):             # PS1 address -> the segment-1-relative constant the code builds: 0x2D2900 + offset
    return 0x2D2900 + (ps1 - 0x80000000)
def hi_lo(v):                   # split into lui immediate and low half; the low half is sign-extended when used, so
                                # the high half is one more when bit 15 of the low half is set (MIPS %hi / %lo)
    lo = v & 0xFFFF; hi = (v >> 16) + (1 if lo & 0x8000 else 0)
    return hi & 0xFFFF, lo

# name: (old address, new address, byte limit at the new address). The limits are the space reserved for each
# buffer inside FREE (the three ranges are consecutive); a MSG can never exceed 0xFFFF bytes anyway (u16 offsets).
MOVES = {
    'stage':   (0x80157000, 0x80060000, 0x10000),  # largest English stage MSG 35,756 bytes
    'support': (0x801E4000, 0x80070000, 0x10000),  # SUPPORT STFF_FD 47,548 bytes
    'submsg':  (0x801F2000, 0x80080000, 0x8000),   # STFF_FE 23,756 bytes
}
FREE = (0x80040100, 0x800D9B00)                    # the PS1 program area, unused on the PSP (see above)
# Code sites, as vaddr in .text (file offset = vaddr + 0x80): 'hi' = the lui instructions, 'lo' = the instructions
# carrying the low 16 bits (addiu, or a load/store offset). One lui can serve several lo sites, so the lists differ in
# length. Found by research/msg_base_refs.py, which follows each LO16 site's base register back to its lui
# through straight-line code and branches; all are clean (the register comes only from the matching lui, nothing
# else uses it). Counts: stage 1 / 1, support 24 / 24, pause 53 lo / 37 hi.
SITES = {
    'stage':   dict(lo=[0x3C1F4], hi=[0x3C1E4]),
    'support': dict(lo=[0x4FAD0, 0x4FB64, 0x50024, 0x503B4, 0x5043C, 0x50688, 0x50A98, 0x50B68, 0x50CD8, 0x50D40, 0x50E80,
                        0x50EB4, 0x50F3C, 0x51F94, 0x51FD8, 0x520C4, 0x52148, 0x521D4, 0x52388, 0x524DC, 0x524FC, 0x52830,
                        0x52A6C, 0x52D78],
                    hi=[0x4FAC8, 0x4FB60, 0x5001C, 0x503B0, 0x50438, 0x50684, 0x50A94, 0x50B58, 0x50CD4, 0x50D3C, 0x50E7C,
                        0x50EB0, 0x50F34, 0x51F84, 0x51FD4, 0x520BC, 0x52140, 0x521D0, 0x52228, 0x52384, 0x524D8, 0x5282C,
                        0x52A68, 0x52D74]),
    # pause code (0x47600-0x49100). One more pair builds 0x801F2000, at 0x1CC9C/0x1CCAC, and is deliberately not
    # listed: it passes the address to the EBD handler for SUPPORT.EBD, which still loads there
    'submsg':  dict(lo=[0x47604, 0x476f4, 0x47714, 0x4778c, 0x4779c, 0x477bc, 0x477dc, 0x477ec, 0x47808, 0x4781c, 0x47890,
                        0x478b8, 0x478e8, 0x47910, 0x47b18, 0x47c0c, 0x47c30, 0x47c5c, 0x47cc8, 0x47d04, 0x47e18, 0x47e34,
                        0x47e64, 0x47e74, 0x47e98, 0x47ea8, 0x47ecc, 0x47edc, 0x47f68, 0x47f94, 0x47fc8, 0x47fe0, 0x48034,
                        0x4805c, 0x48084, 0x480a8, 0x48150, 0x48184, 0x48248, 0x482f4, 0x48374, 0x48390, 0x483b0, 0x486dc,
                        0x48868, 0x48d68, 0x48dac, 0x48e1c, 0x48ed4, 0x48ef0, 0x48f1c, 0x48f54, 0x49054],
                    hi=[0x47600, 0x476f0, 0x47770, 0x47788, 0x477d8, 0x47804, 0x47818, 0x4785c, 0x47874, 0x47880, 0x478e0,
                        0x47b14, 0x47bf4, 0x47c08, 0x47c58, 0x47cc4, 0x47e14, 0x47e60, 0x47e94, 0x47ec8, 0x47f64, 0x47fc4,
                        0x48030, 0x48080, 0x4814c, 0x4823c, 0x482f0, 0x48370, 0x4838c, 0x483ac, 0x486d8, 0x48860, 0x48d64,
                        0x48ec8, 0x48ee0, 0x48eec, 0x49050]),
}
MOVED = {old: new for old, new, _ in MOVES.values()}            # old load address -> new
LIMITS = {new: lim for _, new, lim in MOVES.values()}
# the pause-text move under its earlier names, still imported by other tools
SUBMSG_OLD, SUBMSG_NEW, SUBMSG_LIMIT = MOVES['submsg']
# sanity: new ranges inside the free block and not overlapping
_r = sorted((new, new + lim) for _, new, lim in MOVES.values())
assert _r[0][0] >= FREE[0] and _r[-1][1] <= FREE[1] and all(a[1] <= b[0] for a, b in zip(_r, _r[1:])), _r
