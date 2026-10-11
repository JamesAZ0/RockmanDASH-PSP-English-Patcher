"""Build check (run by build.py; its output is kept as build/test/<tag>/audit_eboot.txt): account for every difference
between the built program and Sony's, so that nothing unexplained ships. Introduced 2026-09-30 while finding out why
real hardware would not start an early build (docs/RESEARCH.md §5, §15).

Both programs are loaded like the PSP loader does (the loader part of compare_loaded.py), so the comparison is of
relocated memory images, indexed by vaddr; file layout changes that load identically do not count.

1. Changed words inside the original image. Each must fall in a range claimed by a known patch:
     0x3C980-0x3C998      variable-width-font trampoline in the text draw loop (tools/patch_eboot.py)
     0x22691C-0x226BB0    its code and glyph-width table, placed in a block of unreachable maths routines
     0x277C..0x2944       seven immediates that widen the title-menu options from 80 to 86 px
     memmap.SITES         the lui / low-half instructions that build the three moved text-buffer addresses
     0x2479D4, 204 x 12   the DAT file table (disc position and size per data file; tools/pack_inplace.py)
     0x25451C, 248 x 4    system-message pointer table (tools/build_sysmsg.py); 0x2625C8-0x2625D4 the MISSION START /
                          COMPLETE banner sprite-list pointers
     0x23CE1C-0x23DD8C    save-screen strings, plus their pointer slots and format strings (script/savedata_rules.json)
     voice bank table     the English bank slots (segment 1 + voice_banks.BANK_TABLE_SEG1), and the bank-6 path
                          entries of the news reports that game code starts (script/voice_rules.json code_voice)
     0x2607E8...          subtitle master arrays: string-table and timing-table slots (tools/build_subtitles.py)
     option patches       the words listed in the reports ps1_title.json, ps1_dog.json, subtitles.json, psp_menu.json
                          and wide_hud.json (read from next to the program file, else from build/eboot/)
   Anything else is printed as UNACCOUNTED.
2. Memory added after the original image end. Every byte must be reachable: covered by a string, list or table that
   some relocated pointer in the image points to (NUL-terminated strings; banner lists to their end record; subtitle
   tables and strings to their terminators; voice path arrays by clip count; system-message strings up to the next
   pointed-to address), or by the PS1 title templates / wide-HUD code, which are reached PC-relative and are compared
   byte for byte with their reports instead. Unreferenced zero padding is counted; unreferenced non-zero data is
   reported as UNREFERENCED.
3. Informational: bytes of the file that no program header, section or header table refers to (dead file space).

Reads:  the program file given, build/diag/BOOT_sony_plain.BIN (or --original), script/savedata_rules.json,
        script/voice_rules.json, build/voice_en/index.csv (via voice_banks.clips()), the option reports.
Writes: nothing itself (build.py redirects the printed report into the build folder).
Failure (exit 1, stops the build): any UNACCOUNTED word or UNREFERENCED non-zero data. It means a build step changed
        something this audit was not told about - either a bug, or a new patch that must be declared here.

Usage: python3 tools/checks/audit_eboot.py <built EBOOT, plain ELF> [--original build/diag/BOOT_sony_plain.BIN]"""
import sys, os, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'voice'))
import memmap as MM, voice_banks as VB
# take compare_loaded.py's loader (everything before its command-line part) and run it here: defines BASE and load().
# sys.argv is emptied meanwhile and restored afterwards
src = open(os.path.join(os.path.dirname(__file__), 'compare_loaded.py')).read().split('a, na, pa = load')[0]
sys.argv, argv = [sys.argv[0]], sys.argv; exec(src); sys.argv = argv
NEW = sys.argv[1]; ORIG = sys.argv[sys.argv.index('--original') + 1] if '--original' in sys.argv else 'build/diag/BOOT_sony_plain.BIN'
# A = the original program as loaded, B = the built one; both indexed by vaddr
A, _, _ = load(ORIG); B, _, _ = load(NEW)
# known = (start vaddr, end vaddr, reason) ranges inside the original image that the build is allowed to change
known = []
def add(a, b, why): known.append((a, b, why))
add(0x3C980, 0x3C998, 'VWF trampoline'); add(0x22691C, 0x226BB0, 'VWF cave + width table (dead libm block)')
for va in (0x277C, 0x2780, 0x278C, 0x2860, 0x2920, 0x2944, 0x2928): add(va, va + 4, 'title-menu immediate')
for key in MM.SITES:
    for va in MM.SITES[key]['hi'] + MM.SITES[key]['lo']: add(va, va + 4, 'moved text buffer (%s)' % key)
