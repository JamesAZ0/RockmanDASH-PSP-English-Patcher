"""Build check (the first one build.py runs): resolve every voice id through the built program's sound tables, exactly as
the game will, and compare the file path it arrives at.

Background (docs/RESEARCH.md §5, §10): a sound id is type << 28 | bank << 16 | clip. For voices (type 0) the play
routines read a pointer at segment 1 + 0xA938 to the bank table (53 slots, one pointer per bank; 0 = unused bank),
then the bank's path array, then the path string ('disc0:/PSP_GAME/USRDIR/DAT/at3/...'). There are only null checks,
no bounds checks, so a wrong table entry plays the wrong file or crashes. The Japanese game uses 16 of the bank slots;
tools/voice/patch_eboot_voice.py fills the 36 free ones (voice_banks.SLOTS; never slot 6) with new path arrays for the
English clips at3/xaen/eBB_CC.at3, each new pointer with a new relocation.
Five clips are started by game code rather than by dialogue text: the City Hall TV news reports, ids in bank 6 taken
from a 4-entry table and from one lui/ori constant (script/voice_rules.json 'code_voice'). Bank-6 ids also start the
news subtitle scenes, so the ids are kept and those clips' entries in bank 6's path array are pointed at the English
clips instead.

Reads:  build/eboot/ULJM05030_EBOOT_en.BIN (the program after all patch steps, before packing; a plain ELF),
        build/voice_en/jp_clips.json (the Japanese clips and their paths), build/voice_en/index.csv (via
        voice_banks.clips()), script/voice_rules.json. Writes nothing.
The file is loaded like the PSP loader does it: every loadable segment at base + vaddr, then every relocation
section (type 0x700000A0) applied; only R_MIPS_32 entries matter for data pointers, so only those are applied.
Checks: every Japanese id gives its original path (except, with English voices, the repointed news clips);
        with English voices ('en') every English bank slot gives the xaen path for each of its clips, and each news
        id gives the English clip named in the rules; with Japanese voices ('jp') the English slots must be empty and
        the news ids must give the original Japanese paths.
Failure (exit 1, stops the build): 'wrong' is non-zero; news mismatches are printed with both paths.

Usage: python3 tools/checks/verify_voice_eboot.py [--audio=jp|en]
The --audio argument is internal: build.py passes en for --localization=audio and legends, jp for text."""
import sys, os, struct, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'voice')); import voice_banks as VB
AUDIO = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--audio=')), 'en')
# BASE = the address the game module is loaded at in PSP memory (as seen in PPSSPP save states)
d = open('build/eboot/ULJM05030_EBOOT_en.BIN', 'rb').read(); BASE = 0x08804000
# ELF header: program headers at e_phoff (0x1C), count 0x2C; section headers at e_shoff (0x20), count 0x30
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
ph = [struct.unpack_from('<8I', d, phoff + 32 * k) for k in range(phnum)]
# program header p: p[1] file offset, p[2] vaddr, p[4] file size, p[5] memory size. mem is indexed by vaddr
mem = bytearray(max(p[2] + p[5] for p in ph) + 0x100)
for p in ph: mem[p[2]:p[2] + p[4]] = d[p[1]:p[1] + p[4]]
segv = [p[2] for p in ph]; n = 0
for k in range(shnum):
    s = struct.unpack_from('<10I', d, shoff + 40 * k)
    # 0x700000A0 = PSP relocation section. Entry (offset, info): t = type, ob = segment the offset is relative to, ab
    # = segment whose load address is added. Type 2 = R_MIPS_32: word += load base + that segment's vaddr
    if s[1] != 0x700000A0: continue
    for j in range(s[5] // 8):
        o, i = struct.unpack_from('<II', d, s[4] + 8 * j); t, ob, ab = i & 0xFF, (i >> 8) & 0xFF, (i >> 16) & 0xFF
        if t == 2:
            a = segv[ob] + o; struct.pack_into('<I', mem, a, struct.unpack_from('<I', mem, a)[0] + BASE + segv[ab]); n += 1
# rd / cs: read a u32 / a C string at an absolute (loaded) address
def rd(a): return struct.unpack_from('<I', mem, a - BASE)[0]
def cs(a): a -= BASE; e = mem.index(b'\0', a); return mem[a:e].decode()
# 0x245200 = vaddr of segment 1 (.data); +0xA938 holds the pointer to the voice bank table
banks = rd(BASE + 0x245200 + 0xA938)
jp = json.load(open('build/voice_en/jp_clips.json'))['clips']; bad = 0; ok = 0
# the Japanese news clips that English builds repoint; they are skipped in the loop over Japanese ids and checked last
_cv = json.load(open('script/voice_rules.json'))['code_voice']
_repointed = {v_['jp'] for v_ in _cv['table']['entries'] + [_cv['constant']]} if AUDIO == 'en' else set()   # checked below
for key, v in jp.items():
    if v['path'] in _repointed: continue
    # key = 'bank,clip'; bank table -> path array -> path string
    b, c = map(int, key.split(',')); arr = rd(banks + 4 * b); p = cs(rd(arr + 4 * c))
    if not p.endswith('/at3/' + v['path']): bad += 1
    else: ok += 1
if AUDIO == 'en':
    C = VB.clips()
    for b, lst in C.items():
        arr = rd(banks + 4 * VB.SLOTS[b])
        for c in range(len(lst)):
            if not arr or cs(rd(arr + 4 * c)) != VB.game_path(b, c): bad += 1
            else: ok += 1
else:
    # Japanese-voice build: no English slot may be filled
    bad += sum(1 for s in VB.SLOTS if rd(banks + 4 * s))
# voice ids the game code starts directly (news reports, script/voice_rules.json code_voice)
CV = json.load(open('script/voice_rules.json'))['code_voice']
# path_of: id -> path (bank = bits 16..27, clip = low 16 bits). want: the path that rule entry e should give; an
# English clip is named like 'bBB_cCC_K' in the rules, BB = PS1 bank; its clip number = its position in that bank's
# list
def path_of(i): return cs(rd(rd(banks + 4 * ((i >> 16) & 0xFFF)) + 4 * (i & 0xFFFF)))
def want(e): return (VB.game_path(int(e['en'][1:3]), [k for k, f in enumerate(VB.clips()[int(e['en'][1:3])]) if f.endswith('/' + e['en'] + '.xa')][0])
                     if AUDIO == 'en' else 'disc0:/PSP_GAME/USRDIR/DAT/at3/' + e['jp'])
# the 4 table ids, then the id built by the lui (upper 16 bits) / ori (lower 16 bits) pair
news = [(rd(BASE + int(CV['table']['va'], 16) + 4 * e['index']), e) for e in CV['table']['entries']]
k = CV['constant']; news.append(((rd(BASE + int(k['lui_va'], 16)) & 0xFFFF) << 16 | (rd(BASE + int(k['ori_va'], 16)) & 0xFFFF), k))
for i, e in news:
    if path_of(i) == want(e): ok += 1
    else: bad += 1; print('news report', e['scene'], hex(i), path_of(i), '!=', want(e))
print(f'{n} R_MIPS_32 relocations applied; voice ids resolved correctly: {ok}; wrong: {bad} (mode {AUDIO})')
sys.exit(1 if bad else 0)
