"""PS1 XA-ADPCM audio without external programs: decode, resample to 44.1 kHz, write WAV.

Used by extract_voice_en.py (clip files), build_audio.py and encode_at3.py (English audio). Replaces FFmpeg, which
the build used until 2026-10-05 for exactly these steps. Needs numpy.

A clip file (.xa, written by extract_voice_en.py) is the clip's raw 2352-byte CD sectors, in order. Sector layout:
12 sync bytes, 4 header bytes, the 8-byte XA subheader (two copies of file, channel, submode, coding), then 18 sound
groups of 128 bytes. Coding byte (sector offset 19): bits 0-1 = 1 for stereo, bits 2-3 = 1 for 18.9 kHz (0 = 37.8
kHz), bits 4-5 = 0 for 4-bit samples (the only kind on this disc).
A sound group holds 8 sound units of 28 samples. Its bytes 4..11 are the units' parameters (low 4 bits: range, high 4
bits: filter); the sample nibbles follow from byte 16: byte 16 + i + 4j carries sample j of unit 2i (low nibble) and
of unit 2i+1 (high nibble). Mono plays units 0..7 one after the other; stereo plays the even units on the left and
the odd units on the right.
A sample is  s = (nibble << (12 - range)) + ((K0 * s1 + K1 * s2 + 32) >> 6), limited to 16 bits, where s1 and s2 are
the two samples before it and (K0, K1) come from the filter number (FILTERS). This is whole-number arithmetic, and the
result is the same as FFmpeg's decoder sample for sample (checked on every clip of the disc, 2026-10-05).

Speed: each sample depends on the two before it, so a channel cannot be computed all at once. decode() cuts every
channel into pieces of CHUNK units and steps through all pieces of all clips side by side (one numpy operation per
step for thousands of pieces). A piece that is not the first of its channel starts from a guessed state (0, 0); a
second pass recomputes the start of each such piece from the true end of the piece before it, and stops at the first
two samples in a row that equal the first pass: from there on the first pass is exact, because the same two samples
and the same data give the same continuation.

Resampling 18.9 or 37.8 kHz to 44.1 kHz is a ratio of 7/3 or 7/6: a windowed-sinc low-pass (Kaiser window, TAPS input
samples wide) evaluated at the 7 output positions of each block of 3 or 6 input samples, as one matrix product.

Command line (for looking at clips with other programs):  python3 tools/voice/xa.py clip.xa [more.xa ...]
writes clip.wav next to each file, at the clip's own rate."""
import sys, os, struct
import numpy as np

SECTOR = 2352
FILTERS = np.array([[0, 0], [60, 0], [115, -52], [98, -55], [122, -60]], dtype=np.int32)   # (K0, K1) by filter number
CHUNK = 1152                    # units per piece (32,256 samples)
BATCH = 24_000_000              # samples decoded side by side (memory: about 6 bytes per sample)
TAPS = 32                       # low-pass width in input samples
CUTOFF, BETA = 0.96, 9.0        # pass band as a fraction of the input's half rate; Kaiser window shape


def read(path):
    """clip file -> (rate, channels, [per channel (filter numbers, shifts, nibbles)]): arrays of shape (units,),
    (units,) and (units, 28)"""
    d = np.frombuffer(open(path, 'rb').read(), dtype=np.uint8)
    assert len(d) and len(d) % SECTOR == 0, (path, 'not whole sectors')
    d = d.reshape(-1, SECTOR); coding = d[:, 19]
    assert (coding == coding[0]).all() and (coding[0] >> 4) & 3 == 0, (path, 'coding changes or is not 4-bit')
    stereo, rate = int(coding[0] & 3), (37800, 18900)[(coding[0] >> 2) & 3]
    assert stereo in (0, 1), path
    g = d[:, 24:24 + 18 * 128].reshape(-1, 128)                           # sound groups
    par = g[:, 4:12]                                                      # (groups, 8 units)
    flt, shift = (par >> 4).astype(np.int32), 12 - (par & 15).astype(np.int32)
    flt[flt > 4] = 0; shift[shift < 0] = 0                                # as FFmpeg treats out-of-range values
    b = g[:, 16:128].reshape(-1, 28, 4)                                   # byte 16 + i + 4j -> [group, j, i]
    nib = np.stack([b & 15, b >> 4], axis=-1).reshape(-1, 28, 8).astype(np.int8)   # [group, j, unit]
    nib = ((nib ^ 8) - 8).transpose(0, 2, 1)                              # signed, [group, unit, j]
    if stereo:
        return rate, 2, [(flt[:, c::2].reshape(-1), shift[:, c::2].reshape(-1), nib[:, c::2].reshape(-1, 28)) for c in (0, 1)]
    return rate, 1, [(flt.reshape(-1), shift.reshape(-1), nib.reshape(-1, 28))]


