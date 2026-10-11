"""Voice lines with Japanese audio: put the Japanese voice clips at the right places in the English text.
Used by tools/build_text.py (place_jp); run alone it writes script/voice_map.json (a record of every placement) and
logs/voice_map_review.md (the blocks matched by time, worst first). Needs build/voice_en/index.csv
(extract_voice_en.py) and build/voice_en/jp_clips.json (jp_clips.py); build.py makes both if missing.

The problem. A dialogue block starts a voice clip with the AUDIO op, 0x8F, args = clip, 0, bank, 0 (both discs). The
English text comes from the PS1 and carries PS1 clip numbers, which on the PSP either name a bank that doesn't exist
(1,041 ops: nothing plays and the text box waits forever, seen in game e.g. after City Hall) or the wrong Japanese
clip (434 ops). And the two scripts don't always cut a speech into the same
number of voiced pieces, so the Japanese ops can't simply be copied by position.

Two build modes (build_text.py's internal argument --audio=, set by build.py):
--audio=jp (--localization=text, Japanese voices): the English ops are removed and the Japanese block's ops are
  placed in the English token list at anchors: the English ops' positions (no penalty), page starts (after NEXT 9F /
  CLEAR 87, +0.02) and sentence ends (. ! ? then space/newline, +0.04).
    same    - equal counts: Japanese op k takes English op k's place.
    aligned - different counts: a monotone one-to-one match (DP) of each Japanese clip to the anchor nearest in
              *time*: a Japanese op's position = the length of the Japanese clips before it / all of them (clip
              lengths from the ISO); an anchor's = the English clips before it + the part of its own clip up to the
              anchor by characters (lengths of the PS1 clips). Spoken lines take about as long in both languages, so
              this follows the voice better than character counts do (character fractions alone misplaced clips
              in three checked blocks; time fixed two of them, the third is in the review list).
    jp_only - no English op: the same on characters only.
    en_only - no Japanese op: the English ops are removed.
  More Japanese clips than anchors never happened (checked; asserted).
  Counts when this was written: 461 blocks same, 293 aligned, 33 jp_only, 47 en_only; 1,343 ops = every Japanese op.
--audio=en (--localization=audio|legends): this module is not used; the English ops stay and build_text.py moves
  their bank to the English voice banks (tools/voice/voice_banks.py, files from tools/voice/build_audio.py).

Tokens (tools/msgtool.py parse): ('c', code) = a character in PS1 codes (0x86 = newline, 0x4F = space), and
('op', opcode, args) = a control code in PS1 opcode numbers with its argument bytes. Positions are token indexes in
the English list; "anchor k" means "insert before English token k".
The penalties 0.02 / 0.04 are in the same unit as the time distance (fraction of the block): small enough to matter
only between otherwise equal places, preferring an English voice position, then a page start, then a sentence end
(how the two values were chosen: origin not recorded). See docs/RESEARCH.md §10 and §3.
Usage: python3 tools/voice/voice_map.py"""
import sys, os, glob, json, csv, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); import msgtool as M
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
def _p(x): return os.path.join(ROOT, x)
# PAGE: the ops after which a new page of text starts (NEXT, CLEAR)
PAGE = (0x9F, 0x87)
# Clip lengths in seconds. _JP: Japanese, keyed 'bank,clip' (jp_clips.json). _EN: English, keyed (PS1 bank, clip
# number = rank by first sector), from the extraction index. A clip missing from either table counts as 2.0 s
# (fallback value; origin not recorded)
_JP = json.load(open(_p('build/voice_en/jp_clips.json')))['clips']
def jp_seconds(clip, bank): return _JP.get('%d,%d' % (bank, clip), {}).get('seconds', 2.0)
_EN = {}
_rows = list(csv.DictReader(open(_p('build/voice_en/index.csv'))))
for b in {int(r['bank']) for r in _rows}:
    for i, r in enumerate(sorted([r for r in _rows if int(r['bank']) == b], key=lambda r: int(r['first_sector']))):
        _EN[(b, i)] = float(r['seconds'])
def en_seconds(clip, bank): return _EN.get((bank, clip), 2.0)
# _punct(): the PS1 character codes of . ! ? (from script/ps1_charmap.tbl), loaded on first use
_EN_PUNCT = None
def _punct():
    global _EN_PUNCT
    if _EN_PUNCT is None:
        tbl = {}
        for l in open(_p('script/ps1_charmap.tbl'), encoding='utf-8'):
            k, v = l.rstrip('\n').split('=', 1)
            if len(v) == 1: tbl.setdefault(int(k, 16), v)
        _EN_PUNCT = {k for k, v in tbl.items() if v in '.!?'}
    return _EN_PUNCT
