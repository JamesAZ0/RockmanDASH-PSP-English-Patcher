"""Research / authoring tool (not run by the build): propose timed English subtitle lines for the PSP-only subtitle
scenes. Its output, script/subtitles_en.csv, is reviewed by hand and then read by tools/build_subtitles.py, which the
build does run. First made 2026-09-30. See docs/RESEARCH.md §11.

The problem: the PSP version shows subtitles during voiced scenes (cutscene streams, radio, TV news) that have no
on-screen text on the PS1. So there is no PS1 text to take; what exists in English is the PS1 dub itself. The
Japanese subtitle timings do not fit either, because the English dub breaks its sentences at different points.

Inputs:
  build/voice_en/words.json          word-level timing of the English dub per scene, made with
                                     research/transcribe_words_mac.py (the words are what the Whisper speech
                                     recogniser heard, so they contain errors)
  reference/gamefaqFullScript.txt    a fan transcript of the PS1 game's script (GameFAQs, by Estil), saved locally and
                                     used as a spelling / punctuation reference only; it is not part of the project's
                                     published files
  build/eboot/ULJM05030_EBOOT_vwf.BIN  for the glyph-width table, to measure lines as the game will draw them
  script/ps1_charmap.tbl  the PS1 character table (which characters the font has)
The dub is the authority: a proposed line keeps the reference's wording only where it matches what is heard (score =
token similarity); low scores are flagged for a person to listen to.

Method:
  - the reference is parsed into utterances ("Speaker: text", continuation lines joined, stage directions and
    headings dropped) and tokenised into one long token list;
  - each scene's heard words are located in that list by 3-gram voting (every 3 consecutive heard tokens that occur
    in the reference vote for an offset), then aligned token by token around the winning offset (difflib). Every
    matched reference token gets the time of the heard word; unmatched ones are interpolated between neighbours;
  - utterances are split into sentences and packed into subtitle lines of at most 2 rows of ROW_PX pixels (measured
    with the game's variable-width table) and MAX_S seconds; sentences too long for that are split at punctuation or
    at the word boundary nearest the middle;
  - a line is shown from LEAD seconds before its first word to TAIL seconds after its last; lines never overlap;
  - heard words that no reference line covers become lines of their own, flagged 'heard only'.

Output columns: scene, n, start_s, end_s, start_frame, frames (30 frames per second, time within the clip), speaker,
text (proposed), heard, score, rows, width_px, flags, then the review columns en_final / status (use | drop) /
time_override ("start-end" in seconds) / notes. The review columns are carried over when the file is regenerated; a
line is matched by scene + number, so re-check them if the alignment changes.
Also writes logs/subtitle_align_report.json (per scene: how much was matched; reference lines inside a scene that
were not heard).
research/subtitle_review_page.py executes two parts of this file (the measuring helpers at the top and the
row-wrapping helper), so those parts must stay free of side effects.

Usage: python3 research/subtitle_align.py"""
import sys, os, re, csv, json, struct, difflib, collections
sys.path.insert(0, 'tools'); import msgtool as M
REF = 'reference/gamefaqFullScript.txt'; OUT = 'script/subtitles_en.csv'
for _p, _how in (('build/voice_en/words.json', 'word timings of the English voices; make them with research/transcribe_words_mac.py (Apple Silicon, mlx-whisper) after a build has extracted the clips'),
                 (REF, 'the reference transcript is a third-party document and is not part of the repository; save your own copy there')):
    if not os.path.exists(_p): raise SystemExit(f'{_p} is missing: {_how}')
# ROW_PX: usable row width chosen for subtitles, in pixels of the 320-wide screen. MAX_S: longest time one line may
# cover. LEAD / TAIL: seconds a line appears before its first word / stays after its last
ROW_PX = 288; MAX_S = 6.0; LEAD = 0.1; TAIL = 0.35
# --- font widths and the PS1 character table. The width table is written by patch_eboot.py at vaddr 0x226980 (file
# offset = vaddr + 0x80), one byte per glyph code 0..0x1A6: low nibble = last ink column, high nibble = first ink column
E = open('build/eboot/ULJM05030_EBOOT_vwf.BIN', 'rb').read(); VWF = E[0x80 + 0x226980: 0x80 + 0x226980 + 0x1A7]
TBL = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: TBL.setdefault(v, int(k, 16))
# width: pixel width of a string as the game draws it. Characters go through the converter's PS1 -> PSP glyph mapping;
# a glyph advances by (last ink column + 1) and the next glyph is pulled left by its own first ink column. Codes
# outside the table count as a full 12-pixel cell (0x0B)
def width(s):
    cs = [M.PS1_TO_PSP_CHAR.get(TBL[ch], TBL[ch]) if ch in TBL else 0x20 for ch in s]; x = 0   # unknown chars: counted as a wide letter (flagged)
    for k, c in enumerate(cs):
        e = VWF[c] if c < len(VWF) else 0x0B; x += (e & 15) + 1
        if k + 1 < len(cs): n = cs[k + 1]; x -= (VWF[n] >> 4) if n < len(VWF) else 0
    return x