# the DAT file table is at file offset 0x247A54 = vaddr 0x2479D4 (file offset = vaddr + 0x80): 204 entries of 12 bytes
FT = 0x247A54 - 0x80; add(FT, FT + 204 * 12, 'DAT file table (LBA/size)')
# system-message table; the save-screen string area and each rule's pointer slot; the two banner list pointers; the
# save format strings (26 bytes allowed from each given address)
add(0x25451C, 0x25451C + 4 * 248, 'system-message table slots'); add(0x245200 + 0xFB6C, 0x245200 + 0xFB6C + 42, 'weapon development level labels (build_sysmsg.py)'); add(0x41308, 0x4130C, 'level digit position (build_sysmsg.py)'); add(0x23CE1C, 0x23DD8C, 'save-screen strings (build_savetext.py)'); [add(int(r['slot'], 16), int(r['slot'], 16) + 4, 'save-screen pointer (moved to added data when too long)') for r in __import__('json').load(open('script/savedata_rules.json'))['strings']]; add(0x2625C8, 0x2625D4, 'banner list pointers'); [add(int(f['va'], 16), int(f['va'], 16) + 26, 'save format string (savedata_rules formats)') for f in __import__('json').load(open('script/savedata_rules.json')).get('formats', [])]
# 0x245200 = vaddr of segment 1 (.data); the bank table has one pointer per voice bank
for s in VB.SLOTS: add(0x245200 + VB.BANK_TABLE_SEG1 + 4 * s, 0x245200 + VB.BANK_TABLE_SEG1 + 4 * s + 4, 'English voice bank slot')
# _b6 = bank 6's path array (bank-table slot 6, read from the original file as a segment-1 offset); the news reports'
# entries in it, indexed by the clip part (low 16 bits) of each Japanese id, are repointed at English clips
_cv = __import__('json').load(open('script/voice_rules.json'))['code_voice']; _b6 = struct.unpack_from('<I', open('build/diag/BOOT_sony_plain.BIN', 'rb').read(), 0x80 + 0x245200 + VB.BANK_TABLE_SEG1 + 24)[0]
[add(0x245200 + _b6 + 4 * (int(e['jp_id'], 16) & 0xFFFF), 0x245200 + _b6 + 4 * (int(e['jp_id'], 16) & 0xFFFF) + 4, 'news-report path slot -> English clip (code_voice)') for e in _cv['table']['entries'] + [_cv['constant']]]
# subtitle master arrays: set -> (string-table slots, timing-table slots, number of slots). Set B is given here from
# its real start 0x260908 (scene B00 is its index 2)
for _set, (_ms, _mt, _n) in {'A': (0x2607E8, 0x260878, 36), 'B': (0x260908, 0x260998, 36), 'C': (0x260A28, 0x260A48, 8)}.items(): add(_ms, _ms + 4 * _n, 'subtitle string-table slots (build_subtitles.py)'); add(_mt, _mt + 4 * _n, 'subtitle timing-table slots (build_subtitles.py)')
# the option reports: next to the audited file when build.py has copied them there, else the copies in build/eboot/
_ptf = os.path.join(os.path.dirname(NEW), 'ps1_title.json'); _ptf = _ptf if os.path.exists(_ptf) else 'build/eboot/ps1_title.json'
_pt = __import__('json').load(open(_ptf)) if os.path.exists(_ptf) else {'mode': 'psp'}   # PS1 title option (patch_ps1_title.py)
if _pt['mode'] == 'ps1':
    add(_pt['code_range'][0], _pt['code_range'][1], 'PS1 title background code (patch_ps1_title.py)')
    for _va in _pt['words']:
        if not _pt['code_range'][0] <= int(_va, 16) < _pt['code_range'][1]: add(int(_va, 16), int(_va, 16) + 4, 'PS1 title: palette 8 / title-call branches (patch_ps1_title.py)')
