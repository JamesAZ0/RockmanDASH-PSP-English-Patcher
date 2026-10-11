"""Research tool (not run by the build; read-only): map the program's system-message table - menus, save screens, options,
item / part / weapon names, help lines - to the PS1 English strings. This is the analysis that tools/build_sysmsg.py
was built on (docs/RESEARCH.md §7).

PSP (JP): 248 relocated pointers at .data vaddr 0x25451C -> MSG-format 16-bit strings at 0x25205C-0x254520.
          (The program is relocatable: a stored pointer is segment-relative, absolute = value + 0x245200 for
          segment 1; which segment applies is read from the pointer's relocation entry.)
PS1 (US): 242 pointers at 0x8008CACC in ROCK_NEO.EXE -> 8-bit strings at 0x8008AF48-0x8008CACC.
Entries 0-241 correspond one to one (same order); 242-247 are PSP additions.
A string ends at its first 0x91 (return), 0x95 or 0x84 (close) op.

Reads:  decrypted_eboot/ULJM05030_EBOOT.BIN, extracted/ps1/ROCK_NEO.EXE, script/ps1_charmap.tbl (PS1 character table),
        tools/jptable.py (PSP kana / kanji table; the Japanese column is a provisional decode).
Writes: logs/system_strings_map.md - per entry the Japanese text, the PS1 English, a proposal (use the PS1 English, or
        keep Japanese with the reason) and the byte sizes of both.
Note:   the proposal column (KEEP below) records the first proposal of 2026-09-29. The build went further: the options
        screen and the other PSP-specific lines got approved English wording in script/sysmsg_rules.json, and only
        entry 1 (the control legend of an unused developer screen) stays Japanese.

Usage: python3 research/system_strings.py"""
import sys, struct, collections
sys.path.insert(0, 'tools'); import msgtool as M; from jptable import T
E = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read(); X = open('extracted/ps1/ROCK_NEO.EXE', 'rb').read()
# SEG = vaddr of segment 0 and segment 1
SEG = [0, 0x245200]
# the relocation entries for data (.rel.data: file offset 0x3CF6D0, 0x1E6F0 bytes; 8 bytes each: offset, info). PTR:
# vaddr of a relocated word -> the vaddr it points to. (info >> 8) & 0xFF = segment the offset is relative to, (info
# >> 16) & 0xFF = segment the stored value is relative to; file offset = vaddr + 0x80
rel = [struct.unpack_from('<II', E, 0x3cf6d0 + 8*k) for k in range(0x1e6f0 // 8)]
PTR = {o + SEG[(i >> 8) & 0xff]: struct.unpack_from('<I', E, o + SEG[(i >> 8) & 0xff] + 0x80)[0] + SEG[(i >> 16) & 0xff] for o, i in rel}
# pt = the 248 PSP string addresses; qt = the 242 PS1 string addresses (PS1 file offset = address - 0x80010000 +
# 0x800)
pt = [PTR[a] for a in range(0x25451C, 0x25451C + 4*248, 4)]
qt = [struct.unpack_from('<I', X, a - 0x80010000 + 0x800)[0] for a in range(0x8008CACC, 0x8008CACC + 4*242, 4)]
EN = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8', errors='replace'):
    if '=' in l and len(l.split('=')[0]) == 2: k, v = l.rstrip('\n').split('=', 1); EN[int(k, 16)] = v
# PSP glyph codes of the symbols (buttons, punctuation, hand, +, %); 0x10C = the empty cursor-slot glyph
SYM = {0xFD:'○',0xFE:'△',0xFF:'×',0x100:'□',0x101:'[L1]',0x102:'[L2]',0x103:'[R1]',0x104:'[R2]',0x105:',',0x106:'"',0x107:'.',0x108:'…',0x109:'☞',0x10A:'+',0x10B:'%',0x10C:''}
ENDS = {0x91, 0x95, 0x84}
# cut: tokens up to and including the first end op. psp / ps1: parse the string at an address (4000 / 3000 bytes is
# more than any string needs). txt: tokens as readable text, "/" for a newline
def cut(t):
    for k, x in enumerate(t):
        if x[0] == 'op' and x[1] in ENDS: return t[:k+1]
def psp(v): return cut(M.parse(E[v+0x80: v+0x80+4000], True, True)[0])
def ps1(v): o = v - 0x80010000 + 0x800; return cut(M.parse(X[o:o+3000], False)[0])
def txt(t, wide):
    s = ''
    for x in t:
        if x[0] == 'c':
            c = x[1]
            s += '/' if c == 0x86 else (SYM.get(c, T.get(c, '{%X}' % c)) if wide else ('' if c == 0xED else {0x58:'[L1]',0x59:'[L2]',0x5A:'[R1]',0x5B:'[R2]'}.get(c, EN.get(c, '{%X}' % c))))
        elif x[1] == 0xA0: s += ' '          # PAD (spacing)
        elif x[1] == 0x96: s += ' '          # choice
    return s.strip()
# first proposal (2026-09-29; superseded, see the docstring): entries to keep Japanese, with the reason
KEEP = {1: 'PSP control legend differs', 38: 'PSP options screen layout differs', 41: 'PSP: analog-pad camera text', 42: 'PSP: analog-pad camera text',
        43: 'PSP: camera/analog option (PS1: stereo/mono)', 44: 'PSP: camera/analog option (PS1: stereo/mono)', 49: 'PSP: screen-size option (PS1: close options)'}
# lj / le = size in bytes of the Japanese string and of the PS1 English converted to PSP format; strings shared by
# several slots are counted once in the totals
rows = []; jpb = enb = 0; seen = set()
for i, v in enumerate(pt):
    tj = psp(v); lj = len(M.tokens_to_psp(tj))
    if i < 242:
        te = ps1(qt[i]); le = len(M.tokens_to_psp(te)); en = txt(te, False)
        act = 'keep JP (' + KEEP[i] + ')' if i in KEEP else 'use PS1 English'
    else: le = 0; en = '—'; act = 'keep JP (PSP-only line)'
    if v not in seen:
        seen.add(v); jpb += lj; enb += (le if act == 'use PS1 English' else lj)
    rows.append((i, txt(tj, True), en, act, lj, le))
L = ['# EBOOT system messages: PSP (JP) vs PS1 (US)', '', f'248 PSP entries, 242 PS1 entries (0-241 correspond). Space: JP strings {jpb - 0} bytes used in place; with the proposal {enb} bytes needed (region 9,412 bytes).', '',
     '| # | PSP (JP, provisional kana decode) | PS1 English | Proposal | JP bytes | EN bytes |', '|---|---|---|---|---|---|']
for r in rows: L.append('| %d | %s | %s | %s | %d | %d |' % (r[0], r[1].replace('|', '¦')[:110], r[2].replace('|', '¦')[:110], r[3], r[4], r[5]))
open('logs/system_strings_map.md', 'w').write('\n'.join(L) + '\n'); print(L[2])