# _chars: running count of printed characters; c[k] = characters before token k (newlines and ops count 0)
def _chars(t):
    c = [0]
    for x in t: c.append(c[-1] + (1 if x[0] == 'c' and x[1] != 0x86 else 0))
    return c
# _dp: place n clips on m >= n anchors, in order, each anchor used at most once.
# items[i] = clip i's position (0..1); anchors[j] = (token index, position 0..1, penalty).
# D[i][j] = lowest total cost of placing the first i clips among the first j anchors; each cell either skips
# anchor j (D[i][j-1]) or puts clip i on it (D[i-1][j-1] + |position difference| + penalty); P records which,
# ties going to 'take'. The walk back from D[n][m] gives the chosen anchor per clip.
# -> (anchor indexes, mean cost per clip)
def _dp(items, anchors):
    n, m = len(items), len(anchors); INF = 1e9
    assert n <= m, ('more Japanese clips than places', n, m)
    D = [[INF] * (m + 1) for _ in range(n + 1)]; D[0] = [0.0] * (m + 1); P = {}
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = D[i][j - 1]; take = D[i - 1][j - 1] + abs(items[i - 1] - anchors[j - 1][1]) + anchors[j - 1][2]
            D[i][j], P[i, j] = (take, 1) if take <= skip else (skip, 0)
    res = []; i, j = n, m
    while i > 0:
        if P[i, j]: res.append(j - 1); i -= 1
        j -= 1
    return res[::-1], D[n][m] / n
def place_jp(te, tj):
    """te: English PS1 tokens, tj: Japanese PSP tokens -> (new English tokens with the Japanese AUDIO ops, info dict)"""
    # eo: (token index, args) of every English AUDIO op; jo: args of every Japanese AUDIO op, in order.
    # In the args, byte 0 = clip and byte 2 = bank. body = the English tokens without their AUDIO ops
    eo = [(k, x[2]) for k, x in enumerate(te) if x[0] == 'op' and x[1] == 0x8F]
    jo = [x[2] for x in tj if x[0] == 'op' and x[1] == 0x8F]
    info = dict(en_ops=[[a[0], a[2]] for _, a in eo], jp_ops=[a.hex() for a in jo])
    body = [x for x in te if not (x[0] == 'op' and x[1] == 0x8F)]
    if not jo:
        info['mode'] = 'en_only' if eo else 'none'; info['place'] = []; return body, info
    if len(eo) == len(jo):
        # same count: Japanese op k goes where English op k was
        info['mode'] = 'same'; pos = [k for k, _ in eo]; order = list(range(len(jo)))
    else:
        # ch: character counts of the English block; P: the . ! ? codes; opk: token indexes of the English ops
        ch = _chars(te); tot = max(ch[-1], 1); P = _punct()
        opk = {k for k, _ in eo}
        # cand: {anchor token index: penalty}. English op positions cost 0; the token after a page op 0.02; the token
        # after . ! ? when an op, a newline (0x86) or a space (0x4F) follows 0.04; the block start 0.02.
        # setdefault keeps the lowest-penalty reason when a place qualifies twice
        cand = {k: 0.0 for k in opk}
        for k, x in enumerate(te):
            if x[0] == 'op' and x[1] in PAGE and k + 1 < len(te): cand.setdefault(k + 1, 0.02)
            if x[0] == 'c' and x[1] in P and k + 1 < len(te) and (te[k + 1][0] == 'op' or te[k + 1][1] in (0x86, 0x4F)):
                cand.setdefault(k + 1, 0.04)
        cand.setdefault(0, 0.02)
        for k in list(cand):          # a page/sentence anchor right next to an English op is the same place: drop it
            if cand[k] > 0 and (k - 1 in opk or k + 1 in opk): del cand[k]
        if eo:
            # With English ops: positions in time. d = English clip lengths, T their sum. tfrac(k) = the share of T
            # that has been spoken when token k is reached: the clips of the ops before the latest op q at or
            # before k, plus clip q's length times the share of q's characters (from op q to the next op) that
            # come before k. Before the first op: 0
            d = [en_seconds(a[0], a[2]) for _, a in eo]; T = sum(d)
            def tfrac(k):
                s = [q for q, (kk, _) in enumerate(eo) if kk <= k]
                if not s: return 0.0
                q = s[-1]; k0 = eo[q][0]; k1 = eo[q + 1][0] if q + 1 < len(eo) else len(te)
                w = (ch[k] - ch[k0]) / max(ch[k1] - ch[k0], 1)
                return (sum(d[:q]) + d[q] * w) / T
            # items: where each Japanese clip starts, as a share of the total Japanese clip time
            jd = [jp_seconds(a[0], a[2]) for a in jo]; JT = sum(jd)
            items = [sum(jd[:q]) / JT for q in range(len(jo))]
            info['mode'] = 'aligned'
        else:
            # no English ops: positions by characters, in both languages (jc = character counts of the Japanese block)
            tfrac = lambda k: ch[k] / tot
            jc = _chars(tj); jt = max(jc[-1], 1)
            items = [jc[k] / jt for k, x in enumerate(tj) if x[0] == 'op' and x[1] == 0x8F]
            info['mode'] = 'jp_only'
        # anchors in text order with their positions; the DP picks one per Japanese clip
        anchors = sorted((k, tfrac(k), p) for k, p in cand.items())
        idx, cost = _dp(items, anchors)
        pos = [anchors[j][0] for j in idx]; order = list(range(len(jo))); info['cost'] = round(cost, 3)
    info['place'] = [[p, q] for p, q in zip(pos, order)]
    # rebuild: insert Japanese op q before English token p (positions refer to te; English ops dropped)
    # at: {English token index: Japanese ops to insert before it} (several if anchors coincide; len(te) = at the end)
    at = collections.defaultdict(list)
    for p, q in zip(pos, order): at[p].append(q)
    new = []
    for k, x in enumerate(te):
        for q in at.get(k, []): new.append(('op', 0x8F, jo[q]))
        if not (x[0] == 'op' and x[1] == 0x8F): new.append(x)
    for q in at.get(len(te), []): new.append(('op', 0x8F, jo[q]))
    return new, info