_pdf = os.path.join(os.path.dirname(NEW), 'ps1_dog.json'); _pdf = _pdf if os.path.exists(_pdf) else 'build/eboot/ps1_dog.json'
_pd = __import__('json').load(open(_pdf)) if os.path.exists(_pdf) else {'mode': 'jp'}   # PS1 dog option (patch_ps1_dog.py)
for _va in _pd.get('words', {}): add(int(_va, 16), int(_va, 16) + 4, 'PS1 dog scene: no kick (patch_ps1_dog.py)')
_sbf = os.path.join(os.path.dirname(NEW), 'subtitles.json'); _sbf = _sbf if os.path.exists(_sbf) else 'build/eboot/subtitles.json'
_sb = __import__('json').load(open(_sbf)) if os.path.exists(_sbf) else {'mode': 'on'}   # subtitles off option (patch_subtitles.py)
for _va in _sb.get('words', {}): add(int(_va, 16), int(_va, 16) + 4, 'subtitles off (patch_subtitles.py)')
_pmf = os.path.join(os.path.dirname(NEW), 'psp_menu.json'); _pmf = _pmf if os.path.exists(_pmf) else 'build/eboot/psp_menu.json'
for _va in (__import__('json').load(open(_pmf)) if os.path.exists(_pmf) else {}).get('words', {}): add(int(_va, 16), int(_va, 16) + 4, 'psp-menu localized: save icon load buffer (patch_psp_menu.py)')
_bxf = os.path.join(os.path.dirname(NEW), 'subtitle_box.json'); _bxf = _bxf if os.path.exists(_bxf) else 'build/eboot/subtitle_box.json'
_bx = __import__('json').load(open(_bxf)) if os.path.exists(_bxf) else {'mode': 'off'}   # subtitle band without a border (patch_subtitle_box.py)
for _va in _bx.get('words', {}): add(int(_va, 16), int(_va, 16) + 4, 'subtitle box without border: call retargeted to the new code (patch_subtitle_box.py)')
_whf = os.path.join(os.path.dirname(NEW), 'wide_hud.json'); _whf = _whf if os.path.exists(_whf) else 'build/eboot/wide_hud.json'
_wh = __import__('json').load(open(_whf)) if os.path.exists(_whf) else {'mode': 'off'}   # optional wide HUD (patch_wide_hud.py)
for _va in _wh.get('words', {}): add(int(_va, 16), int(_va, 16) + 4, 'wide HUD: call retargeted to the new code (patch_wide_hud.py)')
# why(k): the reason attached to vaddr k, or None
def why(k):
    for a, b, w in known:
        if a <= k < b: return w
unacc = []; counts = {}
for k in range(0, len(A), 4):
    if A[k:k+4] != B[k:k+4]:
        w = why(k)
        if w: counts[w] = counts.get(w, 0) + 1
        else: unacc.append(k)
print('changed words in the original memory, by patch:')
for w, n in sorted(counts.items(), key=lambda x: -x[1]): print('  %5d  %s' % (n, w))
print('UNACCOUNTED changed words:', len(unacc), [hex(k) for k in unacc[:20]])
# --- added memory after the original end: coverage by pointed-to data
END = len(A); ext = len(B) - END; cov = bytearray(ext)
def rd(a): return struct.unpack_from('<I', B, a)[0] - BASE
# ptrs = (vaddr of the pointer, vaddr it points to) for every word that points into the added memory
ptrs = []
for k in range(0, len(B) - 3, 4):
    v = struct.unpack_from('<I', B, k)[0] - BASE
    if END <= v < len(B): ptrs.append((k, v))
def mark(a, n):
    for x in range(a, a + n): cov[x - END] = 1
