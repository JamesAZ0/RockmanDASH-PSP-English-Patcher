"""Research / review tool (not run by the build): find and decode the PSP-only voice subtitles in the original program
and collect, per Japanese line, everything known about its English counterpart. Writes script/subtitles.csv, the
first review file for the subtitles (2026-09-29). The English subtitles the build uses were later re-cut to the
English dub's own timing by research/subtitle_align.py (script/subtitles_en.csv); this file remains the map of
the Japanese originals and of which audio clip belongs to which scene. See docs/RESEARCH.md §11.

What the PSP adds: bottom-of-screen subtitles for voiced scenes that had no text on the PS1 (TV news, radio, cutscene
streams). They live in the program's .data as MSG-format strings in game font codes, each starting with op 8A and a
WIN op (8C) whose y is 0xDC (one row at the bottom) - that signature is how they are found. They are reached through
per-scene pointer tables; a parallel "companion" table gives each line's (start frame, duration). Scene tables hang
off three master arrays: A at vaddr 0x2607E8 and B at 0x260910 (timing companions 0x90 bytes after each), and C at
0x260A28 (TV news; its timing array is not read here).

Method: resolve every relocated pointer in .data; keep those that point at a subtitle string; consecutive pointers
form a scene's table; the master slot pointing at the table gives set and scene number.

Columns: id (set + scene - line, e.g. A07-03), set, scene, line, pointer / string / table vaddrs, start / duration in
frames, window (the WIN arguments in hex), Japanese (tools/jptable.py TK; kanji marked * are tentative readings),
ps1_match (the same Japanese found as dialogue text in a PSP MSG file -> ps1_english = the PS1 English block at that
position), the PS1 English voice transcript (ps1_voice with names normalised, ps1_voice_raw as the speech recogniser
wrote it; voice_flags / voice_clip / voice_window for checking by ear), en_draft and draft_notes (optional files
build/analysis/subtitles_draft_en.json and subtitles_draft_notes.json: a working translation for reading only, with
scene descriptions and term choices), and the review columns en_final / status / notes, which are KEPT when the file
is regenerated.

Reads:  decrypted_eboot/ULJM05030_EBOOT.BIN, extracted/psp and extracted/ps1 dialogue, script/ps1_charmap.tbl
        (the PS1 character table), build/voice_en/*.json (transcripts, if present), script/voice_rules.json, the existing CSV.
Usage: python3 research/subtitle_map.py"""
import sys, os, csv, json, struct, glob, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools')); import msgtool as M; from jptable import TK, TENTATIVE
E = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()
# SEG = vaddr of segment 0 and 1; DATA_END = end of the data this script treats as table space (segment 1 start +
# 0xDF6BC; where that length was taken from: origin not recorded)
SEG = [0, 0x245200]; DATA_END = 0x245200 + 0xDF6BC
# rel: vaddr of each relocated data word -> relocation info (.rel.data: file offset 0x3CF6D0, 0x1E6F0 bytes, 8-byte
# entries). ptr(va): the vaddr the word points to = stored value + vaddr of the segment named in bits 16-23 of the
# info
rel = {}
for k in range(0x1E6F0 // 8):
    o, i = struct.unpack_from('<II', E, 0x3CF6D0 + 8*k); rel[o + SEG[(i >> 8) & 0xFF]] = i
def ptr(va): return struct.unpack_from('<I', E, 0x80 + va)[0] + SEG[(rel[va] >> 16) & 0xFF] if va in rel else None
# toks: parse the MSG-format string at va up to its end op (95, 84 or 91)
def toks(va, n=400):
    t, _ = M.parse(E[0x80+va:0x80+va+n], True, True); out = []
    for x in t:
        out.append(x)
        if x[0] == 'op' and x[1] in (0x95, 0x84, 0x91): break
    return out
# is_sub: starts with op 8A, then op 8C (WIN) whose third and fourth argument bytes are DC 00 (y = 0xDC)
def is_sub(va):
    t = toks(va, 40)
    return len(t) >= 2 and t[0][:2] == ('op', 0x8A) and t[1][:2] == ('op', 0x8C) and t[1][2][2:4] == b'\xdc\x00'
# PSP glyph codes of the symbols, shown with full-width punctuation in the Japanese column
SYM = {0xFD: '○', 0xFE: '△', 0xFF: '×', 0x100: '□', 0x105: '，', 0x106: '"', 0x107: '。', 0x108: '…', 0x109: '☞', 0x10A: '＋', 0x10B: '％'}
def jp(codes, mark=True):
    s = ''
    for c in codes:
        if c == 0x86: s += ' / '
        else: s += TK.get(c) or SYM.get(c) or '{%X}' % c; s += '*' if (mark and c in TENTATIVE) else ''
    return s.replace('　', '').strip()
# --- tables
# P = every relocated pointer in .data; subptr = those pointing at a subtitle string (strings sit in
# 0x254500-0x262000); tabs = runs of consecutive pointers, keyed by the address of the first
P = {a: ptr(a) for a in rel if 0x245200 <= a < 0x3A0000}
subptr = {a: v for a, v in P.items() if v and 0x254500 <= v < 0x262000 and is_sub(v)}
tabs = collections.OrderedDict()
for a in sorted(subptr):
    last = next(reversed(tabs), None)
    if last is not None and a - tabs[last][-1] == 4: tabs[last].append(a)
    else: tabs[a] = [a]
# (set, vaddr of its master array, distance to the companion array of timing tables)
MASTER = (('A', 0x2607E8, 0x90), ('B', 0x260910, 0x90), ('C', 0x260A28, None))
masters = collections.defaultdict(list)
for a, v in P.items():
    if v in tabs: masters[v].append(a)
# scene_of: (set, scene index, master slot vaddr, companion distance) for the table at t; set 'X' if no master points
# at it
def scene_of(t):
    for m in sorted(masters.get(t, [])):
        for name, base, comp in MASTER:
            if base <= m < base + 0x100: return name, (m - base) // 4, m, comp
    return 'X', 0, None, None
# --- Japanese dialogue pages, for finding lines that also exist as dialogue text
# norm: strip spaces and punctuation so a subtitle can be searched for inside dialogue pages
def norm(s): return ''.join(ch for ch in s if ch not in '　 /…。、！？!?・「」*')
pages = []
for f in sorted(glob.glob('extracted/psp/**/*.[Mm][Ss][Gg]', recursive=True)):
    rel_ = f[len('extracted/psp/'):]
    for bi, b in enumerate(M.blocks(open(f, 'rb').read())[0]):
        cur = []
        # a page ends at op 9F, CLEAR (87) or CLOSE (84); a final 9F is appended so the last page is flushed
        for x in M.parse(b, True, True)[0] + [('op', 0x9F, b'')]:
            if x[0] == 'c': cur.append(x[1])
            elif x[1] in (0x9F, 0x87, 0x84) and cur: pages.append((rel_, bi, norm(jp(cur, False)))); cur = []
EN = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: EN.setdefault(int(k, 16), v)
def ps1_block(rel_, bi):
    try: B = M.blocks(open('extracted/ps1/' + rel_, 'rb').read())[0]
    except FileNotFoundError: return ''
    if bi >= len(B): return ''
    t, _ = M.parse(B[bi], False)
    return ''.join((' ' if x[1] == 0x86 else EN.get(x[1], '')) for x in t if x[0] == 'c').strip()
draft = json.load(open('build/analysis/subtitles_draft_en.json')) if os.path.exists('build/analysis/subtitles_draft_en.json') else {}
# --- PS1 English voice transcripts (made with tools/voice/*, 2026-09-29): A/B lines from per-line audio windows,
# C scenes (TV news) from whole clips of PS1 voice bank 11
import re
VD = 'build/voice_en/'
def _j(p): return json.load(open(VD + p)) if os.path.exists(VD + p) else {}
WT = _j('window_transcripts.json'); WIN = {w['id']: w for w in (json.load(open(VD + 'windows.json')) if os.path.exists(VD + 'windows.json') else [])}
BT = _j('transcripts.json')
# WT / WIN: transcript and time window per subtitle id; BT: whole-clip transcripts. C_CLIP: news scene -> PS1 clip
C_CLIP = {0: 'b11_c10_0', 1: 'b11_c04_0', 2: 'b11_c05_0', 3: 'b11_c07_0', 4: 'b11_c06_0', 5: 'b11_c08_0', 6: 'b11_c09_0'}  # by content
# FIX: the recogniser's usual mishearings of the game's names -> the PS1 spelling
FIX = [(r'\bMega Man\b', 'MegaMan'), (r'\b(Role|Roar|Rolf|Rol)\b', 'Roll'), (r'\b(Teasel|Diesel|Teisal|Tizel)\b', 'Teisel'),
       (r'\b(Bond|Bomb|Bonn)\b', 'Bon'), (r'\bDraks\b', 'Draches'), (r'\bVolnut\b', 'Volnutt'), (r'\brefractor', 'Refractor'),
       (r'\bCadillox\b', 'Kattelox')]
# scenes whose "English" PS1 clip is really the Japanese recording (no English dub exists)
KEEP_JP = json.load(open('script/voice_rules.json'))['keep_japanese_scenes'] if os.path.exists('script/voice_rules.json') else {}
SCENE_FLAG = {k: 'KEEP JAPANESE VOICE (script/voice_rules.json): the PS1 clip is the Japanese track, no English dub; transcript is Whisper translating Japanese' for k in KEEP_JP}
def voice(pid, st, sc, ln):
    raw = ''; clip = ''; win = ''; flags = [SCENE_FLAG[pid[:3]]] if pid[:3] in SCENE_FLAG else []
    if st in 'AB' and pid in WT:
        v = WT[pid]; raw = v['text']; w = WIN[pid]; clip = w['clip']; win = '%.2f-%.2f' % (w['start'], w['end'])
        if not raw: flags.append('empty')
        # the recogniser's own quality measures, used to flag transcripts that may be invented (thresholds chosen by
        # hand)
        if v['no_speech'] > 0.6: flags.append('no-speech %.2f' % v['no_speech'])
        if v['logprob'] < -1.0: flags.append('low confidence %.2f' % v['logprob'])
        if v['compression'] > 2.4: flags.append('repetitive')
        if raw.endswith('-') or raw.startswith(('and ', 'the ', 'for ', 'of ')): flags.append('cut at window edge')
    elif st == 'C' and ln == 0 and sc in C_CLIP:
        clip = C_CLIP[sc]; raw = BT.get(clip, ''); flags.append('whole scene on the -00 line; split across lines in review')
    fixed = raw
    for a, b in FIX: fixed = re.sub(a, b, fixed)
    if fixed != raw: flags.append('names normalised')
    return dict(ps1_voice=fixed, ps1_voice_raw=raw, voice_clip=clip, voice_window=win, voice_flags='; '.join(flags))
dnotes = json.load(open('build/analysis/subtitles_draft_notes.json')) if os.path.exists('build/analysis/subtitles_draft_notes.json') else {}
OUT = 'script/subtitles.csv'
keep = {}
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT, encoding='utf-8-sig')): keep[r['id']] = r
cols = ['id', 'set', 'scene', 'line', 'pointer_va', 'string_va', 'table_va', 'start_frame', 'frames', 'window', 'japanese',
        'ps1_match', 'ps1_english', 'ps1_voice', 'voice_flags', 'voice_clip', 'voice_window', 'ps1_voice_raw', 'en_draft', 'draft_notes', 'en_final', 'status', 'notes']
