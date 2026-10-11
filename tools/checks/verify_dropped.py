"""Build check (run by build.py after jp_audio_audit.py, only when the build has English voices, i.e.
--localization=audio or legends): the Japanese voice clips that pack_inplace.py removed from the disc must be
unreachable in the English build, and must really be gone. (Dropping them: project decision, 2026-09-30.)

Background: the PSP game keeps every dialogue voice clip as its own ATRAC3plus file, DAT/at3/xa18mNN/*.at3 (NN = the
voice bank in hex; 846 files, about 54 MB). With English voices the dialogue plays the English clips in DAT/at3/xaen
instead, so the Japanese clip files are removed: their folders keep only the '.' and '..' records and their sectors are
reused by files that had to move. The cutscene streams (at3/xa37s00) are not dropped. See docs/RESEARCH.md §10, §15.

Reads:  build/test/<tag>/manifest.json   'dropped' = the files pack_inplace.py removed (path, size)
        logs/jp_audio_audit.json         written just before by tools/checks/jp_audio_audit.py from the same inputs:
                                         every Japanese audio file, what plays it, and its status in the English build
        build/test/<tag>/RockmanDASH_EN_<tag>.iso
Writes: nothing (prints one summary line).

Checks, each a failure (exit 1, which stops the build) when it does not hold:
  - something was dropped, and every dropped file is under at3/xa18m*;
  - the audit has no voice clip with status 'STILL PLAYED' (a clip the game code starts by itself and that was not
    given an English replacement), and no English dialogue block names a Japanese voice bank in its AUDIO op;
  - every xa18m* folder in the ISO is empty;
  - xa37s00 (the cutscene streams, replaced file by file, never dropped) holds the 71 files this check expects, and
    xaen holds the 691 English clips (the number of clips in the PS1 voice banks).
A failure means the English build could ask for a file that no longer exists (the text box would wait for a clip that
never plays) or that the packing step did not remove or add what the manifest says.

Usage: python3 tools/checks/verify_dropped.py <tag>"""
import sys, json, pycdlib
tag = sys.argv[1]; P = f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'
man = json.load(open(f'build/test/{tag}/manifest.json')); A = json.load(open('logs/jp_audio_audit.json'))
bad = []
drop = man.get('dropped', [])
if not drop: bad.append('nothing dropped')
if any('/at3/xa18m' not in d['path'] for d in drop): bad.append('dropped a file outside at3/xa18m*')
# 'STILL PLAYED ...' is the audit's status for a clip that game code starts and that has no English replacement
still = [r['path'] for r in A['rows'] if r['kind'] == 'voice' and r['status'].startswith('STILL')]
if still: bad.append(f'still played: {still}')
if A['english_ops_on_japanese_banks']: bad.append('English text names a Japanese bank')
iso = pycdlib.PyCdlib(); iso.open(P); at3 = '/PSP_GAME/USRDIR/DAT/at3'
# the children of an ISO directory without its own "." and ".." records
kids = lambda p: [c for c in iso.list_children(iso_path=p) if c.file_identifier() not in (b'.', b'..')]
for c in kids(at3):
    dn = c.file_identifier().decode(); n = len(kids(at3 + '/' + dn))
    if dn.startswith('xa18m') and n: bad.append(f'{dn} still has {n} files')
    # 71 = expected file count of the stream folder; 691 = English voice clips taken from the PS1 voice banks
    if dn == 'xa37s00' and n != 71: bad.append(f'xa37s00 has {n} files (71 expected)')
    if dn == 'xaen' and n != 691: bad.append(f'xaen has {n} files (691 expected)')
print(f'dropped {len(drop)} Japanese voice files ({sum(d["size"] for d in drop) / 1e6:.1f} MB); problems: {bad or 0}')
sys.exit(1 if bad else 0)