for src_, v in ptrs:
    if src_ >= END: pass
    if 0x2625C8 <= src_ < 0x2625D4:                      # banner list: 4-byte header + 16-byte records to flag 0xFFFF
        o = v + 4; n = 4
        while struct.unpack_from('<H', B, o + 12)[0] != 0xFFFF: o += 16; n += 16
        mark(v, n + 16); continue
    # is the pointer one of the subtitle master slots? string tables: three arrays of up to 0x90 bytes; timing tables:
    # the two arrays 0x90 after sets A and B, and 0x260A48-0x260A68 for set C
    sub_str = any(ms <= src_ < ms + 0x90 for ms in (0x2607E8, 0x260908, 0x260A28)) and src_ < 0x260A48
    sub_tim = any(mt <= src_ < mt + 0x90 for mt in (0x260878, 0x260998)) or 0x260A48 <= src_ < 0x260A68
    if sub_tim:                                           # subtitle timing table: (start, frames) u16 pairs to 0xFFFF 0xFFFF
        o = v
        while struct.unpack_from('<H', B, o)[0] != 0xFFFF: o += 4
        mark(v, o + 4 - v); continue
    if sub_str:                                           # subtitle string table: pointers to 0; each MSG-format string to 95 + 0000
        o = v
        while struct.unpack_from('<I', B, o)[0]:
            p_ = struct.unpack_from('<I', B, o)[0] - BASE; q = p_
            # 0x383 = the end op (PS1 code 95 + 0x2EE); the string is marked up to and including the u16 after it
            while struct.unpack_from('<H', B, q)[0] != 0x383: q += 2
            mark(p_, q + 4 - p_); o += 4
        mark(v, o + 4 - v); continue
    # 53 = number of slots in the voice bank table
    bank_slot = 0x245200 + VB.BANK_TABLE_SEG1 <= src_ < 0x245200 + VB.BANK_TABLE_SEG1 + 4 * 53
    if bank_slot:                                         # voice path array: count = clips in that bank
        b = VB.SLOTS.index((src_ - 0x245200 - VB.BANK_TABLE_SEG1) // 4); mark(v, 4 * len(VB.clips()[b])); continue
    if src_ >= END and cov[src_ - END] == 0 and not (0x25451C <= src_ < 0x2548FC): pass
    e = B.index(b'\0', v); mark(v, e - v + 1)           # string (system message bytes / path) incl. terminator
if _pt['mode'] == 'ps1':                                  # background primitive templates, reached PC-relative (no pointer)
    assert bytes(B[_pt['data_va']:_pt['data_va'] + _pt['data_len']]).hex() == _pt['data'], 'PS1 title templates not as built'
    mark(_pt['data_va'], _pt['data_len'])
if _bx['mode'] != 'off':                                   # subtitle-background code (tools/patch_subtitle_box.py), reached by the retargeted call (no pointer)
    assert bytes(B[_bx['origin']:_bx['origin'] + _bx['size']]).hex() == _bx['code'], 'subtitle box code not as built'
    mark(_bx['origin'], _bx['size'])
if _wh['mode'] != 'off':                                   # wide-HUD code + state words, reached by the retargeted calls (no pointer)
    assert bytes(B[_wh['origin']:_wh['origin'] + _wh['size']]).hex() == _wh['code'], 'wide HUD code not as built'
    mark(_wh['origin'], _wh['size'])
# system-message strings are MSG-format (not NUL-terminated): mark from each slot to the next pointed-to start
# 0x2548FC = end of the system-message table (0x25451C + 4 * 248)
slots = sorted({v for s, v in ptrs if 0x25451C <= s < 0x2548FC})
for i, v in enumerate(slots):
    nxt = min([x for x in {p for _, p in ptrs} if x > v] + [len(B)]); mark(v, nxt - v)
# walk the coverage map: an uncovered run of zeros is padding, an uncovered run with any non-zero byte is a gap
pad = 0; gaps = []; k = 0
while k < ext:
    if not cov[k]:
        s = k
        while k < ext and not cov[k]: k += 1
        if any(B[END + s:END + k]): gaps.append((hex(END + s), k - s))
        else: pad += k - s
    k += 1
print(f'added memory: {ext} bytes after the original end {END:#x}; unreferenced zero padding {pad} bytes; '
      f'UNREFERENCED non-zero data: {len(gaps)} {gaps[:10]}')
# --- dead file bytes (never loaded, not a section the loader uses)
d = open(NEW, 'rb').read()
phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C)
shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
# used[] marks file bytes something refers to: the 0x34-byte ELF header, both header tables, every segment's file
# bytes, and every section except type 8 (SHT_NOBITS, .bss), which has no file bytes
used = bytearray(len(d)); used[:0x34] = b'\1' * 0x34
def u(a, n): used[a:a + n] = b'\1' * n
u(phoff, 32 * phnum); u(shoff, 40 * shnum)
for k in range(phnum): p = struct.unpack_from('<8I', d, phoff + 32 * k); u(p[1], p[4])
for k in range(shnum):
    s = struct.unpack_from('<10I', d, shoff + 40 * k)
    if s[1] != 8: u(s[4], s[5])
dead = [(a) for a in range(len(d)) if not used[a]]
nz = sum(1 for a in dead if d[a])
print(f'file: {len(d)} bytes; bytes nothing refers to: {len(dead)} ({nz} non-zero)')
if dead:
    runs = []; s = dead[0]; p = s
    for a in dead[1:]:
        if a != p + 1: runs.append((s, p + 1)); s = a
        p = a
    runs.append((s, p + 1)); print('  dead runs:', [(hex(a), b - a) for a, b in runs if b - a >= 16][:10])
sys.exit(1 if unacc or gaps else 0)
