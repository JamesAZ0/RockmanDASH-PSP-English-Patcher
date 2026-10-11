"""Encode audio to a PSP ATRAC3plus .at3 laid out like the game's own files. Used by build_audio.py (English audio:
--localization=audio|legends).
atracdenc (github.com/dcherednik/atracdenc; source with the project's changes in src/atracdenc, located by
tools/exttools.py: ATRACDENC=, bin/<platform>/, PATH) writes the raw frames; the RIFF header is
written here from the Japanese files' template: fmt = WAVE_FORMAT_EXTENSIBLE (52 bytes: bits 0, cbSize 34, 2048
samples/block, channel mask 1 or 3, ATRAC3plus GUID, version 1, 2-byte codec config, 8 zero bytes), fact = (samples,
sample offset), data. The frame size is set through the project's change to atracdenc (environment variable
AT3P_FRAME; the same change as a patch: src/atracdenc/at3p_frame.patch). Unchanged, atracdenc always writes 2048-byte
frames. Japanese: 744-byte frames (voice mono ~64 kb/s, streams stereo ~128 kb/s).
atracdenc's output starts 4464 samples late (measured). The PSP skips fact offset + 368 (0x170) samples and needs
offset + end sample + 368 <= frames * 2048 (every Japanese ATRAC3plus file has offset 2048 and >= 396 samples to
spare). The first test broke this: it wrote fact = (n, 4096) with too few frames because atracdenc drops the delayed
tail, so the game never started the clip and the text box hung (seen in game; the cause was found by comparing the
fact chunks of all Japanese files). Now: offset 2048 like every Japanese file, end sample n + 2048 (the whole clip
plays, after 46 ms of extra lead-in), and the input is padded with silence so enough frames are written.
See docs/RESEARCH.md §10.
The input is a PS1 clip file (.xa; decoded and brought to 44.1 kHz by tools/voice/xa.py) or samples handed over by
build_audio.py. No other program than atracdenc is used.
Usage: python3 tools/voice/encode_at3.py clip.xa out.at3 [mono|stereo]"""
import sys, os, struct, subprocess, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')); import exttools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import xa
# tools/exttools.py: ATRACDENC=, then bin/<platform>/, then the PATH
ENC = exttools.find('atracdenc') or 'atracdenc'
# GUID: the ATRAC3plus subformat id of the fmt chunk, as in the Japanese files
GUID = bytes.fromhex('bfaa23e958cb7144a119fffa01e4ce62')
# FRAME: frame size in bytes (build_audio.py sets it per file); OFFSET: fact sample offset; DELAY: atracdenc's
# encoder delay in samples; SKIP: the samples the PSP skips on top of the offset
FRAME = 744; OFFSET = 2048; DELAY = 4464; SKIP = 0x170
# encode -> (fact end sample, data bytes). Steps: 44.1 kHz 16-bit samples (pcm = (rate, int16 array) as xa.decode
# returns it, else decoded from the clip file src), padded with silence, atracdenc to raw frames, the RIFF file
def encode(src, dst, ch, frame=None, pcm=None):
    FRAME = frame or globals()['FRAME']               # per call, so several encodes can run at once (threads)
    nch = 1 if ch == 'mono' else 2
    with tempfile.TemporaryDirectory() as t:
        wav, raw = os.path.join(t, 'in.wav'), os.path.join(t, 'out.raw')
        rate, x = pcm if pcm is not None else xa.decode([src])[src]
        assert x.shape[1] == nch, (src, 'channels', x.shape[1], nch)
        x = xa.resample(x, rate)
        n = len(x)                                            # samples in the source at 44.1 kHz
        end = n + (DELAY - OFFSET - SKIP)                     # fact end sample: covers the delayed audio
        frames = -(-(end + OFFSET + SKIP + 400) // 2048) + 1  # >= 400 spare samples, like the Japanese files
        pad = frames * 2048 - n
        open(wav, 'wb').write(xa.wav_bytes(np.concatenate([x, np.zeros((pad, nch), np.int16)]), 44100))
        # raw container: frames only, no header; AT3P_FRAME selects the frame size
        # CREATE_NO_WINDOW (Windows only; 0 = no flag elsewhere): started from the windowed patcher, each atracdenc
        # would otherwise open a console window of its own
        subprocess.run([ENC, '-e', 'atrac3plus', '--container', 'raw', '-i', wav, '-o', raw], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, AT3P_FRAME=str(FRAME)),
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        data = open(raw, 'rb').read()
    assert len(data) % FRAME == 0, len(data)
    assert (len(data) // FRAME) * 2048 >= end + OFFSET + SKIP + 368, ('too few frames', len(data) // FRAME, end)
    # codec config: 0x20 | channels << 2 | high bits of (frame / 8 - 1), then its low byte: 0x24 (mono) / 0x28 (stereo),
    # 0x5C for 744-byte frames, as the Japanese files have
    cfg = bytes([0x20 | (nch << 2) | ((FRAME // 8 - 1) >> 8), (FRAME // 8 - 1) & 0xFF])
    # fmt chunk: tag 0xFFFE (extensible), channels, 44100 Hz, bytes per second, block size = frame, bits 0, cbSize 34,
    # 2048 samples per block, channel mask; then the GUID, version 1, the 2 config bytes and 8 zero bytes
    fmt = struct.pack('<HHIIHHHHI', 0xFFFE, nch, 44100, FRAME * 44100 // 2048, FRAME, 0, 34, 2048, 1 if nch == 1 else 3) \
          + GUID + struct.pack("<H", 1) + cfg + bytes(8)
    assert len(fmt) == 52
    body = b'WAVE' + b'fmt ' + struct.pack('<I', 52) + fmt + b'fact' + struct.pack('<III', 8, end, OFFSET) + b'data' + struct.pack('<I', len(data)) + data
    open(dst, 'wb').write(b'RIFF' + struct.pack('<I', len(body)) + body)
    return end, len(data)
if __name__ == '__main__':
    print(encode(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'mono'))
