"""Convert the script: English PS1 dialogue -> PSP-format MSG files in build/msg_psp/ (second data step of build.py).

Inputs  extracted/psp/**/*.msg   the 129 Japanese PSP dialogue files (tools/extract.py), each = entry header + data
        extracted/ps1/**/*.msg   the 129 English PS1 files, same relative paths
        script/fill_rules.json   what to put in PSP blocks that have no English counterpart
        script/text_edits.json   the approved formatting edits to PS1 lines
        script/ps1_charmap.tbl   PS1 English character -> code, for text written in the rule files
Outputs build/msg_psp/<same path>   complete MSG entries (the Japanese header with the new size; tools/msgtool.py)
        logs/build_text_report.md   which rule filled which block
Nothing is written into any game image here; tools/pack_inplace.py puts the files into the ISO.

How a file is built. The two games' MSG files correspond path for path and block for block (docs/RESEARCH.md §3),
so the output has exactly the Japanese file's block count, and for each block index:
1. If the PS1 file has a non-empty block at that index, it is used: parsed (msgtool.parse), given the approved text
   edits, the PSP-only choice ops and the voice ops (below), and encoded as PSP 16-bit text (msgtool.tokens_to_psp).
   The wording is the PS1's, byte for byte, apart from script/text_edits.json.
2. If both are empty the block stays empty.
3. If only the Japanese block has text (lines the PSP version added or keeps in another file; 352 slots), the first
   matching rule in script/fill_rules.json is used, tried in this order:
     copy         the English block with the same index from a sibling PS1 file (the PSP moved some blocks between
                  the files of a stage); verbatim PS1 text
     copy_marked  an English block from another file or index that matches only approximately; gets the review marker
     ps1_layout   a PSP-only block rebuilt from PS1 English words on the Japanese block's control codes, optionally
                  with another window size; verbatim PS1 text, so no marker
     authored     a translation written for this project: the Japanese block's control codes are kept and each run
                  of Japanese text is replaced by the rule's English; gets the review marker
   A block no rule covers is left empty and printed as UNHANDLED (the build expects none).
Review marker: the project's ground rule is that only PS1 English lines go into the game. Every line that is not a
verbatim PS1 line therefore starts with the marker text from fill_rules.json ("R*") so it can be found and reviewed
in play. No '*' glyph was found in the PSP font, so it is drawn with the placeholder glyph STAR_PSP.

PSP-specific control codes handled here (the rest is in msgtool.py):
  - Voice ops. AUDIO (0x8F; arguments clip, 0, bank, 0) starts a voice clip and the text waits for it. The two games
    number clips and banks differently, so PS1 numbers on the PSP name a missing bank (the text box then waits
    forever) or the wrong clip (found in play; docs/RESEARCH.md §10). With --audio=en each op's bank byte is moved to
    the free PSP bank slot that holds the English clips (tools/voice/voice_banks.py SLOTS; the clip number stays).
    With --audio=jp the English ops are removed and the Japanese block's ops are placed in the English text
    (tools/voice/voice_map.py place_jp).
  - The Data save menu's PSP-only choice ops A3 / AB: psp_choice_ops().

Usage: python3 tools/build_text.py [--audio=en|jp]
--audio is an internal argument, set by build.py: jp for --localization=text, en for audio and legends."""
import sys, os, glob, json, struct, collections, re
sys.path.insert(0, 'tools'); import msgtool as M; from jpdump import dump
# internal argument, set by build.py (see the docstring): which voice clips the AUDIO ops must name
AUDIO = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--audio=')), 'en')
assert AUDIO in ('jp', 'en'), AUDIO
sys.path.insert(0, 'tools/voice'); import voice_map as VM, voice_banks as VB
# counters for the summary line printed at the end (voice ops by kind, text edits by id)
VOICE = collections.Counter()
EDITS = json.load(open('script/text_edits.json'))['edits'] if os.path.exists('script/text_edits.json') else []
EDIT_HITS = collections.Counter()
# English text -> PS1 character codes (TBL is filled further down, before this is first called)
def _codes(text):
    # '{56}' = the PS1 character code 0x56 itself (for symbols the table has no letter for, e.g. the button icons
    # 0x54 circle, 0x55 triangle, 0x56 cross, 0x57 square)
    out = []
    for part in re.split(r'(\{[0-9A-Fa-f]{2}\})', text):
        if re.fullmatch(r'\{[0-9A-Fa-f]{2}\}', part): out.append(int(part[1:3], 16))
        else: out += [TBL[ch] for ch in part]
    return out
