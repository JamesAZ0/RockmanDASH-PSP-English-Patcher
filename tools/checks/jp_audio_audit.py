"""Read-only audit, also a build step: for every Japanese audio file on the PSP disc, what plays it, and whether a build
with English voices still plays it or has an English replacement. First made 2026-09-30, when the question was whether
the Japanese voice clips could be dropped from the disc. build.py runs it (without --streams) before verify_dropped.py
whenever the build has English voices (--localization=audio or legends); verify_dropped.py reads its JSON.

Writes: logs/jp_audio_audit.md (readable summary) and logs/jp_audio_audit.json (every file with its references and
        status; voice_paths, stream_paths, call_sites, english_ops_on_japanese_banks).
Reads:  build/diag/BOOT_sony_plain.BIN (Sony's program as a plain ELF; never the built one), extracted/psp/**.MSG and
        build/msg_psp/**.MSG (Japanese and built English dialogue), build/audio_psp/plan.json (which streams the build
        replaces), script/voice_rules.json; with --streams also the PSP ISO and the extracted PS1 audio in
        build/voice_en/. Needs capstone; --streams needs ffmpeg and numpy and takes about two minutes.

How the game starts audio, established by static analysis of Sony's program (docs/RESEARCH.md §10):
  - a sound id is type << 28 | bank << 16 | clip. Every .at3 is opened by a path taken from the sound tables: a
    per-type table at segment 1 + 0xA938, then a per-bank table, then that bank's array of path pointers. The voice
    bank table is at segment 1 + 0xA864 (53 slots; folder at3/xa18mNN belongs to bank NN, hex), the two stream lists
    hang off segment 1 + 0xA930;
  - a relocation scan shows the only code reading those tables is 'play' (0xACA0) and 'play2' (0xADAC), and no path is
    built at run time (the only at3 strings are the 865 table paths);
  - play / play2 are only called directly: 62 jal sites, no function pointers to them. At each site the id is a
    constant (lui/ori into a0), or comes from the dialogue AUDIO op (site 0x3D0D4), or from one of two id tables:
    site 0x92710 uses the table at vaddr 0x2816CC (stream ids for the credits), site 0xBDC38 the table at vaddr
    0x28D98C (voice ids of the City Hall TV news reports);
  - the program's own MSG-format strings (system messages, subtitles) contain no AUDIO op.
So a Japanese clip is reachable only if a dialogue block names it or one of the 62 sites can produce its id.

Status per voice clip: 'replaced' (all its dialogue lines are English text with an English voice op, or it is a news
clip whose path entry the build repoints), 'superseded' (its lines are English text but the PS1 English has no voice
there), 'never played' (no reference even in the Japanese game), or 'STILL PLAYED in the English build (code)' -
which verify_dropped.py treats as a failure. Streams are 'replaced', or 'kept' with the result of the optional
waveform comparison against the PS1 English stream of the same scene (music-only streams match apart from codec noise).

The script itself always exits 0 unless one of its assertions about the program fails (62 call sites, the id-table
index bytes, the three hand-checked second entry paths); such a failure means the input is not the program this
analysis was made for.

Usage: python3 tools/checks/jp_audio_audit.py [--streams]"""
import sys, os, struct, json, glob, collections, capstone
sys.path.insert(0, 'tools'); sys.path.insert(0, 'tools/voice')
import msgtool as M, voice_banks as VB
# S = vaddr of segment 1 (.data). File offset = vaddr + 0x80 for both segments (off() spells that out per segment)
E = open('build/diag/BOOT_sony_plain.BIN', 'rb').read(); S = 0x245200
def off(va): return va + 0x80 if va < S else va - S + 0x245280
# w: u32 at a vaddr; cstr: C string at a vaddr. The file is not relocated here: a stored pointer into .data is a
# segment-1 offset (hence the "+ S" when a table pointer is followed); pointers to the path strings are plain vaddrs
def w(va): return struct.unpack_from('<I', E, off(va))[0]
def cstr(va): o = off(va); return E[o:E.index(b'\0', o)].decode()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
# --- sound id -> path
def path_of(i):
    # t = type, b = bank, c = clip; type table -> bank table -> path array -> string
    t, b, c = (i >> 28) & 3, (i >> 16) & 0xFFF, i & 0xFFFF
    bt = w(w(S + 0xA938 + 4 * t) + S + 4 * b)
    return cstr(w(bt + S + 4 * c)) if bt else None
