"""English audio files for the ISO -> build/audio_psp/ + build/audio_psp/plan.json {iso path: built file}. Run by
build.py for --localization=audio|legends (English audio), after patch_eboot_voice.py; not run for text.
tools/pack_inplace.py --audio (internal flag, set by build.py) writes each planned file over the Japanese one (in
place if it fits, else in a freed slot or after the image end) and updates its directory record; the game opens .at3
files by path, so an LBA change is harmless.
Inputs: the extracted PS1 clips and their indexes in build/voice_en/ (extract_voice_en.py, with and without
--streams), build/voice_en/jp_clips.json (jp_clips.py), script/subtitles.csv, script/voice_rules.json.
Stream mapping: PSP bank 0x33 path n = PS1 stream file s00 (XA37S00E) clip rank n, bank 0x34 path n = s01 rank n
(66 of 69 durations within 1 s; confirmed from transcripts of the scenes).
Mode (internal argument; build.py passes `en`):
  en     - all English voices: the 691 voice clips -> new folder at3/xaen/eBB_CC.at3 (mono, 744-byte
           frames; the EBOOT side is tools/voice/patch_eboot_voice.py) and the English cutscene streams over the
           Japanese ones: every stream with a PSP subtitle scene (A n = s00 rank n, B n = s01 rank n+2) plus the
           other voiced ones (s00 30 na = prologue narration, s01 0 staff = opening, s01 29 gts2 = launch line),
           except the scenes in script/voice_rules.json keep_japanese_scenes (none now); stream_overrides picks another
           rank for a scene (A15: the US disc's rank 15 is the Japanese track, its English dub is rank 18, checked by
           ear; it also goes over the variant bsr2.at3). Music-only streams stay Japanese
           (credits cd00-05/cd00long, mini0-2, battle loops: same music, and the PSP credits are re-edited).
           Stream frames: 1864 bytes (320 kb/s; 2026-09-30). atracdenc low-passes by bit rate (measured): 744 cuts
           above ~5 kHz, 1120 ~9 kHz, 1488 ~12 kHz, 1864 ~16 kHz, 2048 ~18 kHz. Sony's Japanese streams (744) keep
           ~15-16 kHz, and the PS1 source has content to ~17 kHz, so 1864 is the lowest rate that sounds as bright as
           the Japanese version. No size cap any more (an earlier 5.1 MB cap, the largest Japanese stream, was a
           guess); the biggest stream is now staff.at3, ~12.6 MB.
           Only standard ATRAC3plus frame sizes (376/560/744/936/1120/1488/1864/2048); 1024 was used by mistake
           in early builds.
           Encoded files are cached (rebuilt only when the source or the settings change); run once before build.py
           if it would take too long: python3 tools/voice/build_audio.py en
The encoder is atracdenc, found by tools/exttools.py (ATRACDENC=, bin/<platform>/, PATH); its source with the
project's frame-size change is in src/atracdenc. See docs/RESEARCH.md §10.
Usage: python3 tools/voice/build_audio.py en
(An earlier three-file codec-proof mode was removed on 2026-09-30.)"""
import sys, os, csv, json, hashlib
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
sys.path.insert(0, os.path.dirname(__file__)); import encode_at3 as ENC, xa
MODE = sys.argv[1] if len(sys.argv) > 1 else 'en'
OUT = 'build/audio_psp'; os.makedirs(OUT, exist_ok=True)
V = 'build/voice_en/'
# rank(): the extracted clip file of clip number i of PS1 bank / stream file b (clips ordered by first sector, the
# game's own numbering); idx = the index CSV to read
def rank(prefix, b, i, idx):
    rs = sorted([r for r in csv.DictReader(open(V + idx)) if int(r['bank']) == b], key=lambda r: int(r['first_sector']))
    r = rs[i]; return V + '%s%02d_c%02d_%s.xa' % (prefix, b, int(r['channel']), r['clip_in_channel'])
AT3 = '/PSP_GAME/USRDIR/DAT/at3/'
if MODE == 'en':
    import voice_banks as VB
    # a job = (ISO path to write, source clip, mono|stereo, frame sizes to try in order)
    jobs = []
    for b, lst in VB.clips().items():
        for c, src in enumerate(lst): jobs.append((VB.iso_path(b, c), src, 'mono', [744]))
    keep = json.load(open('script/voice_rules.json'))['keep_japanese_scenes']
    subs = list(csv.DictReader(open('script/subtitles.csv', encoding='utf-8-sig')))
    # want: (PS1 stream file 0|1, clip rank) of every scene with subtitles: A n -> (0, n), B n -> (1, n + 2)
    want = {(0, int(r['scene'])) for r in subs if r['set'] == 'A' and 'A%02d' % int(r['scene']) not in keep}
    want |= {(1, int(r['scene']) + 2) for r in subs if r['set'] == 'B' and 'B%02d' % int(r['scene']) not in keep}
    # voiced streams without a subtitle scene: prologue narration (na), opening (staff), launch line (gts2)
    want |= {(0, 30), (1, 0), (1, 29)}
    names = json.load(open(V + 'jp_clips.json'))['clips']          # Japanese stream paths: bank 0x33 = s00, 0x34 = s01
    over = json.load(open('script/voice_rules.json')).get('stream_overrides', {})
    for b, r in sorted(want):
        # target = the Japanese stream at the same number: path n of PSP bank 0x33 (s00) / 0x34 (s01)
        src = (b, r); target = '/PSP_GAME/USRDIR/DAT/at3/' + names['%d,%d' % (0x33 + b, r)]['path']; extra = []
        sc = ('A%02d' % r) if b == 0 else ('B%02d' % (r - 2))
        if sc in over:                                               # e.g. A15: English dub at another rank
            src = (b, over[sc]['ps1_rank']); extra = over[sc].get('also_replace', [])
        jobs.append((target, rank('s', src[0], src[1], 'index_streams.csv'), 'stereo', [1864]))
        for e in extra: jobs.append((target.rsplit('/', 1)[0] + '/' + e, rank('s', src[0], src[1], 'index_streams.csv'), 'stereo', [1864]))