def apply_edits(rel, blk, tokens):
    """script/text_edits.json: approved formatting adjustments to PS1 English lines (e.g. Memory card -> Memory Stick).
    An edit names its blocks as [file name, block index in hex] and has
      replace    [old, new] pairs: the first occurrence of the character run old becomes new
      drop_page  texts: the page (the tokens between two CLEAR ops, 0x87) containing the text is removed together with
                 the CLEAR that ends it; it must be neither the first nor the last page
    Every edit must match where it says (asserted here); every rule must be used (asserted at the end of the build)."""
    base = os.path.basename(rel).lower()
    for e in EDITS:
        if [base, blk] not in [[b.lower(), k.upper()] for b, k in e['blocks']]: continue
        for old, new in e.get('replace', []):
            o, n = _codes(old), _codes(new); hit = 0
            for k in range(len(tokens) - len(o) + 1):
                if all(tokens[k + j] == ('c', o[j]) for j in range(len(o))):
                    tokens = tokens[:k] + [('c', c) for c in n] + tokens[k + len(o):]; hit += 1; break
            assert hit, ('edit did not match', e['id'], rel, blk, old)
        for text in e.get('drop_page', []):
            o = _codes(text); starts = [0] + [k + 1 for k, x in enumerate(tokens) if x[0] == 'op' and x[1] == 0x87]
            found = None
            for si, st in enumerate(starts):
                en = starts[si + 1] if si + 1 < len(starts) else len(tokens)
                seg = [x for x in tokens[st:en] if x[0] == 'c' and x[1] != 0x86]
                flat = [x[1] for x in seg]
                if any(flat[k:k + len(o)] == o for k in range(len(flat) - len(o) + 1)): found = (st, en); break
            assert found and found[0] > 0 and found[1] < len(tokens), ('drop_page did not match', e['id'], rel, blk, text)
            tokens = tokens[:found[0]] + tokens[found[1]:]
        EDIT_HITS[e['id']] += 1
    return tokens
# PS1 choice op -> its PSP-only variant in the Data save menu: SEL 96 -> A3, MULTI 97 -> AB
PSP_CHOICE = {0x96: 0xA3, 0x97: 0xAB}
def psp_choice_ops(tokens, tj):
    """The PSP's Data menu (Recharge Energy / Save / Tell me... / Cancel, 30 blocks) marks the Save choice with the
    PSP-only op A3 instead of SEL 96 and ends with AB instead of MULTI 97 (same arguments). The English PS1 block has
    96/97, so on the PSP "Save" opened the Load screen (found in play, 2026-09-30). Where the
    Japanese block uses A3/AB, the English op in the same position (k-th SEL / k-th MULTI) takes the PSP code; the
    arguments must match (asserted)."""
    jseq = {0x96: [x for x in tj if x[0] == 'op' and x[1] in (0x96, 0xA3)], 0x97: [x for x in tj if x[0] == 'op' and x[1] in (0x97, 0xAB)]}
    if not any(x[1] in (0xA3, 0xAB) for v in jseq.values() for x in v): return tokens
    n = {0x96: 0, 0x97: 0}; out = []
    for x in tokens:
        if x[0] == 'op' and x[1] in n:
            k = n[x[1]]; n[x[1]] += 1; j = jseq[x[1]][k]
            if j[1] == PSP_CHOICE[x[1]]:
                assert j[2] == x[2], ('choice op arguments differ', x, j); x = ('op', j[1], x[2]); VOICE['choice_op'] += 1
        out.append(x)
    assert n[0x96] == len(jseq[0x96]) and n[0x97] == len(jseq[0x97]), 'choice op counts differ'
    return out
