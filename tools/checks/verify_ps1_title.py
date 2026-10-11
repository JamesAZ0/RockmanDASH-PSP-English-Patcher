"""Build check (run by build.py): the options that change the title screen, the PSP menu / save picture and the dog
scene are in the ISO exactly as the manifest says they were built - and absent when they were not chosen.

How the user-facing options map (build.py sets the internal values recorded in manifest.json 'options' and in the
report files copied to build/test/<tag>/):
  --localization=legends      -> title 'ps1' and menu 'localized'; text / audio -> title 'psp', menu 'original'
  --paprika=good-dog          -> dog 'ps1' (the US behaviour); fair-game -> 'jp' (the Japanese behaviour)
(PS1 title and save image: project decision 2026-10-01; dog option: project decision 2026-10-01.)

Reads:  build/test/<tag>/: the ISO, manifest.json, EBOOT_plain.BIN (the built program as a plain ELF) and the reports
        ps1_title.json (tools/patch_ps1_title.py), psp_menu.json (tools/patch_psp_menu.py), ps1_dog.json
        (tools/patch_ps1_dog.py); build/diag/BOOT_sony_plain.BIN (the original program); build/ps1_title/,
        build/tex_psp/, build/pict/ (what the build steps produced); both original disc images. Writes nothing.
Both programs are loaded like the PSP loader does (the loader part of compare_loaded.py), so 'EBOOT word' below means
a word of the relocated memory image, indexed by vaddr.

title ps1 (docs/RESEARCH.md §8):
  - DEMO_DAT.BIN logo entry NTITLE.TIM = the PS1 NTITLEU.TIM's first 0xA000 stored bytes (rows 0-159, the only rows
    either game draws) and its CLUT; the first 0x100 header bytes stay the PSP's;
  - menu-word entry NTITLE2.TIM: header = build/ps1_title's (9 palettes instead of 8; palette 8 is the PSP's old
    palette 0, kept for PRESS START / copyright), pixels = tools/build_title.py's;
  - the PS1 background NTITLE3U.TIM entry, byte for byte, directly after it, followed by the original next entry;
  - every word and the background primitive templates listed in ps1_title.json are in the loaded program, and the
    original program has the recorded old values;
  - the new background code reaches its data PC-relative (no relocations). After its 'bal', ra = 0x2378; each
    address is built as ra + (imm16 << 16) + imm16 from two instructions. They must resolve to the templates, to
    AddPrim (0x21647C; the original instruction at 0x2368 must be a jal) and to the ordering-table pointer that the
    original code reads through the relocated lui/lw at 0x2474 / 0x2484. This last test exists because an early
    version of the patch used the unrelocated address; the check caught it.
title psp: those DEMO_DAT entries are the original's (the menu-word pixels are English in every build), there is no
  NTITLE3U, and the program words at 0x19A4 / 0x19AC (the branches that skip the Japanese title calls), 0x253C / 0x25F8
  (palette of PRESS START / copyright) and 0x2370-0x248C (the background code) are the original's.
menu localized (docs/RESEARCH.md §14): DAT/PICT/savepic.png and PSP_GAME/ICON0.PNG = build/pict/savepic.png, a 144x80
  8-bit RGB PNG of at most 30,000 bytes (the size of the game's load buffer); PSP_GAME/ICON1.PMF removed; the three
  program words that make the save-load setup use the spare icon buffer are set. original: those files and words as on
  the original disc. (The menu name is checked by verify_sfo.py, the save name by verify_savetext.py.)
dog ps1 (docs/RESEARCH.md §12): the words of ps1_dog.json are in the program (the kick is removed and the wait after
  the talk scene is the US value); jp: the five words are the original's (talk or kick).
Always: ST05.BIN's PS1 stage program R3_ST05.BIN is unchanged. The PSP does not run it - it runs a native port of
  the stage code inside the EBOOT - and an earlier attempt that patched it had no effect, so it must stay original.

Failure (exit 1, stops the build): the list of checks that did not hold is printed.

Usage: python3 tools/checks/verify_ps1_title.py <tag>"""
import sys, os, io, json, struct, pycdlib
sys.path.insert(0, 'tools'); from rawiso import open_ps1; import inputs as IN
# take compare_loaded.py's loader (everything before its command-line part) and run it here: defines BASE and load()
src = open(os.path.join(os.path.dirname(__file__), 'compare_loaded.py')).read().split('a, na, pa = load')[0]
tag = sys.argv[1]; sys.argv = [sys.argv[0]]; exec(src)
man = json.load(open(f'build/test/{tag}/manifest.json')); opt = man.get('options', {'title': 'psp', 'save': 'psp'})
def get(iso, p):
    b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=p); return b.getvalue()