def _decode_channels(chans):
    """[(filters, shifts, nibbles)] -> [int16 samples], all channels stepped side by side (see the module text)"""
    # pieces: one row per CHUNK units of a channel; row lists per channel, in order
    rows, n = [], 0
    for f, s, t in chans:
        k = -(-len(f) // CHUNK); rows.append(np.arange(n, n + k)); n += k
    F = np.zeros((n, CHUNK), np.int32); S = np.zeros((n, CHUNK), np.int32); T = np.zeros((n, CHUNK, 28), np.int8)
    for (f, s, t), r in zip(chans, rows):
        u = len(f); pad = len(r) * CHUNK - u
        F[r] = np.pad(f, (0, pad)).reshape(-1, CHUNK); S[r] = np.pad(s, (0, pad)).reshape(-1, CHUNK)
        T[r] = np.pad(t, ((0, pad), (0, 0))).reshape(-1, CHUNK, 28)
    out = np.empty((n, CHUNK * 28), np.int16)
    K0, K1 = FILTERS[F, 0], FILTERS[F, 1]

    def run(sel, s1, s2, first_pass):
        """decode rows sel from the state (s1, s2). First pass: all samples. Second pass: until every row has
        produced two samples in a row equal to the first pass (rows drop out as they do)."""
        same = np.zeros(len(sel), np.int8)
        for u in range(CHUNK):
            k0, k1 = K0[sel, u], K1[sel, u]
            tt = T[sel, u].astype(np.int32) << S[sel, u][:, None]
            for j in range(28):
                p = (s1 * k0 + s2 * k1 + 32 >> 6) + tt[:, j]
                np.clip(p, -32768, 32767, out=p)
                col = u * 28 + j
                if first_pass:
                    out[sel, col] = p
                else:
                    eq = out[sel, col] == p
                    out[sel, col] = p
                    same = np.where(eq, same + 1, 0).astype(np.int8)
                    keep = same < 2
                    if not keep.all():
                        if not keep.any(): return
                        sel, p, s1, same, tt, k0, k1 = sel[keep], p[keep], s1[keep], same[keep], tt[keep], k0[keep], k1[keep]
                s2, s1 = s1, p

    z = np.zeros(n, np.int32)
    run(np.arange(n), z, z.copy(), True)
    for c in range(1, max(len(r) for r in rows)):                 # piece number c of every channel that has one
        sel = np.array([r[c] for r in rows if len(r) > c]); prev = sel - 1
        run(sel, out[prev, -1].astype(np.int32), out[prev, -2].astype(np.int32), False)
    return [out[r].reshape(-1)[:len(f) * 28].copy() for (f, s, t), r in zip(chans, rows)]


def decode(paths):
    """clip files -> {path: (rate, int16 array of shape (samples, channels))}; decoded in batches of BATCH samples"""
    res, batch, size = {}, [], 0
    def flush():
        nonlocal batch, size
        if not batch: return
        chans = [c for _, _, _, cs in batch for c in cs]
        dec = _decode_channels(chans); k = 0
        for path, rate, nch, cs in batch:
            res[path] = (rate, np.stack(dec[k:k + nch], axis=1)); k += nch
        batch, size = [], 0
    for p in paths:
        rate, nch, cs = read(p); n = sum(len(c[0]) for c in cs) * 28
        if batch and size + n > BATCH: flush()
        batch.append((p, rate, nch, cs)); size += n
    flush()
    return res


_H = {}
def _kernel(rate):
    """-> (M, lo, matrix): for each block of M input samples the 7 outputs are matrix @ x[block start + lo : ...]"""
    if rate in _H: return _H[rate]
    L = 7; M = {18900: 3, 37800: 6}[rate]
    N = L * TAPS + 1; c = (N - 1) // 2; i = np.arange(N)
    h = np.sinc(CUTOFF * (i - c) / L) * np.kaiser(N, BETA)
    h *= L / h.sum()                                             # unity gain for each of the 7 output positions
    # output r of a block sits at up-sampled position r*M; tap i reaches input sample (r*M - i + c) / L when whole
    ent = [(r, (r * M - k + c) // L, h[k]) for r in range(L) for k in range(N) if (r * M - k + c) % L == 0]
    lo = min(e[1] for e in ent); hi = max(e[1] for e in ent)
    H = np.zeros((L, hi - lo + 1), np.float32)
    for r, nrel, v in ent: H[r, nrel - lo] += v
    _H[rate] = (M, lo, H); return _H[rate]


def resample(x, rate):
    """int16 (samples, channels) at 18,900 or 37,800 Hz -> int16 at 44,100 Hz (7/3 or 7/6 times as many samples)"""
    if rate == 44100: return x
    M, lo, H = _kernel(rate); n, nch = x.shape; W = H.shape[1]
    assert n % M == 0, (n, M)
    out = np.empty((n // M * 7, nch), np.int16); STEP = 1 << 15                    # blocks per matrix product
    for ch in range(nch):
        xp = np.concatenate([np.zeros(-lo, np.float32), x[:, ch].astype(np.float32), np.zeros(W + lo + M, np.float32)])
        win = np.lib.stride_tricks.sliding_window_view(xp, W)[::M][:n // M]          # one row per block
        for a in range(0, len(win), STEP):
            y = win[a:a + STEP] @ H.T
            out[a * 7:(a + len(y)) * 7, ch] = np.clip(np.rint(y), -32768, 32767).reshape(-1)
    return out


def wav_bytes(x, rate):
    """int16 (samples, channels) -> the bytes of a 16-bit PCM WAV file"""
    data = np.ascontiguousarray(x, dtype='<i2').tobytes(); nch = x.shape[1]
    return (b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, nch, rate, rate * nch * 2, nch * 2, 16)
            + b'data' + struct.pack('<I', len(data)) + data)


if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__)
    for p, (rate, x) in decode(sys.argv[1:]).items():
        open(os.path.splitext(p)[0] + '.wav', 'wb').write(wav_bytes(x, rate)); print(p, rate, x.shape)