def to_psp(tokens, jp_block):
    """English PS1 tokens -> PSP bytes, with the PSP-only choice ops and the voice ops for the chosen audio mode.
    jp_block: the Japanese PSP block at the same index (raw bytes), the reference for both."""
    if jp_block: tokens = psp_choice_ops(tokens, M.parse(jp_block, True, True)[0])
    if AUDIO == 'jp':
        tj = M.parse(jp_block, True, True)[0] if jp_block else []
        tokens, info = VM.place_jp(tokens, tj); VOICE[info['mode']] += 1
    elif AUDIO == 'en':   # English clips: PS1 bank b -> free PSP bank slot (tools/voice/voice_banks.py)
        new = []
        for x in tokens:
            if x[0] == 'op' and x[1] == 0x8F:
                # AUDIO arguments: clip, 0, bank, 0 -> only the bank byte changes
                a = x[2]; assert a[2] < len(VB.SLOTS), ('English bank out of range', a.hex())
                x = ('op', 0x8F, bytes([a[0], a[1], VB.SLOTS[a[2]], a[3]])); VOICE['en_op'] += 1
            new.append(x)
        tokens = new
    return M.tokens_to_psp(tokens)
# --- fill rules for the Japanese-only blocks, and the character table for text written in the rule files
R = json.load(open('script/fill_rules.json'))
MARK = R['marker']
STAR_PSP = 0x0010   # PLACEHOLDER glyph for '*': no '*' found in the PSP font; code 0x10 is the middle dot ('・')
# character -> PS1 code from script/ps1_charmap.tbl, which was compiled with reference to DashEditor (lines "XX=c"); the first code listed for a character wins.
# A full-width space in a rule file means the same as a plain space.
TBL = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: TBL.setdefault(v, int(k, 16))
TBL['　'] = TBL[' ']

def text_tokens(s):
    """English text from a rule file -> tokens. '\n' newline, '{XXX}' raw PSP character code in hex (e.g. '{4F}',
    the 12-px full-width space), '*' the placeholder glyph. Other characters become PS1 codes, which
    msgtool.tokens_to_psp maps to PSP codes like the rest of the script."""
    out = []; i = 0
    while i < len(s):
        ch = s[i]
        if ch == '\n': out.append(('c', 0x86))
        elif ch == '{':
            j = s.index('}', i); out.append(('raw', int(s[i+1:j], 16))); i = j
        elif ch == '*': out.append(('raw', STAR_PSP))
        else:
            if ch not in TBL: raise KeyError(f'no glyph for {ch!r}')
            out.append(('c', TBL[ch]))
        i += 1
    return out

def insert_marker(tokens):
    """Insert the review marker right after the first DECOR op (0x93; the displayed text starts after it), else
    before the first character."""
    mt = text_tokens(MARK)
    for k, x in enumerate(tokens):
        if x[0] == 'op' and x[1] == 0x93: return tokens[:k+1] + mt + tokens[k+1:]
    for k, x in enumerate(tokens):
        if x[0] in ('c', 'raw'): return tokens[:k] + mt + tokens[k:]
    return mt + tokens

def runs_of(tokens):
    """Split JP (PSP) tokens into ops and text runs; returns list of ('op',tok) / ('run',[toks],text).
    text is the run decoded with jptable.T (kana, Latin, symbols; a newline as the two characters backslash-n; any
    other code, kanji included, as {XXX}). That string is the key into the 'runs' of an authored / ps1_layout rule."""
    from jptable import T
    out = []; cur = []
    def flush():
        if cur:
            txt = ''.join('\\n' if c == 0x86 else T.get(c, '{%X}' % c) for _, c in cur)
            out.append(('run', list(cur), txt)); cur.clear()
    for x in tokens:
        if x[0] == 'c': cur.append(x)
        else: flush(); out.append(('op', x))
    flush(); return out

