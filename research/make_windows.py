"""Cut plan for transcribing the cutscene streams line by line -> build/voice_en/windows.json. An analysis step for
the subtitle work (not run by build.py); its output feeds transcribe_windows_mac.py and transcribe_words_mac.py.
Inputs: build/voice_en/index_streams.csv (extract_voice_en.py --streams), script/subtitles.csv (the Japanese
subtitle lines with their timing, research/subtitle_map.py), script/voice_rules.json.
PSP subtitle scene -> PS1 stream clip: set A slot n = XA37S00E clip rank n; set B slot n = XA37S01E clip rank n+2
(s01 ranks 0-1 are the opening narration and the theme; checked on A00/02/03/23/27/29/31/33 and B01-07/09/18/29-32).
Each PSP line's (start frame, frames) at 30 fps matches the English dub closely (A23: within ~0.5 s), so each line
gets its own window: start-0.4 s to end+0.8 s, cut back to 0.1 s before the next line starts.
See docs/RESEARCH.md §11.
Usage: python3 research/make_windows.py"""
import csv, json, collections
R = list(csv.DictReader(open('build/voice_en/index_streams.csv')))
# rank: {(stream file 0|1, clip rank by first sector): (extracted clip name, seconds)}
rank = {}
for b in (0, 1):
    rs = sorted([r for r in R if int(r['bank']) == b], key=lambda r: int(r['first_sector']))
    for i, r in enumerate(rs): rank[(b, i)] = ('s%02d_c%02d_%s' % (b, int(r['channel']), r['clip_in_channel']), float(r['seconds']))
OVER = json.load(open('script/voice_rules.json')).get('stream_overrides', {})   # e.g. A15 -> rank 18
# the timed lines of sets A and B (set C, the news, has whole-clip transcripts instead)
rows = [r for r in csv.DictReader(open('script/subtitles.csv', encoding='utf-8-sig')) if r['set'] in 'AB' and r['start_frame'] != '']
scenes = collections.defaultdict(list)
for r in rows: scenes[(r['set'], int(r['scene']))].append(r)
out = []
for (st, sc), ls in sorted(scenes.items()):
    key = (0, sc) if st == 'A' else (1, sc + 2)
    ov = OVER.get('%s%02d' % (st, sc))
    if ov: key = (key[0], ov['ps1_rank'])
    clip, dur = rank[key]
    ls.sort(key=lambda r: int(r['line']))
    for i, r in enumerate(ls):
        s = int(r['start_frame']) / 30; e = s + int(r['frames']) / 30
        # window: 0.4 s before the line to 0.8 s after it, not into the next line; at least 0.5 s, not past the clip end
        a = max(0, s - 0.4); b = e + 0.8
        if i + 1 < len(ls): b = min(b, int(ls[i + 1]['start_frame']) / 30 - 0.1)
        out.append(dict(id=r['id'], clip=clip, start=round(a, 2), end=round(min(max(b, a + 0.5), dur), 2)))
json.dump(out, open('build/voice_en/windows.json', 'w'), indent=1)
print(len(out), 'windows in', len(scenes), 'scenes')