rows = []; nmatch = 0
for t, ps in tabs.items():
    name, sc, m, comp = scene_of(t); timing = []
    # the companion slot holds the scene's timing table: (start frame, duration) u16 pairs up to 0xFFFF
    c = ptr(m + comp) if (m is not None and comp and (m + comp) in rel) else None
    if c and c < DATA_END:
        o = c
        while struct.unpack_from('<H', E, 0x80 + o)[0] != 0xFFFF: timing.append(struct.unpack_from('<HH', E, 0x80 + o)); o += 4
    for k, a in enumerate(ps):
        tk = toks(subptr[a]); codes = [x[1] for x in tk if x[0] == 'c']
        text = jp(codes); n = norm(jp(codes, False))
        hits = [(r_, b_) for r_, b_, s_ in pages if n and len(n) >= 8 and n in s_]   # >= 8 chars: short phrases match everywhere
        pid = '%s%02d-%02d' % (name, sc, k)
        row = dict(id=pid, set=name, scene=sc, line=k, pointer_va='%06X' % a, string_va='%06X' % subptr[a], table_va='%06X' % t,
                   start_frame=timing[k][0] if k < len(timing) else '', frames=timing[k][1] if k < len(timing) else '',
                   window=next((x[2].hex() for x in tk if x[0] == 'op' and x[1] == 0x8C), ''), japanese=text,
                   ps1_match='; '.join('%s blk %02X' % h for h in hits[:3]), ps1_english=ps1_block(*hits[0]) if hits else '',
                   en_draft=draft.get(pid, ''), draft_notes=dnotes.get(pid, ''), **voice(pid, name, sc, k))
        nmatch += bool(hits)
        for c_ in ('en_final', 'status', 'notes'): row[c_] = keep.get(pid, {}).get(c_, '')
        rows.append(row)
os.makedirs('script', exist_ok=True)
with open(OUT, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(f'{len(rows)} subtitle lines in {len(tabs)} scenes -> {OUT}; {nmatch} also appear as Japanese dialogue text; '
      f'{sum(1 for r in rows if r["en_draft"])} with draft English')
