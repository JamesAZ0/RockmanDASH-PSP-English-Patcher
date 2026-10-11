"""English subtitles for the PSP-only subtitle scenes (cutscene streams, radio, TV news). Run by build.py when
--subtitle-language=en (the default), with English audio (--localization=audio|legends) and, since 2026-10-01, also
with Japanese audio (--localization=text): the same English lines and timings are used, since both dubs follow the
same cutscene animation (a few scenes differ in length; docs/RESEARCH.md §16). --subtitle-language=jp skips this
script and keeps the original tables. Runs after build_savetext.py and before tools/voice/patch_eboot_voice.py, in
place on build/eboot/ULJM05030_EBOOT_en.BIN. Report: logs/subtitles_report.json (read by verify_subtitles.py).
Source: script/subtitles_en.csv (research/subtitle_align.py + review): per scene the lines whose status isn't
'drop', text = en_final or text, time = time_override or start_s-end_s (seconds in the English clip; 30 frames/s).
Game side (EBOOT; found by reading the subtitle function and dumping its tables): subtitle function
0x449D0(scene, set) reads a scene's string table and timing table from three master arrays: set 0 (A) strings
va 0x2607E8 / timing 0x260878, set 1 0x260908 / 0x260998 (36 scenes each; the review files number B scenes from
set-1 index 2, whose first two slots hold no subtitles, so B nn uses slots 0x260910 / 0x2609A0 + 4*nn), set 2
(news C) 0x260A28 / 0x260A48 (8). A string table is a 0-terminated array of pointers to MSG-format strings; a timing
table is (start frame, duration) u16 pairs ended by 0xFFFF 0xFFFF.
For every English scene this appends a new timing table, string table and strings to segment 2 (build_sysmsg.py's added
data; the program headers after it are rewritten), points the two master slots at them (their existing R_MIPS_32
relocations retargeted to segment 2, like build_savetext.py) and adds one relocation per string pointer in a new
relocation section (a copy of .rel.data's header, like patch_eboot_voice.py; flatten_eboot.py folds it into .rel.data).
String format = the Japanese one, in PS1 opcode numbers (the PSP stores each as a 16-bit unit, opcode + 0x2EE):
8A 0000, 8C WIN (x 16, y 0xDC, 30 columns, 1 row; 2 rows: y 0xD0), text, 8A 0100, 95.
Slots that share a scene's original tables (A18 with A15, B27 with B26) are pointed at the same English tables.
Each row is centred on x = 160 like the Japanese lines (full-width 0x4F spaces + English 0x1A6 spaces in front);
2-row lines break with the newline code 0x374 (project decision, 2026-09-30: English timing, 2-row boxes allowed,
news scenes included). Rows are measured with the variable-width table tools/patch_eboot.py puts in the EBOOT.
See docs/RESEARCH.md §11 (subtitles), §3-§4 (MSG codes, text widths) and §5 (segments, relocations).
Usage: python3 tools/build_subtitles.py"""
import sys, os, csv, json, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import msgtool as M
# BASE: file offset of virtual address 0; SEG1: virtual address of segment 1 (.data); RELD_OFF: file offset of
# .rel.data, the data relocation section
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; SEG1 = 0x245200; RELD_OFF = 0x3CF6D0
# per set: (string-table master array, timing-table master array, number of scene slots); B's addresses already
# include the 2-slot shift
MASTER = {'A': (0x2607E8, 0x260878, 36), 'B': (0x260910, 0x2609A0, 34), 'C': (0x260A28, 0x260A48, 8)}   # B nn = set-1 index nn+2 (script/subtitles.csv numbering)
# ROW_PX: widest row in pixels, the limit subtitle_align.py packs lines to (= 320 - 2 x WIN_X; why this margin was
# chosen: origin not recorded). CENTRE: screen x the rows are centred on. WIN_X: the window's x, as the Japanese
ROW_PX = 288; CENTRE = 160; WIN_X = 16
# --box (internal argument, set by build.py for --subtitle-background=on): a dark band behind each subtitle, made from
# the game's own window box. The Japanese strings have no DECOR op (0x93), so no box is drawn; with --box a DECOR 04 04
# follows the WIN op, and the window starts at x 0 so that its 30 columns (12 px each) run past the right edge: the
# box spans the screen width.
# Decoration types 2 (the ordinary box, e.g. the help boxes) and 4 are drawn by the same code: a box from
# (x - m, y - m) to (x + 12 * columns + m, y + 12 * rows + m), m = DECOR's second byte (US handler 0x8005B85C). With
# x 0 and m 4 the left and right edges are off-screen; one extra window row takes the bottom edge below the screen as
# well (y 220 + 24 + 4 or 208 + 36 + 4 = 248 > 240), so the box reaches the bottom of the picture.
# Type 4 is used by nothing else in the game; tools/patch_subtitle_box.py makes the game draw type 4 without the
# one-pixel border, so the band has no white line along its top (2026-10-05, confirmed in play).
BOX = '--box' in sys.argv; BOX_TYPE = 4
if BOX: WIN_X = 0
d = bytearray(open(P, 'rb').read())
# ELF header: e_phoff 0x1C / e_phnum 0x2C (program headers, 8 u32 each: type, offset, vaddr, paddr, file size,
# memory size, flags, align); e_shoff 0x20 / e_shnum 0x30 (section headers, 10 u32 each: [1] type, [4] file
# offset, [5] size)
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
assert phnum == 3, 'run after build_sysmsg.py / build_savetext.py (segment 2 expected, before patch_eboot_voice.py)'
ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
sh = [list(struct.unpack_from('<10I', d, shoff + 40 * k)) for k in range(shnum)]
# 0x700000A0 = the PSP's relocation section type; reld = .rel.data's header, the template for the new section
reld = next(s for s in sh if s[1] == 0x700000A0 and s[4] == RELD_OFF)
# rel: {relocated virtual address: file offset of its 8-byte relocation entry (offset, info)}. info = type |
# offset base << 8 | address base << 16 (bases are segment numbers); an offset in segment 1 is made absolute
rel = {}
for s in sh:
    if s[1] != 0x700000A0: continue
    for k in range(s[5] // 8):
        o, i = struct.unpack_from('<II', d, s[4] + 8 * k); rel[o + (SEG1 if (i >> 8) & 0xFF == 1 else 0)] = s[4] + 8 * k
# The width table at va 0x226980, one byte per character code 0..0x1A6: high nibble = first ink column, low
# nibble = last column (+ the 1 px gap). Codes outside it are 12 px wide (0x0B)
VWF = d[BASE + 0x226980: BASE + 0x226980 + 0x1A7]
# TBL: character -> PS1 character code (script/ps1_charmap.tbl); codes() gives the PSP codes (symbols and the space are
# remapped by msgtool.PS1_TO_PSP_CHAR)
TBL = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: TBL.setdefault(v, int(k, 16))
def codes(s): return [M.PS1_TO_PSP_CHAR.get(TBL[ch], TBL[ch]) for ch in s]
# pixel width of a run of codes, as the text routine advances: (last column + 1) minus the next glyph's first column
def width(cs):
    x = 0
    for k, c in enumerate(cs):
        e = VWF[c] if c < len(VWF) else 0x0B; x += (e & 15) + 1
        if k + 1 < len(cs): n = cs[k + 1]; x -= (VWF[n] >> 4) if n < len(VWF) else 0
    return x
# wrap: one row if it fits, else the 2-row split at a space with the most equal row widths (assert if none fits).
# split: a text too long even for 2 rows becomes several lines, cut preferably after punctuation, near the middle
def wrap(s):
    if width(codes(s)) <= ROW_PX: return [s]
    words = s.split(' '); best = None
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        if width(codes(a)) <= ROW_PX and width(codes(b)) <= ROW_PX:
            c = (abs(width(codes(a)) - width(codes(b))), a, b); best = min(best or c, c)
    assert best, ('does not fit in 2 rows', s)
    return [best[1], best[2]]
def fits(s):
    try: wrap(s); return True
    except AssertionError: return False
def split(s):
    if fits(s): return [s]
    words = s.split(' '); c = []
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        c.append((0 if a.endswith((',', ';', ':', '--', '...', '!', '?', '.')) else 1, abs(width(codes(a)) - width(codes(b))), a, b))
    c.sort(); return split(c[0][2]) + split(c[0][3])
# Leading spaces that centre the row: tries 0-24 full-width spaces (0x4F, 12 px) with 0-2 English spaces (0x1A6,
# 5 px) and keeps the combination closest to the wanted indent
def centred(row):
    cs = codes(row); target = CENTRE - width(cs) / 2 - WIN_X; best = None
    for n12 in range(0, 25):
        for n5 in range(0, 3):
            pad = [0x4F] * n12 + [0x1A6] * n5
            err = abs(width(pad + cs) - width(cs) - target)
            if best is None or err < best[0]: best = (err, pad)
    return best[1] + cs
def u16s(vals): return b''.join(struct.pack('<H', v) for v in vals)
# One subtitle string: 0x378 0 (op 8A, args 00 00); 0x37A + x, y (u16), columns, rows (op 8C WIN); the rows joined by
# 0x374 (newline); 0x378 with bytes 01 00 (op 8A); 0x383 (op 95) and a 0 terminator
def string(text):
    rows = wrap(text); y = 0xDC if len(rows) == 1 else 0xD0
    body = []
    for k, r in enumerate(rows):
        if k: body.append(0x374)
        body += centred(r)
    return (u16s([0x378, 0]) + u16s([0x37A]) + struct.pack('<HHBB', WIN_X, y, 30, len(rows) + BOX) + (u16s([0x381]) + bytes([BOX_TYPE, 4]) if BOX else b'') + u16s(body)
            + u16s([0x378]) + bytes([1, 0]) + u16s([0x383, 0])), rows
# --- lines
lines = collections.OrderedDict()
# lines: {scene: [(start frame, duration in frames, text)]}. Seconds x 30 = frames; a duration is at least 15
# frames; split parts end 1 frame before the next part starts
for r in csv.DictReader(open('script/subtitles_en.csv', encoding='utf-8')):
    if r['status'] == 'drop': continue
    st, en = map(float, r['time_override'].split('-')) if r.get('time_override') else (float(r['start_s']), float(r['end_s']))
    text = r['en_final'] or r['text']; parts = split(text); tot = sum(width(codes(x)) for x in parts); t0 = st
    for x in parts:     # a line too long for 2 rows (an edited en_final) becomes consecutive lines, time shared by width
        t1 = t0 + (en - st) * width(codes(x)) / tot
        lines.setdefault(r['scene'], []).append((round(t0 * 30), max(15, round((t1 - t0) * 30) - (1 if x is not parts[-1] else 0)), x)); t0 = t1
# --- append to segment 2
seg2 = bytearray(d[ph[2][1]:ph[2][1] + ph[2][4]]); newrel = []; report = {}
def align4():
    while len(seg2) % 4: seg2.append(0)
# Point a master slot at segment-2 offset `off`: its relocation must be R_MIPS_32 (type 2) with address base 1
# (segment 1); the address base becomes 2 and the stored word becomes the offset
def retarget(slot, off):
    k = rel[slot]; o, i = struct.unpack_from('<II', d, k)
    assert (i & 0xFF) == 2 and (i >> 16) & 0xFF == 1, ('unexpected relocation on master slot', hex(slot), hex(i))
    struct.pack_into('<II', d, k, o, (i & ~0xFF0000) | (2 << 16)); struct.pack_into('<I', d, BASE + slot, off)
for sc, ls in lines.items():
    setname, n = sc[0], int(sc[1:]); ms, mt, cnt = MASTER[setname]; assert n < cnt, sc
    # the game shows one line at a time: lines must not overlap
    ls.sort(); prev_end = -1
    for st, du, _ in ls: assert st >= prev_end, ('overlapping lines', sc); prev_end = st + du
    align4(); t_off = len(seg2); seg2 += u16s([v for st, du, _ in ls for v in (st, du)] + [0xFFFF, 0xFFFF])
    strs = [string(t) for _, _, t in ls]
    align4(); tab_off = len(seg2); seg2 += bytes(4 * (len(ls) + 1))
    for k, (b, rows) in enumerate(strs):
        align4(); s_off = len(seg2); seg2 += b
        # new relocation: R_MIPS_32, offset in segment 2, address in segment 2
        struct.pack_into('<I', seg2, tab_off + 4 * k, s_off); newrel.append((tab_off + 4 * k, 2 | (2 << 8) | (2 << 16)))
    # slots that share this scene's original Japanese tables (A18 = bsr2.at3, which with English audio carries A15's
    # English stream; B27 = gts2.at3, the same launch line as B26) get the same English tables
    orig = (struct.unpack_from('<I', d, BASE + ms + 4 * n)[0], struct.unpack_from('<I', d, BASE + mt + 4 * n)[0])
    twins = [k for k in range(cnt) if k != n and (struct.unpack_from('<I', d, BASE + ms + 4 * k)[0],
                                                     struct.unpack_from('<I', d, BASE + mt + 4 * k)[0]) == orig]
    for k in [n] + twins: retarget(ms + 4 * k, tab_off); retarget(mt + 4 * k, t_off)
    report[sc] = dict(lines=len(ls), two_row=sum(len(r) == 2 for _, r in strs), shared_with=['%s%02d' % (setname, k) for k in twins])
# --- write: segment 2, new relocation section, section headers, program headers
# File tail = segment 2, then the new relocation entries, the section headers (one more), the program headers
while len(seg2) % 16: seg2.append(0)
del d[ph[2][1]:]; d += seg2; ph[2][4] = ph[2][5] = len(seg2)
while len(d) % 4: d.append(0)
rel_off = len(d)
for o, i in newrel: d += struct.pack('<II', o, i)
# the new relocation section: .rel.data's header with its own file offset and size
new = list(reld); new[4] = rel_off; new[5] = 8 * len(newrel); sh.append(new)
new_shoff = len(d)
for s in sh: d += struct.pack('<10I', *s)
new_phoff = len(d)
for p in ph: d += struct.pack('<8I', *p)
struct.pack_into('<I', d, 0x1C, new_phoff); struct.pack_into('<I', d, 0x20, new_shoff); struct.pack_into('<H', d, 0x30, len(sh))
open(P, 'wb').write(d)
json.dump(dict(scenes=report, lines=lines), open('logs/subtitles_report.json', 'w'), indent=1)
print(f'subtitles: {len(lines)} scenes, {sum(len(v) for v in lines.values())} lines ({sum(x["two_row"] for x in report.values())} on 2 rows); '
      f'{len(newrel)} relocations; segment 2 now {len(seg2)} bytes')