# 'authored' rule: keep the Japanese block's ops, replace each text run by rule['runs'][run]; a run mapped to null is
# kept as it is (Japanese codes written out raw). Raises KeyError if the rule does not cover a run: the caller then
# tries the next rule, so a rule applies to exactly the blocks whose runs it lists. The result gets the marker.
def authored_block(jp_block, rule):
    t, _ = M.parse(jp_block, True, True)
    out = []
    for item in runs_of(t):
        if item[0] == 'op':
            op = item[1]; out.append(op)
        else:
            _, toks, txt = item
            if txt not in rule['runs']: raise KeyError(f'run not covered: {txt!r}')
            rep = rule['runs'][txt]
            if rep is None: out += [('raw', c) if c != 0x86 else ('c', 0x86) for _, c in toks]
            else: out += text_tokens(rep)
    return M.tokens_to_psp(insert_marker(out))

def ps1_layout_block(jp_block, rule):
    """PSP-only block rebuilt from PS1 English text (no R*): keep the JP block's ops, optionally replace the WIN
    geometry (formatting), replace each text run. '{4F}' = the 12-px space the cursor column needs.
    rule['window']: 6 argument bytes of WIN (0x8C) in hex = x (u16), y (u16), columns, rows; e.g. the pause-menu
    redraw copy takes the PS1 box 58 00 50 00 0c 06 (x 0x58, y 0x50, 12 columns, 6 rows), not the PSP's 8 columns."""
    t, _ = M.parse(jp_block, True, True); out = []
    for item in runs_of(t):
        if item[0] == 'op':
            op = item[1]
            if op[1] == 0x8C and rule.get('window'): op = ('op', 0x8C, bytes.fromhex(rule['window']))
            out.append(op)
        else:
            if item[2] not in rule['runs']: raise KeyError(f'run not covered: {item[2]!r}')
            out += text_tokens(rule['runs'][item[2]])
    return M.tokens_to_psp(out)

# a stored block ends in 00 00; the converters work on blocks without it (msgtool.build_msg adds it back)
def strip(b): return b[:-2] if b.endswith(b'\0\0') else b
def en_blocks(rel):
    A, _ = M.blocks(open('extracted/ps1/' + rel, 'rb').read()); return [strip(a) for a in A]

def line_overflows(psp_block):
    """Return list of (line_text_len, window_cols) where a displayed line has more characters than its WIN has
    columns (WIN argument byte 4). A line ends at a newline, a new WIN, NEXT (0x9F), CLEAR (0x87) or CLOSE (0x84).
    Informational only: the English text is variable-width, so a character count says little (see the report's
    'Line widths' note); the results are collected in 'over' but not written anywhere."""
    t, _ = M.parse(psp_block, True, True); cols = None; n = 0; res = []
    for x in t:
        if x[0] == 'op':
            if x[1] == 0x8C: cols = x[2][4]
            if x[1] in (0x8C, 0x9F, 0x87, 0x84):
                if cols and n > cols: res.append((n, cols))
                n = 0
        elif x[1] == 0x86:
            if cols and n > cols: res.append((n, cols))
            n = 0
        else: n += 1
    if cols and n > cols: res.append((n, cols))
    return res