JP = {}                                  # path -> (bank, clip)
# walk each of the 53 voice-bank slots' path arrays; an array has no length, so stop at the first entry that is not a
# pointer into the string area or whose folder is not this bank's xa18mNN
for b in range(53):
    bt = w(S + 0xA864 + 4 * b)
    if not bt: continue
    c = 0
    while True:
        p = w(bt + S + 4 * c)
        if not (0x200000 < p < S): break
        q = cstr(p)
        if '/xa18m' not in q: break
        if q.split('/')[-2] != 'xa18m%02x' % b: break
        JP.setdefault(q, (b, c)); c += 1
STREAMS = {}
# the two stream lists (stream bank 0 and 1), walked the same way
for s_ in range(2):
    bt = w(S + 0xA930 + 4 * s_) + S; c = 0
    while 0x200000 < w(bt + 4 * c) < S:
        STREAMS.setdefault(cstr(w(bt + 4 * c)), []).append((s_, c)); c += 1
# --- call sites
# W = the program's code as words from vaddr 0 (0x23126C bytes; where this length was taken from: origin not
# recorded). A jal is opcode 3 with the target / 4 in the low 26 bits
N = 0x23126C // 4; W = struct.unpack_from(f'<{N}I', E, 0x80)
sites = [(k * 4, 'play2' if (w_ & 0x3FFFFFF) << 2 == 0xADAC else 'play') for k, w_ in enumerate(W) if w_ >> 26 == 3 and (w_ & 0x3FFFFFF) << 2 in (0xACA0, 0xADAC)]
assert len(sites) == 62, len(sites)
# site -> (id table va, reachable indexes). 0x92710: index from the byte table va 0x2816BC (values 1-6; 0 is skipped
# by 'beqz' at 0x925C8) -> credits streams. 0xBDC38: TV-news object, index = its byte +0xB, set to 0-3 by story flags
# 0x623-0x625 (0xBDAEC-0xBDB38); state 4 (flag 0x626) takes the constant path 0xBD67C instead.
# call site -> (vaddr of its id table, the indexes that can occur)
TABLES = {0x92710: (S + 0x3C4CC, range(1, 7)), 0xBDC38: (S + 0x4878C, range(0, 4))}
code_ids = collections.defaultdict(list)
for a, fn in sites:
    # disassemble the 15 instructions before the jal and its delay slot, and take the last lui / ori into a0
    ins = list(md.disasm_lite(E[0x80 + a - 60: 0x80 + a + 8], a - 60))
    if a == 0x3D0D4: continue                                        # MSG AUDIO op
    if a in TABLES:
        tv, ks = TABLES[a]
        # the byte table at vaddr 0x2816BC that maps the credits state to an id-table index must be 0,1,2,...,6,0
        assert list(E[off(S + 0x3C4BC): off(S + 0x3C4BC) + 8]) == [0, 1, 2, 3, 4, 5, 6, 0]
        for k in ks: code_ids[w(tv + 4 * k)].append(f'{hex(a)} table {hex(tv)}[{k}]')
        continue
    hi = lo = None
    for x in ins:
        if x[0] > a + 4: break
        if x[2] == 'lui' and x[3].startswith('$a0,'): hi, lo = int(x[3].split(', ')[1], 0), 0
        elif x[2] == 'ori' and x[3].startswith('$a0, $a0,') and hi is not None: lo = int(x[3].split(', ')[2], 0)
    assert hi is not None, ('unresolved call site', hex(a))
    code_ids[(hi << 16) | lo].append(f'{hex(a)} constant')
