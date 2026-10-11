"""Research tool (not run by the build): quality check of the encoded English audio. Made 2026-09-30 after a few odd
noises were heard on real hardware, to find out whether the ATRAC3plus encoder adds pops, clicks or clipping. It
checks every encoded file, not a sample.

For every file in build/audio_psp/plan.json (written by tools/voice/build_audio.py: the .at3 files the build puts on
the disc, each with the source it was encoded from) the .at3 is decoded with ffmpeg and cut the way the PSP plays it,
then compared sample by sample with its 44.1 kHz source.

How the PSP plays an .at3 (docs/RESEARCH.md §10): the file's 'fact' chunk holds the end sample and an offset; playback
skips offset + 368 samples and stops at the end sample. The encoder used (atracdenc) delays its output by 4464
samples, so whatever part of that delay the skip does not cover is silence before the sound starts ('lead' below).

Reported per file (build/analysis/audio_check.json, keyed by the disc path):
  snr                     signal-to-noise ratio of encoded vs source, dB (first channel)
  clip_src / clip_enc     samples at full scale in the source and in the encoded result
  burst_db / burst_at     the loudest 5 ms window of the error, in dB above the file's median error window, and its
                          time in seconds: a pop or click the encoder added shows up here
  worst_err_vs_signal(_at) the window where the error is largest relative to the signal in that window
  start / end, src_start / src_end   level of the first and last played sample (a non-zero value = a click at the cut)
  dc                      mean of the played samples (DC offset)
  lead_silence_max        largest sample in the lead-in that should be silent
The run is resumable: files already in the JSON are skipped, and it stops after max_seconds (default 150) so it can
be called repeatedly.

Reads: build/audio_psp/plan.json and the files it names. Needs ffmpeg and numpy.
Usage: python3 research/audio_check.py [max_seconds]"""
import sys, os, json, struct, subprocess, time
import numpy as np
OUT = 'build/analysis/audio_check.json'
plan = json.load(open('build/audio_psp/plan.json'))['files']
res = json.load(open(OUT)) if os.path.exists(OUT) else {}
T0 = time.time(); LIMIT = float(sys.argv[1]) if len(sys.argv) > 1 else 150
# pcm: decode with ffmpeg to 16-bit samples, returned as a float array of shape (samples, channels)
def pcm(args, ch):
    x = subprocess.run(['ffmpeg', '-v', 'quiet'] + args + ['-f', 's16le', '-ac', str(ch), '-'], capture_output=True).stdout
    return np.frombuffer(x, np.int16).astype(np.float64).reshape(-1, ch)
for q, info in sorted(plan.items()):
    if q in res: continue
    if time.time() - T0 > LIMIT: break
    f = info['file']; ch = 2 if info['channels'] == 'stereo' else 1
    # RIFF 'fact' chunk: after the 4-byte id and 4-byte size come u32 end sample and u32 offset
    d = open(f, 'rb').read(); fi = d.find(b'fact'); end, off = struct.unpack_from('<II', d, fi + 8)
    dec = pcm(['-i', f], ch)                 # ffmpeg decodes from the first frame, no skipping
    play = dec[off + 368: off + 368 + end]   # what the PSP plays
    src = pcm(['-i', info['source'], '-ar', '44100'], ch)
    lead = 4464 - (off + 368)                # encoder delay not covered by the skip -> silence before the voice
    # a = source, b = played result shifted by the lead-in (first channel of each), cut to the same length
    a = src[:, 0]; b = play[lead: lead + len(a), 0]; n = min(len(a), len(b)); a, b = a[:n], b[:n]
    # e = error signal. Windows of 220 samples = 5 ms at 44.1 kHz: ew = error RMS per window, sw = signal RMS per
    # window
    e = b - a; w = 220; m = n // w
    ew = np.sqrt((e[:m * w].reshape(m, w) ** 2).mean(1) + 1e-9); sw = np.sqrt((a[:m * w].reshape(m, w) ** 2).mean(1) + 1e-9)
    # k = the window with the largest error relative to its signal (+50 so that near-silent windows do not dominate)
    med = float(np.median(ew)) + 1e-9; k = int(np.argmax(ew / (sw + 50)))
    res[q] = dict(file=os.path.basename(f), seconds=round(n / 44100, 2),
                  snr=round(float(10 * np.log10((a ** 2).sum() / ((e ** 2).sum() + 1e-9))), 1),
                  clip_src=int((np.abs(src) >= 32767).sum()), clip_enc=int((np.abs(play) >= 32767).sum()),
                  burst_db=round(float(20 * np.log10(ew.max() / med)), 1), burst_at=round(int(np.argmax(ew)) * w / 44100, 2),
                  worst_err_vs_signal_at=round(k * w / 44100, 2), worst_err_vs_signal=round(float(ew[k] / (sw[k] + 50)), 2),
                  start=int(abs(play[lead, 0])) if len(play) > lead else 0, end=int(abs(play[min(len(play) - 1, lead + n - 1), 0])),
                  src_start=int(abs(src[0, 0])), src_end=int(abs(src[-1, 0])), dc=round(float(play[:, 0].mean()), 1),
                  lead_silence_max=int(np.abs(play[:lead]).max()) if lead > 0 else 0)
json.dump(res, open(OUT, 'w'), indent=0)
print(f'{len(res)}/{len(plan)} files checked')