# strip: a block without its 0000 terminator
def strip(b): return b[:-2] if b.endswith(b'\0\0') else b
if __name__ == '__main__':
    out = {}; stats = collections.Counter(); review = []
    # Every PSP dialogue file against the PS1 file of the same name, block by block (blocks present and non-empty in
    # both). te = PS1 tokens (8-bit), tj = PSP tokens (16-bit, read back in PS1 opcode numbers)
    for f in sorted(p.replace('\\', '/') for p in glob.glob('extracted/psp/**/*.[Mm][Ss][Gg]', recursive=True)):   # '/' on every platform
        rel = f.split('/', 2)[2]
        B = [strip(b) for b in M.blocks(open(f, 'rb').read())[0]]
        try: A = [strip(a) for a in M.blocks(open('extracted/ps1/' + rel, 'rb').read())[0]]
        except FileNotFoundError: A = []
        for i in range(min(len(A), len(B))):
            if not A[i] or not B[i]: continue
            te = M.parse(A[i], False)[0]; tj = M.parse(B[i], True, True)[0]
            _, info = place_jp(te, tj)
            if info['mode'] == 'none': continue
            out.setdefault(rel, {})['%02X' % i] = info; stats[info['mode']] += 1
            # the review list: the blocks where the counts differed, i.e. where a judgement was made
            if info['mode'] in ('aligned', 'jp_only'): review.append((rel, i, info))
    json.dump(out, open('script/voice_map.json', 'w'), indent=1, sort_keys=True)
    with open('logs/voice_map_review.md', 'w', encoding='utf-8') as fh:
        fh.write('# Voice map review (tools/voice/voice_map.py, --audio=jp)\n\nBlocks where the English and Japanese split the voice lines differently; '
                 '`cost` = mean distance in time (fraction of the block) between a Japanese clip and its place, plus anchor penalties.\n\n'
                 '| File | Block | Mode | EN ops | JP ops | cost |\n|---|---|---|---|---|---|\n')
        for rel, i, r in sorted(review, key=lambda x: -x[2]['cost']):
            fh.write(f"| {rel} | {i:02X} | {r['mode']} | {len(r['en_ops'])} | {len(r['jp_ops'])} | {r['cost']} |\n")
    print(dict(stats), 'review', len(review))