# clean: strip (stage directions) and [notes], normalise apostrophes, long dot runs and spacing
def clean(s):
    s = re.sub(r'\([^)]*\)', ' ', s); s = re.sub(r'\[[^\]]*\]?', ' ', s); s = s.replace('’', "'").replace('`', "'")
    s = re.sub(r'\.{4,}', '...', s); s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'(\.\.\.)(?=[A-Za-z])', r'\1 ', s); return s
# toks: lower-case word tokens for matching; digits and # spelled out the way the recogniser writes them
NUM = {'1': 'one', '2': 'two', '3': 'three', '4': 'four', '5': 'five', '100': 'hundred', '#': 'number'}
def toks(s):
    s = s.lower().replace('mega man', 'megaman').replace('#', ' number ')
    return [NUM.get(t, t) for t in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", s)]
# FIX: the recogniser's usual mishearings of the game's names -> the PS1 spelling
FIX = [(r'\bMega Man\b', 'MegaMan'), (r'\b(Role|Roar|Rolf|Rol)\b', 'Roll'), (r'\b(Teasel|Diesel|Teisal|Tizel)\b', 'Teisel'),
       (r'\bTizelbon\b', 'Teisel Bonne'), (r'\b(Bond|Bomb|Bonn)\b', 'Bon'), (r'\bDraks\b', 'Draches'), (r'\bVolnut\b', 'Volnutt'),
       (r'\brefractor', 'Refractor'), (r'\b(Cadillox|Cadillacs|Catalox)\b', 'Kattelox')]
def names(s):
    for a, b in FIX: s = re.sub(a, b, s)
    return s
# --- reference utterances
# a line "Name: text" (optional "(note)" after the name) starts an utterance; an all-capitals name is a heading
SPK = re.compile(r"^([A-Z][A-Za-z0-9 .'&/-]{0,40}?)(?: \([^)]*\))?:\s+(.*)$")
utts = []; cur = None
for raw in open(REF, encoding='utf-8', errors='replace'):
    line = raw.rstrip()
    m = SPK.match(line)
    if m and not m.group(1).isupper():
        cur = dict(speaker=m.group(1).strip(), text=m.group(2)); utts.append(cur); continue
    if not line.strip() or line.startswith('(') or line.rstrip().endswith(':') or line.isupper(): cur = None; continue
    if cur: cur['text'] += ' ' + line.strip()
for u in utts: u['text'] = clean(u['text'])
utts = [u for u in utts if toks(u['text'])]
# T = all reference tokens in order, TU = the utterance each belongs to; idx3 = every 3-token sequence -> positions
T = []; TU = []
for ui, u in enumerate(utts):
    for t in toks(u['text']): T.append(t); TU.append(ui)
idx3 = collections.defaultdict(list)
for j in range(len(T) - 2): idx3[tuple(T[j:j+3])].append(j)
# --- scenes
W = json.load(open('build/voice_en/words.json'))
# norm_words: heard words -> [(token, index of the word)], with "mega man" joined into one token as in toks()
def norm_words(ws):
    out = []
    for i, w in enumerate(ws):
        for t in toks(w['w']):
            if t == 'man' and out and out[-1][0] == 'mega': out[-1] = ('megaman', out[-1][1]); continue
            out.append((t, i))
    return out
# heard_between: the words whose midpoint falls inside a line's time span, names corrected - shown for comparison
def heard_between(ws, st, en): return names(' '.join(w['w'] for w in ws if st + LEAD - 0.05 <= (w['start'] + w['end']) / 2 <= en - TAIL + 0.1))
# sentences: split after . ! ? when a capital letter or quote follows
def sentences(text):
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', text); return [p for p in parts if p.strip()]
def split_long(s):
    """A sentence too long for 2 rows: split at the punctuation (, ; : -- ...) closest to the middle, else at the
    word boundary closest to the middle; recursively."""
    w_ = wrap(s)
    if len(w_) <= 2 and max(width(x) for x in w_) <= ROW_PX: return [s]
    words = s.split(' '); cands = []
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        punct = a.endswith((',', ';', ':', '--', '...')) or a.endswith(('!', '?', '.'))
        cands.append((0 if punct else 1, abs(width(a) - width(b)), a, b))
    cands.sort(); _, _, a, b = cands[0]
    return split_long(a) + split_long(b)
def wrap(s):
    if width(s) <= ROW_PX: return [s]
    words = s.split(' '); best = None
    for k in range(1, len(words)):
        a, b = ' '.join(words[:k]), ' '.join(words[k:])
        if width(a) <= ROW_PX and width(b) <= ROW_PX:
            sc = abs(width(a) - width(b)); best = min(best or (sc, a, b), (sc, a, b))
    return [best[1], best[2]] if best else [s]
# fits: s can be shown as one subtitle (at most 2 rows, each within ROW_PX)
def fits(s):
    w_ = wrap(s); return len(w_) <= 2 and max(width(x) for x in w_) <= ROW_PX
old = {}
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT, encoding='utf-8')): old[(r['scene'], r['n'])] = r
rows = []; report = {}; unspoken = {}
for sc in sorted(W):
    ws = W[sc]['words']; H = norm_words(ws)
    if not H: report[sc] = 'no speech'; continue
    # each heard 3-gram found in the reference votes for (reference position - heard position), in bins of 40 tokens
    votes = collections.Counter()
    for i in range(len(H) - 2):
        for j in idx3.get((H[i][0], H[i+1][0], H[i+2][0]), []): votes[(j - i) // 40] += 1
    if not votes: report[sc] = 'not found in reference: lines from the transcript'; votes[0] = 0
    # align the heard tokens against a window of the reference around the winning bin (80 tokens before it, 200 after
    # the scene's length)
    b0 = votes.most_common(1)[0][0] * 40; lo = max(0, b0 - 80); hi = min(len(T), b0 + len(H) + 200)
    sm = difflib.SequenceMatcher(None, [h[0] for h in H], T[lo:hi], autojunk=False)
    # tmap: reference token position -> index of the heard word it matched (blocks of at least 2 tokens only)
    tmap = {}
    blocks = [(a, b, n) for a, b, n in sm.get_matching_blocks() if n >= 2]
    # drop outlying blocks: keep the longest run of blocks whose reference gaps are < 40 tokens
    runs = []; cur_ = []
    for bl in blocks:
        if cur_ and bl[1] - (cur_[-1][1] + cur_[-1][2]) > 40: runs.append(cur_); cur_ = []
        cur_.append(bl)
    if cur_: runs.append(cur_)
    best = max(runs, key=lambda r: sum(x[2] for x in r)) if runs else []
    for a, b, n in best:
        for k in range(n): tmap[lo + b + k] = H[a + k][1]
    if not tmap: report[sc] = 'not in the reference: lines from the transcript'
    j0, j1 = (min(tmap), max(tmap)) if tmap else (1, 0)
    # keep reference utterances inside the aligned span
    ulist = sorted({TU[j] for j in range(j0, j1 + 1)})
    if tmap: report[sc] = f'{len(H)} heard tokens, {len(tmap)} matched ({len(tmap) / len(H):.0%}), reference utterances {ulist[0]}-{ulist[-1]}'
    # time of each reference token (matched = its word; unmatched = interpolated)
    tpos = [j for j in range(j0, j1 + 1)]
    def ttime(j, end=False):
        if j in tmap: w = ws[tmap[j]]; return w['end'] if end else w['start']
        prv = max([k for k in tmap if k < j], default=None); nxt = min([k for k in tmap if k > j], default=None)
        if prv is None: return ws[tmap[nxt]]['start']
        if nxt is None: return ws[tmap[prv]]['end']
        a, b = ws[tmap[prv]]['end'], ws[tmap[nxt]]['start']; return a + (b - a) * (j - prv) / (nxt - prv)
    units = []   # (speaker, text, token range)
    for ui in ulist:
        u = utts[ui]; js = [j for j in range(len(T)) if TU[j] == ui]; pos = 0
        for s in sentences(u['text']):
            for piece in split_long(s):
                n = len(toks(piece)); r = [j for j in js[pos:pos + n] if j0 <= j <= j1]; pos += n
                if r and any(j in tmap for j in r): units.append([u['speaker'], piece, r])
                elif r: unspoken.setdefault(sc, []).append(piece)
    # pack sentences of the same speaker into lines of <= 2 rows and <= MAX_S
    lines = []
    for spk, text, r in units:
        if lines and lines[-1][0] == spk:
            cand = lines[-1][1] + ' ' + text
            if fits(cand) and ttime(r[-1], True) - ttime(lines[-1][2][0]) <= MAX_S and \
               ttime(r[0]) - ttime(lines[-1][2][-1], True) < 0.8:
                lines[-1][1] = cand; lines[-1][2] += r; continue
        lines.append([spk, text, list(r)])
    out = []
    for spk, text, r in lines:
        st = max(0, ttime(r[0]) - LEAD); en = ttime(r[-1], True) + TAIL
        heard = heard_between(ws, st, en)
        score = difflib.SequenceMatcher(None, toks(text), toks(heard), autojunk=False).ratio() if heard else 0
        out.append(dict(speaker=spk, text=text, st=st, en=en, heard=heard, score=score, src='reference'))
    # heard words no reference line covers (runs of >= 3 words): proposed from what was heard, flagged
    used = {tmap[j] for j in tmap}; covered = [(o['st'], o['en']) for o in out]
    free = [i for i, w in enumerate(ws) if not any(a - 0.05 <= w['start'] and w['end'] <= b + 0.05 for a, b in covered)]
    grp = []
    for i in free:
        if grp and (i != grp[-1][-1] + 1 or ws[i]['start'] - ws[grp[-1][-1]]['end'] > 0.8): grp.append([i])
        elif grp: grp[-1].append(i)
        else: grp.append([i])
    for g in grp:
        if len(g) < (3 if tmap else 1): continue   # scenes the reference doesn't have: every heard word counts
        st = max(0, ws[g[0]]['start'] - LEAD); en = ws[g[-1]]['end'] + TAIL; txt = names(' '.join(ws[i]['w'] for i in g))
        out.append(dict(speaker='?', text=txt, st=st, en=en, heard=txt, score=1.0, src='heard'))
    out.sort(key=lambda o: o['st'])
    for k in range(len(out) - 1):                     # no overlaps; keep at least 0.1 s gap
        if out[k]['en'] > out[k+1]['st'] - 0.1: out[k]['en'] = max(out[k]['st'] + 0.5, out[k+1]['st'] - 0.1)
    for n, o in enumerate(out):
        bad = [ch for ch in o['text'] if ch not in TBL]
        wr = wrap(o['text'])
        fl = []
        # flags for the reviewer; a score under 0.75 means the reference wording differs noticeably from what was
        # heard
        if o['src'] == 'heard': fl.append('heard only: not in the reference (wording from the transcript)')
        elif o['score'] < 0.75: fl.append('check wording (heard differs)')
        if not o['heard']: fl.append('not heard')
        if bad: fl.append('unsupported characters ' + ''.join(sorted(set(bad))))
        if len(wr) > 2 or max(width(x) for x in wr) > ROW_PX: fl.append('too wide')
        key = (sc, str(n)); prev = old.get(key, {})
        # frames at 30 per second; a line is shown for at least 15 frames
        rows.append(dict(scene=sc, n=n, start_s=round(o['st'], 2), end_s=round(o['en'], 2), start_frame=round(o['st'] * 30),
                         frames=max(15, round((o['en'] - o['st']) * 30)), speaker=o['speaker'], text=o['text'],
                         heard=o['heard'], score=round(o['score'], 2), rows=len(wr), width_px=max(width(x) for x in wr),
                         flags='; '.join(fl), en_final=prev.get('en_final', ''), status=prev.get('status', ''), time_override=prev.get('time_override', ''), notes=prev.get('notes', '')))
with open(OUT, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
json.dump(dict(scenes=report, reference_lines_not_spoken=unspoken), open('logs/subtitle_align_report.json', 'w'), indent=1)
fl = collections.Counter(x for r in rows for x in r['flags'].split('; ') if x)
print(f'{len(rows)} subtitle lines in {len({r["scene"] for r in rows})} scenes; flags: {dict(fl)}')
for k, v in report.items():
    if 'matched' not in v: print(' ', k, v)
