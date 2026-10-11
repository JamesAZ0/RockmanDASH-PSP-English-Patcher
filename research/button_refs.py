"""Research tool (not run by the build; read-only): list every English PS1 dialogue block that names a shoulder button,
next to the Japanese PSP block at the same position, so the two games' button wording can be compared.

Why: the PS1 pad has L1 / L2 / R1 / R2, the PSP only L and R, and the PSP version changed its controls and its help
text accordingly. The PS1 text uses button glyphs (PS1 character codes 0x58-0x5B = L1, L2, R1, R2). This list was the
basis for the approved formatting rule now in tools/msgtool.py: the R2 glyph becomes the three glyphs L+R, L1 becomes
L and R1 becomes R (docs/RESEARCH.md §3, §4).

Reads:  extracted/ps1/**.msg and extracted/psp/**.msg (from tools/extract.py; the same relative path on both sides),
        script/ps1_charmap.tbl (PS1 character table), tools/jptable.py (PSP kana/kanji table).
Writes: logs/button_refs.md - one section per English block: file, block number, the English text and the Japanese
        text (button glyphs shown as <L1> etc.). Prints the number of blocks found.

Usage: python3 research/button_refs.py"""
import sys, os, glob; sys.path.insert(0, 'tools'); import msgtool as M; from jptable import T
# EN: PS1 character code (two hex digits in the table file) -> character
EN = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8', errors='replace'):
    if '=' in l and len(l.split('=')[0]) == 2:
        k, v = l.rstrip('\n').split('=', 1); EN[int(k, 16)] = v
# PSP glyph codes of the button and hand icons (the PS1 codes 0x54-0x62 moved up by 0xA9)
SYM = {0xFD:'<CIRCLE>',0xFE:'<TRIANGLE>',0xFF:'<CROSS>',0x100:'<SQUARE>',0x101:'<L1>',0x102:'<L2>',0x103:'<R1>',0x104:'<R2>',0x109:'<HAND>'}
# en / jp: a block as readable text. 0x86 = newline; PS1 0xED = the choice-cursor slot, shown as ">"
def en(b):
    t,_ = M.parse(b, False); s = ''
    for x in t:
        if x[0] == 'c': s += '\\n' if x[1] == 0x86 else EN.get(x[1], '{%02X}' % x[1])
        elif x[1] in (0xED,): s += '>'
    return s
def jp(b):
    t,_ = M.parse(b, True, True); s = ''
    for x in t:
        if x[0] == 'c':
            c = x[1]; s += '\\n' if c == 0x86 else SYM.get(c, T.get(c, '{%X}' % c))
    return s
out = ['# L1/L2/R1/R2 references: English PS1 vs Japanese PSP (same block index)', '']
n = 0
for p in sorted(glob.glob('extracted/ps1/**/*.*', recursive=True)):
    if not p.lower().endswith('.msg'): continue
    q = 'extracted/psp' + p[len('extracted/ps1'):]
    if not os.path.exists(q): out.append(f'- {p}: no PSP counterpart'); continue
    eb,_ = M.blocks(open(p,'rb').read()); jb,_ = M.blocks(open(q,'rb').read())
    for i, b in enumerate(eb):
        # quick byte test first, then a real parse so that argument bytes with these values are not counted
        if not any(c in b for c in b'\x58\x59\x5a\x5b'): continue
        t,_ = M.parse(b, False)
        if not any(x[0]=='c' and 0x58 <= x[1] <= 0x5B for x in t): continue
        n += 1
        out += [f'## {p[len("extracted/ps1/"):]} block {i:02X}', f'- EN: `{en(b)}`',
                f'- JP: `{jp(jb[i]) if i < len(jb) else "(none)"}`', '']
out.insert(1, f'{n} English blocks use L1/L2/R1/R2.\n')
open('logs/button_refs.md','w').write('\n'.join(out)); print(n)
