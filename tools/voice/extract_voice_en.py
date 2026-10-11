"""Extract the PS1 English voice clips (read-only) -> build/voice_en/bNN_cCC_K.xa + build/voice_en/index.csv.
First step of the voice work; build.py runs it when the index is missing (the clip lengths are needed for every
build, the audio itself for --localization=audio|legends). Input: the US PS1 disc image (raw 2352-byte sectors).
Voice banks 0-35 = /CDDATA/XA/XA1806E..XA1880E in name order (mono 18.9 kHz XA-ADPCM, coding 0x04). Inside a bank,
each XA channel holds one or more clips, each ended by a sector with the EOF submode bit (0x80). The AUDIO op's clip
number = the clip's rank by first sector within the bank (checked: of the 646 PS1 AUDIO ops followed by text, 630
match a speech-recognition transcript of their clip; the rest are grunts, barks and the like).
XA37S00E/01E are the stereo 37.8 kHz cutscene streams (voice mixed with music; 8 channels): extracted with --streams
as s00_/s01_ clips, same layout, into index_streams.csv.
A clip file is the clip's raw sectors, in order; nothing is decoded here (tools/voice/xa.py decodes them when the
audio is built; `python3 tools/voice/xa.py clip.xa` writes a WAV for listening). A clip's length follows from its
sector count: every sector holds 4032 samples (2016 per channel in stereo).
Index columns: bank, file, channel, clip_in_channel, first_sector (within the file), sectors, seconds, path.
See docs/RESEARCH.md §10.
Usage: python3 tools/voice/extract_voice_en.py [first_bank last_bank] | --streams"""
import sys, os, csv, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); from rawiso import open_ps1; import inputs
OUT = 'build/voice_en'; os.makedirs(OUT, exist_ok=True)
iso = open_ps1(inputs.PS1); f = open(inputs.PS1, 'rb')
STREAMS = '--streams' in sys.argv
names = sorted(n for _, _, fs in iso.walk(iso_path='/CDDATA/XA') for n in fs if n.startswith('XA37S' if STREAMS else 'XA18'))
assert len(names) == (2 if STREAMS else 36), names
PFX = 's' if STREAMS else 'b'; IDX = OUT + ('/index_streams.csv' if STREAMS else '/index.csv')
lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 and not STREAMS else (0, len(names) - 1)
rows = []
for b in range(lo, hi + 1):
    r = iso.get_record(iso_path='/CDDATA/XA/' + names[b]); lba = r.extent_location(); n = r.data_length // 2048
    clips = collections.OrderedDict(); cur = {}
    # Raw sector: 12 sync + 4 header bytes, then the XA subheader: byte 17 = channel, byte 18 = submode (0x04 = audio
    # sector, 0x80 = end of file = last sector of a clip). clips: {(channel, clip number in the channel): sectors}
    for s in range(n):
        f.seek((lba + s) * 2352); sec = f.read(2352); sm = sec[18]
        if sm & 4:
            c = sec[17]; k = cur.get(c, 0); clips.setdefault((c, k), []).append((s, sec))
            if sm & 0x80: cur[c] = k + 1
    for (c, k), secs in sorted(clips.items()):
        out = '%s/%s%02d_c%02d_%d.xa' % (OUT, PFX, b, c, k)
        open(out, 'wb').write(b''.join(x[1] for x in secs))
        # coding byte (sector offset 19): bit 0 = stereo, bit 2 = 18.9 kHz instead of 37.8 kHz
        cod = secs[0][1][19]; rate = 18900 if cod & 4 else 37800; nch = 2 if cod & 1 else 1
        rows.append(dict(bank=b, file=names[b].split(';')[0], channel=c, clip_in_channel=k, first_sector=secs[0][0],
                         sectors=len(secs), seconds='%.6f' % (len(secs) * 4032 / (rate * nch)), path=out))
# merge into the existing index: rows of the banks just extracted replace the old ones
idx = IDX; old = [x for x in csv.DictReader(open(idx))] if os.path.exists(idx) else []
old = [x for x in old if not (lo <= int(x['bank']) <= hi)] + rows
old.sort(key=lambda x: (int(x['bank']), int(x['channel']), int(x['clip_in_channel'])))
with open(idx, 'w', newline='') as g:
    w = csv.DictWriter(g, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(old)
print(f'banks {lo}-{hi}: {len(rows)} clips, {sum(float(x["seconds"] or 0) for x in rows):.0f} s')