else:
    sys.exit('unknown mode ' + MODE)
LIMIT = 1 << 40   # no size cap (see the stream note above)
# cache key part: a hash of encode_at3.py, xa.py and the atracdenc program, so a change to the decoder, the resampler
# or the encoder re-encodes everything
ENC_ID = hashlib.md5(open(ENC.__file__, 'rb').read() + open(xa.__file__, 'rb').read() + open(ENC.ENC, 'rb').read()).hexdigest()[:8]
# The cache. names(job) -> (output file, its .json, cache key): the output is <folder>_<file>.at3 and the key is the
# source (path, mtime), frame sizes, channels and encoder. cached_info(job) -> the plan entry of an output made with
# the same key, else None. one(job, pcm) encodes the job from the decoded samples and writes the .json; the frame-size
# list is tried in order until the file is within LIMIT (now a single size per job).
def names(job):
    iso_path, src, ch, frames = job
    dst = OUT + '/' + iso_path.split('/')[-2] + '_' + iso_path.split('/')[-1]
    return dst, dst + '.json', dict(source=src, source_mtime=os.path.getmtime(src), frames=frames, channels=ch, encoder=ENC_ID)
def cached_info(job):
    dst, meta, key = names(job)
    if os.path.exists(dst) and os.path.exists(meta):
        m = json.load(open(meta))
        if m.get('key') == key: return m['info']
def one(job, pcm):
    iso_path, src, ch, frames = job; dst, meta, key = names(job)
    for fr in frames:
        n, size = ENC.encode(src, dst, ch, fr, pcm)
        if os.path.getsize(dst) <= LIMIT or fr == frames[-1]: break
    info = dict(file=dst, source=src, channels=ch, frame=fr, samples=n, bytes=os.path.getsize(dst))
    json.dump(dict(key=key, info=info), open(meta, 'w')); return iso_path, info
plan = {}; todo = []
for job in jobs:
    info = cached_info(job)
    if info: plan[job[0]] = info
    else: todo.append(job)
cached = len(plan)
# The clips still to encode are decoded in groups (xa.decode steps through all clips of a group side by side, which
# is what makes decoding in Python fast enough), then resampled and encoded, one encode per processor at a time.
# Decoding runs in this thread while the workers encode the groups before it; the longest clips go first, so the few
# slow encodes (the cutscene streams) overlap with the many short ones instead of trailing at the end. Threads, not
# processes: the encoding is done by the atracdenc program, and worker processes cannot be started from inside the
# packaged patcher on Windows and macOS.
GROUP = 24_000_000                                           # samples per group (xa.BATCH)
WORKERS = max(2, min(os.cpu_count() or 4, 16))
srcs = sorted({j[1] for j in todo}, key=os.path.getsize, reverse=True); groups = [[]]; size = 0
for src in srcs:
    n = os.path.getsize(src) // 2352 * 4032
    if groups[-1] and size + n > GROUP: groups.append([]); size = 0
    groups[-1].append(src); size += n
with ThreadPoolExecutor(WORKERS) as ex:
    pending = []
    for g in groups:
        if not g: continue
        dec = xa.decode(g)
        pending += [ex.submit(one, job, dec[job[1]]) for job in todo if job[1] in dec]
        del dec
        # at most two groups of decoded audio wait for an encoder (memory): let the older ones finish first
        while sum(not f.done() for f in pending) > 2 * max(len(g), WORKERS): wait(pending, return_when=FIRST_COMPLETED)
    for f in pending:
        iso_path, info = f.result(); plan[iso_path] = info
plan = {j[0]: plan[j[0]] for j in jobs}                      # in job order, as before
json.dump(dict(mode=MODE, files=plan), open(OUT + '/plan.json', 'w'), indent=1)
fr = {}
for i in plan.values(): fr[(i['channels'], i['frame'])] = fr.get((i['channels'], i['frame']), 0) + 1
print(f"audio {MODE}: {len(plan)} files ({cached} cached), {sum(i['bytes'] for i in plan.values()) / 1e6:.1f} MB; frames {fr}")
