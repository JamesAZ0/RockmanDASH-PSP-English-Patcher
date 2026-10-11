"""Build check (run by build.py after tools/build_text.py): every voice op in the built English dialogue names a clip
that exists.

Background (docs/RESEARCH.md §3, §10): the AUDIO op (PS1 code 0x8F) has four argument bytes: clip, 0, bank, 0. The
text box waits for the clip to finish, so an op naming a clip that does not exist leaves the box waiting forever (a
soft lock seen early in the project, when PS1 clip numbers were left in the PSP text). The PS1 and PSP number their
banks and clips differently, so build_text.py rewrites every op:
  - Japanese voices ('jp', --localization=text): the Japanese block's ops are placed in the English text; valid ids
    are the keys 'bank,clip' of build/voice_en/jp_clips.json (tools/voice/jp_clips.py: the clips on the PSP disc);
  - English voices ('en', --localization=audio or legends): PS1 English bank b is given the free PSP bank slot
    voice_banks.SLOTS[b], and the clip number is the clip's rank by first sector within its PS1 bank (confirmed
    2026-09-29 by matching transcripts of all 691 clips against the script); an op is valid when its bank is one of
    those slots and its clip number is below that bank's clip count (voice_banks.clips()).
(Making the voice language a build option: project decision 2026-09-29.)

Reads:  build/msg_psp/**/*.MSG, build/voice_en/jp_clips.json, build/voice_en/index.csv (through voice_banks.clips()).
Writes: nothing; prints the number of voice ops and up to 20 missing ones as (file, block, bank, clip).
Failure (exit 1, stops the build): any op without a clip.

Usage: python3 tools/checks/verify_voice.py [--audio=en|jp]
The --audio argument is internal: build.py passes en for --localization=audio and legends, jp for text."""
import sys, os, glob, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); import msgtool as M
AUDIO = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--audio=')), 'en')
JP = json.load(open('build/voice_en/jp_clips.json'))['clips']
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'voice')); import voice_banks as VB
# EN[b] = the clips of PS1 English bank b; SLOT = PSP bank slot -> PS1 English bank
EN = VB.clips(); SLOT = {s: b for b, s in enumerate(VB.SLOTS)}
bad = []; n = 0; files = 0
for f in sorted(p.replace('\\', '/') for p in glob.glob('build/msg_psp/**/*.[Mm][Ss][Gg]', recursive=True)):   # '/' on every platform
    files += 1
    for i, b in enumerate(M.blocks(open(f, 'rb').read())[0]):
        for x in M.parse(b, True, True)[0]:
            if x[0] == 'op' and x[1] == 0x8F:
                # x[2] = the op's argument bytes: clip, 0, bank, 0.  f[14:] below drops the leading 'build/msg_psp/'
                n += 1; c, bank = x[2][0], x[2][2]
                if AUDIO == 'jp' and '%d,%d' % (bank, c) not in JP: bad.append((f[14:], '%02X' % i, bank, c))
                if AUDIO == 'en' and not (bank in SLOT and c < len(EN[SLOT[bank]])): bad.append((f[14:], '%02X' % i, bank, c))
print(f'voice ops in {files} files: {n}; mode {AUDIO}; missing clips: {len(bad)}')
for x in bad[:20]: print('  MISSING', x)
sys.exit(1 if (bad and AUDIO in ('jp', 'en')) else 0)