# second paths into three call sites (a branch lands between the id set-up and the jal): checked by hand
# (call site, address of the jump that also reaches it, id set in that jump's delay slot): the jump must be a "j" to
# the site and the next word must carry the low half of the id
for a, src, sid in ((0x12FDA4, 0x12FDBC, 0x20010013), (0x130D3C, 0x130D54, 0x20010013), (0x13B920, 0x13B940, 0x20000015)):
    assert (W[src // 4] >> 26) == 2 and ((W[src // 4] & 0x3FFFFFF) << 2) == a and (W[src // 4 + 1] & 0xFFFF) == sid & 0xFFFF
    code_ids[sid].append(f'{hex(a)} constant (via {hex(src)})')
# --- Japanese script (MSG) references, and the English build's text
# strip: drop the two zero bytes that pad a block. jp_msg[(bank, clip)] = [(file, block, number of voice ops in the
# English block at the same position)]; en_jp_bank_ops = English ops whose bank is not one of the English slots
def strip(b): return b[:-2] if b.endswith(b'\0\0') else b
jp_msg = collections.defaultdict(list); en_voiced = {}; en_jp_bank_ops = []
slots = set(VB.SLOTS)
for f in sorted(p.replace('\\', '/') for p in glob.glob('extracted/psp/**/*.[Mm][Ss][Gg]', recursive=True)):   # '/' on every platform
    rel = f.split('/', 2)[2]
    en_blocks = M.blocks(open('build/msg_psp/' + rel, 'rb').read())[0] if os.path.exists('build/msg_psp/' + rel) else []
    for i, b in enumerate(M.blocks(open(f, 'rb').read())[0]):
        # AUDIO = PS1 code 0x8F; its argument bytes are clip, 0, bank, 0
        ops = [x[2] for x in M.parse(strip(b), True, True)[0] if x[0] == 'op' and x[1] == 0x8F]
        eo = [x[2] for x in M.parse(strip(en_blocks[i]), True, True)[0] if x[0] == 'op' and x[1] == 0x8F] if i < len(en_blocks) else []
        for a_ in ops: jp_msg[(a_[2], a_[0])].append((rel, i, len(eo)))
    for i, b in enumerate(en_blocks):
        for x in M.parse(strip(b), True, True)[0]:
            if x[0] == 'op' and x[1] == 0x8F and x[2][2] not in slots: en_jp_bank_ops.append((rel, i, x[2][2], x[2][0]))
# --- English stream plan
plan = json.load(open('build/audio_psp/plan.json'))['files']
replaced = {q.split('/')[-1] for q in plan if '/xa37s00/' in q}
# --- kept streams: are they language-neutral? (--streams) Waveform comparison of each Japanese PSP stream with its PS1
# English counterpart (same scene): after aligning, the residual energy per 1-s window; music-only streams match to
# codec noise, a window with speech in only one version doesn't (residual/energy > 0.5).
STREAM_CMP = {}
if '--streams' in sys.argv:
    import csv, io, subprocess, numpy as np, pycdlib, inputs as IN
    iso = pycdlib.PyCdlib(); iso.open(IN.PSP); os.makedirs('build/analysis/jp_streams', exist_ok=True)
    names = json.load(open('build/voice_en/jp_clips.json'))['clips']; idx = list(csv.DictReader(open('build/voice_en/index_streams.csv')))
    # rank(b, r): the extracted PS1 English stream of stream bank b whose rank by first sector is r
    def rank(b, r):
        x = sorted([x for x in idx if int(x['bank']) == b], key=lambda x: int(x['first_sector']))[r]
        return 'build/voice_en/s%02d_c%02d_%s.xa' % (b, int(x['channel']), x['clip_in_channel'])
    # pcm: decode to mono 8 kHz samples (enough to tell speech from no speech, and fast)
    def pcm(f): return np.frombuffer(subprocess.run(['ffmpeg', '-v', 'error', *(['-f', 'psxstr'] if f.endswith('.xa') else []), '-i', f, '-ac', '1', '-ar', '8000', '-f', 's16le', '-'], capture_output=True, check=True).stdout, '<i2').astype(np.float64)
    for k, v in names.items():
        b, r = map(int, k.split(','))
        # in jp_clips.json the two stream lists are numbered as banks 0x33 and 0x34
        if b not in (0x33, 0x34): continue
        n = v['path'].split('/')[-1]; f = 'build/analysis/jp_streams/' + n
        if not os.path.exists(f):
            bb = io.BytesIO(); iso.get_file_from_iso_fp(bb, iso_path='/PSP_GAME/USRDIR/DAT/at3/' + v['path']); open(f, 'wb').write(bb.getvalue())
        # align by the peak of the cross-correlation (FFT), remove the best-fitting multiple of the English signal,
        # and measure what is left per 1-second window relative to the window's energy (8e6 keeps silent windows from
        # dividing by ~0)
        a, e = pcm(f), pcm(rank(b - 0x33, r)); L = 1 << int(np.ceil(np.log2(len(a) + len(e))))
        c = np.fft.irfft(np.fft.rfft(a, L) * np.conj(np.fft.rfft(e, L)), L); lag = int(np.argmax(c)); lag = lag if lag < L // 2 else lag - L
        x, y = (a[lag:], e) if lag >= 0 else (a, e[-lag:]); m = min(len(x), len(y)); x, y = x[:m], y[:m]
        res = x - (x @ y) / (y @ y + 1) * y
        rat = [float((res[i:i+8000] ** 2).sum() / ((x[i:i+8000] ** 2).sum() + 8e6)) for i in range(0, m - 8000, 8000)]
        STREAM_CMP[n] = dict(ps1=rank(b - 0x33, r).split('/')[-1], seconds=[round(len(a) / 8000, 1), round(len(e) / 8000, 1)],
                             windows=len(rat), differing_windows=sum(q > 0.5 for q in rat), worst=round(max(rat), 3))
# --- classify
rows = []
for p, (b, c) in sorted(JP.items(), key=lambda x: x[1]):
    # voice ids are type 0, so the id is just bank << 16 | clip
    sid = (b << 16) | c; code = code_ids.get(sid, []); msg = jp_msg.get((b, c), [])
    _cv = json.load(open('script/voice_rules.json')).get('code_voice', {})
    _cvp = {e['jp'] for e in _cv.get('table', {}).get('entries', [])} | ({_cv['constant']['jp']} if 'constant' in _cv else set())
    if code and p.split('at3/')[1] in _cvp: st = 'replaced: the id the game code starts now resolves to the English clip (voice_rules.json code_voice, --audio=en)'
    elif code: st = 'STILL PLAYED in the English build (code)'
    elif msg:
        st = 'replaced: its lines are English text, voiced in English' if all(n for _, _, n in msg) else \
             'superseded: its lines are English text (' + ', '.join(f'{r} {i:02X}' for r, i, n in msg if not n) + ' unvoiced in the PS1 English)'
    else: st = 'never played (no script or code reference, also in the Japanese game)'
    rows.append(dict(kind='voice', path=p, bank=b, clip=c, code=code, script=[f'{r} {i:02X}' for r, i, _ in msg], status=st))
for p, ids in sorted(STREAMS.items()):
    # stream ids are type 2: 2 << 28 | list << 16 | index
    name = p.split('/')[-1]; refs = [x for s_, c in ids for x in code_ids.get((2 << 28) | (s_ << 16) | c, [])]
    cmp_ = STREAM_CMP.get(name)
    if name in replaced: st = 'replaced by the English stream'
    elif cmp_ is None: st = 'kept (run with --streams to compare with the PS1 English)'
    elif cmp_['differing_windows'] == 0: st = 'kept: identical to the PS1 English version apart from codec noise (no language content)'
    elif 'xa37s00/' + name in json.load(open('script/voice_rules.json')).get('kept_japanese_audio', {}):
        st = 'kept by decision (voice_rules.json kept_japanese_audio): PSP-only music, differs from the PS1 English (%d of %d s)' % (cmp_['differing_windows'], cmp_['windows'])
    else: st = 'kept: DIFFERS from its PS1 English counterpart (%d of %d s) - listen' % (cmp_['differing_windows'], cmp_['windows'])
    rows.append(dict(kind='stream', path=p, ids=ids, code=refs, status=st, compare=cmp_))
out = dict(voice_paths=len(JP), stream_paths=len(STREAMS), call_sites=len(sites), english_ops_on_japanese_banks=en_jp_bank_ops, rows=rows)
json.dump(out, open('logs/jp_audio_audit.json', 'w'), indent=1)
cnt = collections.Counter(r['status'] if not r['status'].startswith('superseded') else 'superseded' for r in rows)
L = ['# Japanese audio audit (tools/checks/jp_audio_audit.py)', '', f'{len(JP)} Japanese voice clips, {len(STREAMS)} cutscene streams, {len(sites)} code call sites.', '',
     f'English text ops that still name a Japanese bank: {len(en_jp_bank_ops)}', '', '| status | files |', '|---|---|'] + [f'| {k} | {v} |' for k, v in cnt.most_common()]
L += ['', '## Still played in the English build', ''] + [f"- {r['path'].split('at3/')[1]} (bank {r['bank']:#x} clip {r['clip']:#x}): {', '.join(r['code'])}" for r in rows if r['status'].startswith('STILL')]
L += ['', '## Superseded (Japanese line voiced, PS1 English line not)', ''] + [f"- {r['path'].split('at3/')[1]}: {r['status'].split('(')[1][:-1]}" for r in rows if r['status'].startswith('superseded')]
L += ['', '## Never played', ''] + [', '.join(r['path'].split('/')[-2] + '/' + r['path'].split('/')[-1] for r in rows if r['status'].startswith('never'))]
L += ['', '## Streams', ''] + [f"- {r['path'].split('/')[-1]}: {r['status']}" + (f" (vs {r['compare']['ps1']}, {r['compare']['seconds'][0]} / {r['compare']['seconds'][1]} s, worst window {r['compare']['worst']})" if r.get('compare') else '') for r in rows if r['kind'] == 'stream']
open('logs/jp_audio_audit.md', 'w').write('\n'.join(L) + '\n')
print(cnt); print('still played:', [r['path'].split('/')[-1] for r in rows if r['status'].startswith('STILL')]); print('en ops on JP banks', len(en_jp_bank_ops))
