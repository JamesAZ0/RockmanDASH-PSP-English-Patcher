"""Pass 3 for the English subtitles: word-level timing of the English speech in every subtitle scene
-> build/voice_en/words.json {scene: {"clip", "regions": [[start, end]], "words": [{"w", "start", "end", "p"}]}}.
An analysis step, not run by build.py: research/subtitle_align.py turns the word times into the line timing of
script/subtitles_en.csv, which tools/build_subtitles.py builds into the game (docs/RESEARCH.md §11).
Speech regions = the scene's per-line windows (build/voice_en/windows.json) merged when less than 1.5 s apart, so music-
only stretches are skipped (pass 1 produced made-up text on those). News scenes C00-C04 use their whole English clip
(PS1 voice bank 11; matched to the scenes by content).
Times are seconds in the clip. The words give the English sentence timing; the wording itself is checked against the
PS1 script reference afterwards (research/subtitle_align.py). Resumable.
Run on the Mac: ./research/transcribe_mac.sh --words"""
import os, json, wave, time, collections
import numpy as np, mlx_whisper
MODEL = 'mlx-community/whisper-large-v3-turbo'
root = os.path.join(os.path.dirname(__file__), '..', '..', 'build', 'voice_en')
W = json.load(open(os.path.join(root, 'windows.json')))
# news subtitle scene -> the PS1 English clip of that report (bank 11, channel, clip in channel)
NEWS = {'C00': 'b11_c10_0', 'C01': 'b11_c04_0', 'C02': 'b11_c05_0', 'C03': 'b11_c07_0', 'C04': 'b11_c06_0'}
out = os.path.join(root, 'words.json')
done = json.load(open(out)) if os.path.exists(out) else {}
def audio(clip):
    w = wave.open(os.path.join(root, 'wav16k', clip + '.wav'))
    return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
scenes = collections.OrderedDict()
# window ids are '<scene>-<line>'; consecutive windows less than 1.5 s apart join into one region
for w in W:
    sc = w['id'].split('-')[0]; s = scenes.setdefault(sc, dict(clip=w['clip'], regions=[]))
    r = s['regions']
    if r and w['start'] - r[-1][1] < 1.5: r[-1][1] = max(r[-1][1], w['end'])
    else: r.append([w['start'], w['end']])
for sc, clip in NEWS.items():
    a = audio(clip); scenes[sc] = dict(clip=clip, regions=[[0, round(len(a) / 16000, 2)]])
t0 = time.time()
for sc, s in scenes.items():
    if sc in done: continue
    a = audio(s['clip']); words = []
    for st, en in s['regions']:
        r = mlx_whisper.transcribe(a[int(st * 16000):int(en * 16000)], path_or_hf_repo=MODEL, language='en',
                                   condition_on_previous_text=False, temperature=0.0, word_timestamps=True)
        for g in r['segments']:
            for x in g.get('words', []):
                # word times are relative to the region: add its start; p = the recogniser's probability for the word
                words.append(dict(w=x['word'].strip(), start=round(st + x['start'], 2), end=round(st + x['end'], 2), p=round(x.get('probability', 0), 2)))
    done[sc] = dict(clip=s['clip'], regions=s['regions'], words=words)
    print(sc, s['clip'], ' '.join(x['w'] for x in words)[:150], flush=True)
    json.dump(done, open(out, 'w'), indent=1, ensure_ascii=False)
print(f'{len(done)} scenes in {time.time() - t0:.0f} s -> {out}')
