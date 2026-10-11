"""Build check (run by build.py when the subtitles are English, --subtitle-language=en): read every English subtitle back
out of the built program and compare it with the reviewed list.

Background (docs/RESEARCH.md §11): the PSP version adds bottom-of-screen subtitles to voiced scenes that have no text
on the PS1 (cutscene streams, radio, the TV news). They are data in the program:
  - three master arrays of per-scene pointers. Set A (cutscene stream bank 0): string tables at vaddr 0x2607E8, timing
    tables at 0x260878, 36 scenes. Set B (stream bank 1): 0x260910 / 0x2609A0, 34 scenes (scene Bnn is index nn + 2 of
    the array that really starts at 0x260908). Set C (TV news): 0x260A28 / 0x260A48, 8 scenes;
  - a scene's string table is a list of pointers ended by 0; its timing table is (start frame, duration) u16 pairs
    at 30 frames per second, ended by 0xFFFF;
  - a string is in dialogue (MSG) format, 16-bit: op 0x378 (PS1 code 8A + 0x2EE) with a u16 argument, op 0x37A
    (8C, WIN) with x u16, y u16, columns u8, rows u8, then the text, then 0x378 again (followed by the end op). 0x374
    is the row break, 0x4F the 12-pixel full-width space and 0x1A6 the narrow English space, both used to centre a row.
tools/build_subtitles.py writes new tables and strings from script/subtitles_en.csv (made by subtitle_align.py and
reviewed by hand) and retargets the master slots; its own list of lines goes to logs/subtitles_report.json.

Reads:  build/test/<tag>/EBOOT_plain.BIN and build/diag/BOOT_sony_plain.BIN (loaded like the PSP loader does, with the
        loader part of compare_loaded.py), script/subtitles_en.csv, logs/subtitles_report.json,
        script/ps1_charmap.tbl (the PS1 character table, to decode glyph codes back to text).
Writes: nothing.
Checks: the report's lines, joined per scene, are exactly the CSV's kept lines (en_final if filled, else text; rows
        with status 'drop' left out) - a line too long for two rows is split into consecutive lines by the builder;
        each string decodes to the expected text with the expected start frame and duration, in order; each window is
        x 16, 30 columns, and 1 row at y 0xDC or 2 rows at y 0xD0; scenes that share another scene's original tables
        get the same English; scenes with no English lines keep their original table pointers.
Failure (exit 1, stops the build): CSV MISMATCH, WINDOW, COUNT, DIFF or CHANGED with the scene.

Usage: python3 tools/checks/verify_subtitles.py <tag>"""
import sys, os, csv, struct, collections
# take compare_loaded.py's loader (everything before its command-line part) and run it here: defines BASE and load()
src = open(os.path.join(os.path.dirname(__file__), 'compare_loaded.py')).read().split('a, na, pa = load')[0]
tag = sys.argv[1]; sys.argv = [sys.argv[0]]; exec(src)
sys.path.insert(0, 'tools'); import msgtool as M
B, _, _ = load(f'build/test/{tag}/EBOOT_plain.BIN'); A, _, _ = load('build/diag/BOOT_sony_plain.BIN')
def u32(m, a): return struct.unpack_from('<I', m, a)[0]
def u16(m, a): return struct.unpack_from('<H', m, a)[0]
# character -> PS1 code from script/ps1_charmap.tbl (single characters only), then reversed into PSP code -> character
TBL = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: TBL.setdefault(v, int(k, 16))
# PS1 codes that the converter remaps (msgtool.PS1_TO_PSP_CHAR) are looked up under their PSP code; 0x1A6 = English
# space
REV = {M.PS1_TO_PSP_CHAR.get(c, c): ch for ch, c in TBL.items()}; REV[0x1A6] = ' '
# set -> (vaddr of the string-table pointer array, vaddr of the timing-table pointer array), indexed by scene number
MASTER = {'A': (0x2607E8, 0x260878), 'B': (0x260910, 0x2609A0), 'C': (0x260A28, 0x260A48)}   # B nn = set-1 index nn+2
import json
# expected lines: build_subtitles.py's own list (a line too long for 2 rows is split into consecutive lines); it must
# hold exactly the CSV's kept lines, in order, when split parts are joined back
# want[scene] = [(start frame, duration, text), ...] as build_subtitles.py placed them
want = collections.OrderedDict((k, [tuple(x) for x in v]) for k, v in json.load(open('logs/subtitles_report.json'))['lines'].items())
for sc, inf in json.load(open('logs/subtitles_report.json'))['scenes'].items():
    for tw in inf.get('shared_with', []): want[tw] = want[sc]   # slots sharing the scene's original tables