# --- main loop: one output file per Japanese PSP file. B = Japanese blocks, A = English PS1 blocks of the same path.
# rel = path below extracted/psp/ (e.g. ST00_01/mess/st00_01.msg), blk = block index as two hex digits.
log = collections.defaultdict(list); unhandled = []; over = []
for f in sorted(p.replace('\\', '/') for p in glob.glob('extracted/psp/**/*.[Mm][Ss][Gg]', recursive=True)):   # '/' on every platform
    rel = f.split('/', 2)[2]; base = os.path.basename(rel).lower()
    jp = open(f, 'rb').read(); B, _ = M.blocks(jp); B = [strip(b) for b in B]
    A = en_blocks(rel)
    out = []
    for i, b in enumerate(B):
        a = A[i] if i < len(A) else b''
        # case 1: the PS1 has this block
        if a:
            ta, ok = M.parse(a, False)
            if not ok: raise ValueError('PS1 block did not parse cleanly')
            out.append(to_psp(apply_edits(rel, '%02X' % i, ta), b)); continue
        # case 2: empty on both. Case 3 below: Japanese only -> fill rules, in order
        if not b: out.append(b''); continue
        blk = f'{i:02X}'; done = False
        for r in R['copy']:
            if r['target_msg'].lower() == base and blk in r['blocks']:
                src = en_blocks(r['source'])[i]
                if not src: raise ValueError(f'empty source {r["source"]} {blk}')
                c = to_psp(apply_edits(rel, blk, M.parse(src, False)[0]), b); out.append(c); log['copy'].append((rel, blk, r['source'], blk))
                over += [(rel, blk, 'copy', o) for o in line_overflows(c)]; done = True; break
        if not done:
            for r in R['copy_marked']:
                if r['target_msg'].lower() == base and blk == r['block']:
                    src = en_blocks(r['source'])[int(r['source_block'], 16)]
                    t, ok = M.parse(src, False); c = to_psp(insert_marker(t), b); out.append(c)
                    log['copy_marked'].append((rel, blk, r['source'], r['source_block']))
                    over += [(rel, blk, 'copy_marked', o) for o in line_overflows(c)]; done = True; break
        if not done:
            for r in R.get('ps1_layout', []):
                if r['target_msg'].lower() == base and blk == r['block']:
                    c = ps1_layout_block(b, r); out.append(c); log['ps1_layout'].append((rel, blk, r['id'], 'PS1 text'))
                    done = True; break
        if not done:
            for r in R['authored']:
                try: c = authored_block(b, r)
                except KeyError: continue
                out.append(c); log['authored'].append((rel, blk, r['id'], r['category']))
                over += [(rel, blk, r['id'], o) for o in line_overflows(c)]; done = True; break
        if not done:
            out.append(b''); unhandled.append((rel, blk, dump(b)[:120]))
    # self-check: every built block must re-parse cleanly as PSP
    for k, c in enumerate(out):
        _, ok = M.parse(c, True, True)
        if not ok: raise ValueError(f'built block does not parse: {rel} {k:02X}')
    dst = 'build/msg_psp/' + rel; os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'wb').write(M.build_msg(jp, out))

with open('logs/build_text_report.md', 'w', encoding='utf-8') as fh:
    fh.write('# Text build report\n\nGenerated by tools/build_text.py from script/fill_rules.json.\n\n')
    fh.write(f"- copy (English sibling line, same index): {len(log['copy'])} slots\n- copy_marked (R*): {len(log['copy_marked'])} slots\n- authored (R*): {len(log['authored'])} slots\n- unhandled (left empty): {len(unhandled)}\n")
    fh.write(f"- '*' in the marker is a placeholder glyph (PSP code 0x{STAR_PSP:04X}) until a real '*' glyph is found.\n\n")
    fh.write(f"- ps1_layout (PS1 English, PSP-only block, no R*): {len(log['ps1_layout'])} slots\n\n")
    for k in ('copy', 'copy_marked', 'authored', 'ps1_layout'):
        fh.write(f'## {k}\n\n| File | Block | Source/rule | Detail |\n|---|---|---|---|\n')
        for row in log[k]: fh.write('| ' + ' | '.join(row) + ' |\n')
        fh.write('\n')
    fh.write('## Unhandled\n\n' + ''.join(f'- {r} {b}: {t}\n' for r, b, t in unhandled) + '\n')
    fh.write('## Line widths\n\nNot checked: English window sizes (WIN SX) assume the English variable-width font, so a character-count check against SX is not meaningful. Needs an emulator test.\n')
print({k: len(v) for k, v in log.items()}, 'unhandled', len(unhandled), '| audio', AUDIO, dict(VOICE), '| text edits', dict(EDIT_HITS))
for e in EDITS: assert EDIT_HITS[e['id']], ('text edit never applied', e['id'])
for u in unhandled: print('UNHANDLED', u)
