"""Build check (run by build.py): the English voice samples inside the game's sound banks.

Background (docs/RESEARCH.md §10): a few short voices are not .at3 files but SPU samples (VAG) inside VAB sound banks
stored as container entries: the title-screen voices (DEMO_DAT.BIN, e_title.vab) and two in-game banks (BS16VAB1.BIN
t_lb01b.vab, ST1A_02B.BIN t_lb02b.vab). The US PS1 disc has English versions of the same banks.
script/vab_voices.json lists, per bank, which sample numbers are voices; tools/voice/build_vab.py builds each new
entry: a listed sample is the PS1 English VAG verbatim together with the PS1 bank's tone record for it (the pitch and
volume it was made for - no resampling, no re-encoding), everything else stays the PSP's.

Reads:  the built ISO, the original PSP ISO and the PS1 disc image, script/vab_voices.json, build/vab_psp/.
Writes: nothing; one line per bank.
With English voices ('en'), per bank: the ISO entry equals the file build_vab.py wrote; the bank's SPU load address
        (header +0x14) is unchanged; every listed VAG is byte-identical to the PS1 English one and has Sony one-shot
        framing (build_vab.framing_ok); every other VAG is byte-identical to the PSP original; tone records are the
        PSP's except those of listed samples, which may be the PS1's; and the bank's end in SPU memory (address + sum
        of sample sizes) is no later than the PS1 English bank's, so it fits where the PS1 game fitted it.
With Japanese voices ('jp'): every bank entry must be byte-identical to the original.
Failure (exit 1, stops the build): the bank name with the list of problems, or 'CHANGED IN A JP BUILD'.

Usage: python3 tools/checks/verify_vab.py <tag> [--audio=en|jp]
The --audio argument is internal: build.py passes en for --localization=audio and legends, jp for text."""
import sys, os, io, json, struct, pycdlib
sys.path.insert(0, 'tools'); sys.path.insert(0, 'tools/voice')
import inputs as IN, build_vab as V
from rawiso import open_ps1
tag = sys.argv[1]; mode = next((a.split('=')[1] for a in sys.argv if a.startswith('--audio=')), 'en')
iso = pycdlib.PyCdlib(); iso.open(f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'); psp = pycdlib.PyCdlib(); psp.open(IN.PSP); ps1 = open_ps1(V.PS1)
# g(iso, path) = that file's bytes
g = lambda i, p: (lambda f: (i.get_file_from_iso_fp(f, iso_path=p), f.getvalue())[1])(io.BytesIO())
bad = 0
for r in json.load(open('script/vab_voices.json'))['banks']:
    # N = built BIN, B = original PSP BIN, A = PS1 English BIN; n / b / a = the bank entry parsed from each
    # (build_vab.parse)
    N = g(iso, f'/PSP_GAME/USRDIR/DAT/{r["bin"]}.BIN'); B = g(psp, f'/PSP_GAME/USRDIR/DAT/{r["bin"]}.BIN'); A = g(ps1, f'/CDDATA/DAT/{r["bin"]}.BIN;1')
    n = V.parse(N, V.entry(N, r['psp_entry'])); b = V.parse(B, V.entry(B, r['psp_entry'])); a = V.parse(A, V.entry(A, r['ps1_entry']))
    # the whole entry as stored: header + data, in 0x800-byte sectors
    ent = N[n['off']: n['off'] + n['secs'] * 0x800]
    if mode == 'jp':
        ok = ent == B[b['off']: b['off'] + b['secs'] * 0x800]; bad += not ok; print(r['bin'], 'unchanged (jp)' if ok else 'CHANGED IN A JP BUILD'); continue
    probs = []
    if ent != open('build/vab_psp/' + r['bin'] + '/' + r['psp_entry'][3:].replace('\\', '/'), 'rb').read(): probs.append('entry != build/vab_psp file')
    # entry header +0x14 = where the bank's samples are placed in SPU memory
    if n['hdr'][0x14:0x18] != b['hdr'][0x14:0x18]: probs.append('SPU address changed')
    # VAG numbers in the rules are 1-based
    for k in range(1, len(b['vags']) + 1):
        if k in r['vags']:
            if not V.framing_ok(n['vags'][k-1]): probs.append(f'VAG {k} framing')
            if n['vags'][k-1] != a['vags'][k-1]: probs.append(f'VAG {k} != PS1')
        elif n['vags'][k-1] != b['vags'][k-1]: probs.append(f'VAG {k} (untouched) != PSP')
    for k, lst in b['tones'].items():
        for (pos, t), (pos2, t2) in zip(lst, n['tones'][k]):
            if t2 != t and not (k in r['vags'] and t2 == dict(a['tones'][k])[pos]): probs.append(f'tone {hex(pos)} changed')
    spu = struct.unpack_from('<I', n['hdr'], 0x14)[0]
    if spu + sum(map(len, n['vags'])) > spu + sum(map(len, a['vags'])): probs.append('SPU end beyond the PS1 English bank')
    bad += bool(probs)
    print(r['bin'], f"{len(r['vags'])} VAGs, sectors {b['secs']} -> {n['secs']}, SPU end {hex(spu + sum(map(len, n['vags'])))}", 'OK' if not probs else probs)
print('problems:', bad); sys.exit(1 if bad else 0)
