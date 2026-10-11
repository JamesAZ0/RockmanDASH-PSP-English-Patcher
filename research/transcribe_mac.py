"""Transcribe the PS1 English voice clips on an Apple Silicon Mac (GPU, via mlx-whisper). An analysis step, not run by
build.py: the transcripts were used to confirm the clip numbering (extract_voice_en.py), to map the cutscene streams
to the PSP subtitle scenes, and as review material for the subtitles (docs/RESEARCH.md §10, §11).
Reads build/voice_en/wav16k/*.wav (16 kHz WAV copies of the extracted clips), writes build/voice_en/transcripts.json
({clip name: text}) and build/voice_en/segments.json ({clip name: [[start s, end s, text], ...]}, for
aligning the long cutscene streams). Resumable: clips already in the JSON are skipped. Optional arg: a name prefix,
e.g. b20 for one bank.
PROMPT is a glossary of the game's names for the recogniser. On music-only stretches of the streams it was echoed
back as text, which is why passes 2 and 3 (transcribe_windows_mac.py, transcribe_words_mac.py) use no prompt.
Run with research/transcribe_mac.sh (sets up the venv)."""
import sys, os, json, glob, wave, time
import numpy as np, mlx_whisper
MODEL = 'mlx-community/whisper-large-v3-turbo'
PROMPT = ("MegaMan, Roll, Barrell, Data, Tron, Teisel, Bon, Bonne, Servbots, Miss Tron, Master Teisel, Kattelox, "
          "Reaverbot, Refractor, Mother Lode, Juno, Eden, Carbons, Purifier, Trigger, Amelia, Flutter, Gesellschaft, "
          "Marlwolf, Draches, Feldynaught, Blumebear, Theodore Bruno, Digger, Sub-Gate, Main Gate.")
root = os.path.join(os.path.dirname(__file__), '..', '..', 'build', 'voice_en')
out = os.path.join(root, 'transcripts.json')
done = json.load(open(out)) if os.path.exists(out) else {}
segf = os.path.join(root, 'segments.json')
segs = json.load(open(segf)) if os.path.exists(segf) else {}
prefix = sys.argv[1] if len(sys.argv) > 1 else ''
files = sorted(glob.glob(os.path.join(root, 'wav16k', prefix + '*.wav')))
t0 = time.time(); n = 0
for p in files:
    name = os.path.basename(p)[:-4]
    if name in done: continue
    # 16-bit samples -> floats in -1..1; each clip is transcribed on its own (no carried-over context, temperature 0)
    w = wave.open(p); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    r = mlx_whisper.transcribe(a, path_or_hf_repo=MODEL, language='en', initial_prompt=PROMPT,
                               condition_on_previous_text=False, temperature=0.0)
    done[name] = r['text'].strip(); n += 1
    segs[name] = [[round(g['start'], 2), round(g['end'], 2), g['text'].strip()] for g in r['segments']]
    print(f'{name}: {done[name]}', flush=True)
    # save every 5 clips so an interrupted run can resume
    if n % 5 == 0: json.dump(done, open(out, 'w'), indent=1, sort_keys=True); json.dump(segs, open(segf, 'w'), indent=1, sort_keys=True)
json.dump(done, open(out, 'w'), indent=1, sort_keys=True); json.dump(segs, open(segf, 'w'), indent=1, sort_keys=True)
print(f'{n} clips transcribed in {time.time() - t0:.0f} s; {len(done)} of {len(files)} total in {out}')