csv_text = collections.defaultdict(list)
for r in csv.DictReader(open('script/subtitles_en.csv', encoding='utf-8')):
    if r['status'] != 'drop': csv_text[r['scene']].append(r['en_final'] or r['text'])
for sc in set(csv_text):
    if ' '.join(csv_text[sc]) != ' '.join(t for _, _, t in sorted(want.get(sc, []))): print('CSV MISMATCH', sc); sys.exit(1)
bad = 0; n = 0; two = 0
for sc, ls in want.items():
    # scene id = set letter + two-digit index, e.g. 'A07'
    ls.sort(); ms, mt = MASTER[sc[0]]; k = int(sc[1:])
    tab = u32(B, ms + 4 * k) - BASE; tim = u32(B, mt + 4 * k) - BASE
    got = []; j = 0
    while True:
        p = u32(B, tab + 4 * j)
        if not p: break
        p -= BASE; j += 1
        # every string starts with op 8A (0x378), its u16 argument, then op 8C WIN (0x37A) at +4
        assert u16(B, p) == 0x378 and u16(B, p + 4) == 0x37A, (sc, j)
        # WIN arguments at +6; the text starts at +12 and runs to the next 0x378
        x, y, cols, rows = struct.unpack_from('<HHBB', B, p + 6); q = p + 12; text = ''; row = []
        box = u16(B, q) == 0x381                         # --subtitle-background=on: DECOR 04 04 after WIN, window x 0
        if box: assert u16(B, q + 2) == 0x0404, (sc, j); q += 4   # type 4, margin 4 (patch_subtitle_box.py)
        while True:
            c = u16(B, q); q += 2
            if c == 0x378: break
            row.append(c)
        rs = [[]]
        # split into rows at 0x374; drop the centring spaces 0x4F; decode the rest
        for c in row:
            if c == 0x374: rs.append([])
            else: rs[-1].append(c)
        txt = ' '.join(''.join('' if c == 0x4F else REV.get(c, '?') for c in r_).strip() for r_ in rs)
        # one-row lines sit at y 0xDC (as the Japanese ones), two-row lines 12 pixels higher at y 0xD0
        if (x, cols, rows, y) != (0 if box else 16, 30, len(rs) + box, 0xDC if len(rs) == 1 else 0xD0): bad += 1; print('WINDOW', sc, j, x, y, cols, rows)
        two += rows == 2
        got.append(txt)
    tm = []
    while u16(B, tim + 4 * len(tm)) != 0xFFFF: tm.append((u16(B, tim + 4 * len(tm)), u16(B, tim + 4 * len(tm) + 2)))
    if len(got) != len(ls) or len(tm) != len(ls): bad += 1; print('COUNT', sc, len(got), len(tm), len(ls)); continue
    for (st, du, t), g, (gs, gd) in zip(ls, got, tm):
        n += 1
        if g != t or (gs, gd) != (st, du): bad += 1; print('DIFF', sc, repr(t), repr(g), (st, du), (gs, gd))
# scenes without English lines: original tables
for s_, (ms, mt) in MASTER.items():
    # number of scene slots per set
    for k in range({'A': 36, 'B': 34, 'C': 8}[s_]):
        sc = '%s%02d' % (s_, k)
        if sc in want: continue
        if u32(B, ms + 4 * k) != u32(A, ms + 4 * k) or u32(B, mt + 4 * k) != u32(A, mt + 4 * k): bad += 1; print('CHANGED', sc)
print(f'subtitles: {n} lines in {len(want)} scenes ({two} on 2 rows) match script/subtitles_en.csv; problems: {bad}')
sys.exit(1 if bad else 0)
