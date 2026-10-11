"""Pass 2 for the cutscene streams: transcribe each PSP subtitle line's own slice of the English audio
(build/voice_en/windows.json, from make_windows.py) -> build/voice_en/window_transcripts.json
{line id: {"text", "no_speech", "logprob", "compression"}}. An analysis step, not run by build.py; the results go
into script/subtitles.csv through research/subtitle_map.py (docs/RESEARCH.md §11).
No glossary prompt: in pass 1 the prompt was echoed back as "Theodore Bruno, Digger, ..." on music-only stretches.
Short slices keep the recogniser on one line at a time. The three scores are kept so made-up text can be flagged:
the highest no-speech probability, the lowest average log-probability and the highest compression ratio over the
slice's segments.
Resumable. Run: ./research/transcribe_mac.sh --windows"""
import os, json, wave, time
import numpy as np, mlx_whisper
MODEL = 'mlx-community/whisper-large-v3-turbo'
root = os.path.join(os.path.dirname(__file__), '..', '..', 'build', 'voice_en')
W = json.load(open(os.path.join(root, 'windows.json')))
out = os.path.join(root, 'window_transcripts.json')
done = json.load(open(out)) if os.path.exists(out) else {}
cache = {}
# audio: the 16 kHz clip as floats; only the last clip is kept in memory (windows come grouped by clip)
def audio(clip):
    if clip not in cache:
        w = wave.open(os.path.join(root, 'wav16k', clip + '.wav'))
        cache.clear(); cache[clip] = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return cache[clip]
t0 = time.time(); n = 0
for w in W:
    if w['id'] in done: continue
    # the window in samples (16,000 per second)
    a = audio(w['clip'])[int(w['start'] * 16000):int(w['end'] * 16000)]
    r = mlx_whisper.transcribe(a, path_or_hf_repo=MODEL, language='en', condition_on_previous_text=False, temperature=0.0)
    seg = r['segments']
    done[w['id']] = dict(text=r['text'].strip(),
                         no_speech=round(max([g['no_speech_prob'] for g in seg] or [1]), 3),
                         logprob=round(min([g['avg_logprob'] for g in seg] or [0]), 3),
                         compression=round(max([g['compression_ratio'] for g in seg] or [0]), 2))
    n += 1; print(f"{w['id']}: {done[w['id']]['text']}", flush=True)
    if n % 20 == 0: json.dump(done, open(out, 'w'), indent=1, sort_keys=True, ensure_ascii=False)
json.dump(done, open(out, 'w'), indent=1, sort_keys=True, ensure_ascii=False)
print(f'{n} lines in {time.time() - t0:.0f} s; {len(done)} of {len(W)} in {out}')