new = pycdlib.PyCdlib(); new.open(f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'); org = pycdlib.PyCdlib(); org.open(IN.PSP)
# N = built PSP DEMO_DAT.BIN, O = original PSP, S = PS1 (USA) DEMO_DAT.BIN
N, O = get(new, '/PSP_GAME/USRDIR/DAT/DEMO_DAT.BIN'), get(org, '/PSP_GAME/USRDIR/DAT/DEMO_DAT.BIN')
S = get(open_ps1(IN.PS1), '/CDDATA/DAT/DEMO_DAT.BIN;1')
# ents: (offset, name) of every container entry; ent: (offset, header + data up to the next entry, next entry name)
def ents(d): return [(o, d[o+0x40:o+0x80].split(b'\0')[0].decode()) for o in range(0, len(d) - 0x7FF, 0x800) if d[o+0x40:o+0x43] == b'..\\']
def ent(d, name):
    E = ents(d); k = [i for i, (_, n) in enumerate(E) if n == name]
    if not k: return None
    o = E[k[0]][0]; end = E[k[0] + 1][0] if k[0] + 1 < len(E) else len(d); return o, d[o:end], (E[k[0] + 1][1] if k[0] + 1 < len(E) else None)
bad = []; ok = 0
def check(c, what):
    global ok
    if c: ok += 1
    else: bad.append(what)
T, T2, T3 = '..\\BG\\CHAR\\NTITLE.TIM', '..\\BG\\CHAR\\NTITLE2.TIM', '..\\BG\\CHAR\\NTITLE3U.TIM'
# B = built program as loaded, A = the original program as loaded (both indexed by vaddr)
B, _, _ = load(f'build/test/{tag}/EBOOT_plain.BIN'); A, _, _ = load('build/diag/BOOT_sony_plain.BIN')
pt = json.load(open(f'build/test/{tag}/ps1_title.json'))   # copied there by build.py (patch_ps1_title.py's report)
if opt['title'] == 'ps1':
    _, n1, _ = ent(N, T); _, s1, _ = ent(S, '..\\BG\\CHAR\\NTITLEU.TIM'); _, o1, _ = ent(O, T)
    # 0x800 = header size; 0xA000 stored bytes = rows 0-159 of the logo; 0x100-0x7FF = the palette area of the header
    check(n1[0x800:0x800 + 0xA000] == s1[0x800:0x800 + 0xA000], 'logo pixels = PS1 NTITLEU rows 0-159')
    check(n1[0x100:0x800] == s1[0x100:0x800] and n1[:0x100] == o1[:0x100], 'logo CLUT = PS1, header fields = PSP')
    _, n2, nxt = ent(N, T2); head = open('build/ps1_title/DEMO_DAT/BG/CHAR/NTITLE2.TIM.head', 'rb').read()
    # header +0x18 = number of palettes; 0x2000 = the menu-word pixel bytes written by build_title.py
    check(n2[:0x800] == head and struct.unpack_from('<I', n2, 0x18)[0] == 9, 'menu-word header: 9 palettes (build_ps1_title.py)')
    check(n2[0x800:0x800 + 0x2000] == open('build/tex_psp/DEMO_DAT/BG/CHAR/NTITLE2.TIM.pix', 'rb').read(), 'menu-word pixels = build_title.py')
    check(nxt == T3, 'NTITLE3U directly after the menu words')
    _, n3, after3 = ent(N, T3); _, s3, _ = ent(S, T3)
    check(n3 == s3 and after3 == '..\\sound\\moto\\se\\vab\\common.vab', 'NTITLE3U = the PS1 entry byte for byte, then common.vab')
    check(pt['mode'] == 'ps1', 'EBOOT built with the PS1 title (build/eboot/ps1_title.json)')
    for va, (old, nw) in pt.get('words', {}).items():
        check(struct.unpack_from('<I', B, int(va, 16))[0] == int(nw, 16) and struct.unpack_from('<I', A, int(va, 16))[0] == int(old, 16), f'EBOOT word {va}')
    check(bytes(B[pt['data_va']:pt['data_va'] + pt['data_len']]).hex() == pt['data'], 'background templates in the loaded EBOOT')
    # the PC-relative addresses the new code builds (ra = 0x2378 after the bal) must be: the templates, AddPrim, and the
    # ordering-table pointer the original (relocated) code reads at 0x2474/0x2484
    # rel_(k): the two signed 16-bit immediates at k and k+4, combined as hi << 16 plus lo, added to ra
    # ot_orig: the original lui (0x2474) / lw offset (0x2484) as relocated in memory, minus the load base = a vaddr
    rel_ = lambda k: 0x2378 + (struct.unpack_from('<h', B, k)[0] << 16) + struct.unpack_from('<h', B, k + 4)[0]
    ot_orig = ((struct.unpack_from('<I', A, 0x2474)[0] & 0xFFFF) << 16) + struct.unpack_from('<h', A, 0x2484)[0] - BASE
    check(rel_(0x2378) == pt['data_va'], 'code -> templates address')
    # 0x21647C = the native AddPrim; opcode 3 at 0x2368 = the original code called something there with jal
    check(rel_(0x2384) == 0x21647C and struct.unpack_from('<I', A, 0x2368)[0] >> 26 == 3, 'code -> AddPrim address')
    check(rel_(0x2390) == ot_orig, f'code -> ordering-table pointer {ot_orig:#x} (as the original code)')
else:
    check(ent(N, T)[1] == ent(O, T)[1], 'logo entry unchanged')
    check(ent(N, T2)[1][:0x800] == ent(O, T2)[1][:0x800], 'menu-word header unchanged (8 PSP palettes; the words are from build_title.py)')
    check(ent(N, T3) is None, 'no NTITLE3U')
    # title-call branches, PRESS START / copyright palette, and the whole original background code block
    for va in (0x19A4, 0x19AC, 0x253C, 0x25F8) + tuple(range(0x2370, 0x2490, 4)):
        check(B[va:va+4] == A[va:va+4], f'EBOOT word {va:#x} original')
menu = opt.get('menu', 'original')
for q in ('/PSP_GAME/USRDIR/DAT/PICT/savepic.png', '/PSP_GAME/ICON0.PNG'):
    png = get(new, q)
    if menu == 'localized':
        check(png == open('build/pict/savepic.png', 'rb').read() and len(png) <= 30000, f'{q} = build/pict/savepic.png, <= 30,000 bytes')
        # PNG signature; IHDR width/height at 16..23; bit depth 8 and colour type 2 (RGB) at 24..25
        check(png[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', png[16:24]) == (144, 80) and png[24:26] == b'\x08\x02', f'{q} 144x80 8-bit RGB')
    else:
        check(png == get(org, q), f'{q} original')
icon1 = [c.file_identifier() for c in new.list_children(iso_path='/PSP_GAME')]
check((b'ICON1.PMF;1' in icon1 or b'ICON1.PMF' in icon1) == (menu == 'original'), 'ICON1.PMF ' + ('removed' if menu == 'localized' else 'kept'))
pm = json.load(open(f'build/test/{tag}/psp_menu.json'))               # patch_psp_menu.py's report, copied by build.py
check(pm['mode'] == menu, 'EBOOT save-icon buffer patch matches the menu option')
# save-load setup: (vaddr, original word, localized word). Two stores become nops and one store is redirected, so the
# chosen save's ICON0 is loaded into the spare 30,000-byte buffer instead of over the game's own save picture
for va, old_, new_ in ((0x4F464, 0xAE420584, 0), (0x4F47C, 0xAE430594, 0xAE430584), (0x4F480, 0xAE450598, 0)):
    want = new_ if menu == 'localized' else old_
    check(struct.unpack_from('<I', B, va)[0] == want and struct.unpack_from('<I', A, va)[0] == old_, f'save icon load buffer word {va:#x}')
S5n, S5o = get(new, '/PSP_GAME/USRDIR/DAT/ST05.BIN'), get(org, '/PSP_GAME/USRDIR/DAT/ST05.BIN')
_, pn, _ = ent(S5n, '..\\PROGBIN\\R3_ST05.BIN'); _, po, _ = ent(S5o, '..\\PROGBIN\\R3_ST05.BIN')
check(pn[:0x800] == po[:0x800] and len(pn) == len(po), 'R3_ST05 entry header and size unchanged')
# every differing word of the stage program, labelled from 0x80100000 (only whether the set is empty matters)
diffw = {0x80100000 + k - 0x800 for k in range(0x800, len(pn), 4) if pn[k:k+4] != po[k:k+4]}
check(not diffw, 'R3_ST05 stage program unchanged (the PSP runs its native port in the EBOOT)')
dg = json.load(open(f'build/test/{tag}/ps1_dog.json'))                 # patch_ps1_dog.py's report, copied by build.py
if dg['mode'] == 'ps1':
    for va, (old, nw) in dg['words'].items():
        check(struct.unpack_from('<I', B, int(va, 16))[0] == int(nw, 16) and struct.unpack_from('<I', A, int(va, 16))[0] == int(old, 16), f'PS1 dog scene: EBOOT word {va}')
else:
    # native dog code: kick-target registration (2 words), the two 'was kicked' branches, the wait after the talk
    for va in (0xA7D10, 0xA7D14, 0xA7ECC, 0xA80F0, 0xA87F8):
        check(B[va:va+4] == A[va:va+4], f'dog scene EBOOT word {va:#x} original (talk or kick)')
print(f'options (title={opt["title"]}, menu={menu}, dog={dg["mode"]}): {ok} checks passed; problems: {len(bad)} {bad}')
sys.exit(1 if bad else 0)
