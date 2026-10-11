"""Research / review tool (not run by the build): a listening page for script/subtitles_en.csv (2026-09-30).

Writes build/analysis/subtitle_review/index.html with one audio snippet per subtitle line - the English dub, cut
from the extracted PS1 clip at the line's timing (0.3 s of margin on each side), in clips/ beside the page - next to
the proposed text wrapped as the game would show it, what the speech recogniser heard, the match score and the flags.
Flagged lines are listed first, then the reference lines that fall inside a scene but were not heard, then
everything. The page is local: open the HTML file in a browser.

It executes two parts of research/subtitle_align.py, read as text: the measuring helpers at its top and its
row-wrapping helper, so that the page wraps lines exactly as the proposal did.

Reads:  script/subtitles_en.csv, build/voice_en/words.json (which clip each scene is), build/voice_en/<clip>.xa,
        logs/subtitle_align_report.json. Needs ffmpeg. Snippets already made are not made again.
Changes are entered in the en_final / status / notes columns of the CSV, not on the page.

Usage: python3 research/subtitle_review_page.py"""
import sys, os, csv, json, html, subprocess
sys.argv = [sys.argv[0]]
# run subtitle_align.py's helpers here: everything before its reference-parsing part, and its row-wrapping function
src = open('research/subtitle_align.py').read(); exec(src.split('# --- reference utterances')[0]); exec(src[src.index('def wrap(s):'):src.index('old = {}')])
if not os.path.exists('build/voice_en/words.json'): raise SystemExit('build/voice_en/words.json is missing: make it with research/transcribe_words_mac.py (Apple Silicon, mlx-whisper) after a build has extracted the clips')
# The published script/subtitles_en.csv has no review columns (heard, score, flags, notes): they are shown empty unless
# subtitle_align.py has been rerun, which writes them again.
R = list(csv.DictReader(open('script/subtitles_en.csv', encoding='utf-8'))); W = json.load(open('build/voice_en/words.json'))
for _r in R:
    for _k in ('heard', 'score', 'flags', 'notes'): _r.setdefault(_k, '')
D = 'build/analysis/subtitle_review'; os.makedirs(D + '/clips', exist_ok=True)
for r in R:
    f = f"{D}/clips/{r['scene']}_{int(r['n']):03d}.mp3"
    if not os.path.exists(f):
        st = max(0, float(r['start_s']) - 0.3); du = float(r['end_s']) - st + 0.3
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'psxstr', '-i', f"build/voice_en/{W[r['scene']]['clip']}.xa", '-ss', str(st), '-t', str(du),
                        '-ac', '1', '-b:a', '96k', f], check=True)
# row: one table row; the reviewed text (en_final) replaces the proposal, a dropped line is shown as "(no subtitle)"
def row(r):
    t = r.get('en_final') or r['text']
    shown = '<i>(no subtitle)</i>' if r.get('status') == 'drop' else '<br>'.join(html.escape(x) for x in wrap(t))
    fl = html.escape(r['flags']) + ('<br><span class=note>' + html.escape(r.get('notes', '')) + '</span>' if r.get('notes') else '')
    cls = ' class="flag"' if r['flags'] else ''
    return (f"<tr{cls}><td>{r['scene']}-{int(r['n']):02d}<br><small>{float(r['start_s']):.1f}-{float(r['end_s']):.1f}s</small></td>"
            f"<td><audio controls preload=none src=\"clips/{r['scene']}_{int(r['n']):03d}.mp3\"></audio></td>"
            f"<td class=sub>{shown}</td><td class=heard>{html.escape(r['heard'])}</td><td>{r['score']}</td><td>{fl}</td></tr>")
flag = [r for r in R if r['flags']]
H = ['<!doctype html><meta charset=utf-8><title>Subtitle review</title><style>body{font:14px system-ui;margin:16px;background:#fff;color:#111}'
     'table{border-collapse:collapse;width:100%}td{border-top:1px solid #ddd;padding:4px 6px;vertical-align:top}'
     '.sub{font-weight:600;background:#111;color:#fff;font-family:monospace;white-space:nowrap}.heard{color:#555}.note{color:#06c}tr.flag td:last-child{color:#b00}'
     'audio{width:220px}@media(prefers-color-scheme:dark){body{background:#181818;color:#eee}.heard{color:#aaa}}</style>',
     f'<h1>English subtitles: review</h1><p>{len(R)} lines in {len({r["scene"] for r in R})} scenes. '
     f'{len(flag)} flagged (listed first). Proposed text = the PS1 script reference where it matches the dub; '
     'score = how closely the reference matched what was heard (1.0 = same words); blue notes = the choice made and why. Report any changes to the project, or fill en_final / status in script/subtitles_en.csv.</p>',
     '<h2>Flagged</h2><table>'] + [row(r) for r in flag] + ['</table><h2>Reference lines not found in the audio</h2><p>These script lines fall inside a scene but no heard words matched them, so they have no subtitle. Usually they are not in the dub (or were text boxes); if you hear one in a scene, report it to the project.</p><ul>'] + [f'<li><b>{k}</b>: ' + ' | '.join(html.escape(x) for x in v) + '</li>' for k, v in json.load(open('logs/subtitle_align_report.json'))['reference_lines_not_spoken'].items()] + ['</ul><h2>All lines</h2><table>'] + [row(r) for r in R] + ['</table>']
open(D + '/index.html', 'w', encoding='utf-8').write('\n'.join(H))
print(f'{D}/index.html: {len(R)} lines, {len(flag)} flagged')
