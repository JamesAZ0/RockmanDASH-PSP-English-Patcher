"""English system messages for the EBOOT: menus, save screens, options, item / part / weapon names, help lines,
and the MISSION START / MISSION COMPLETE banner layout. Runs after tools/patch_eboot.py.
Input : build/eboot/ULJM05030_EBOOT_vwf.BIN (tools/patch_eboot.py), extracted/ps1/ROCK_NEO.EXE (the US executable,
        source of the English strings), script/sysmsg_rules.json, script/ps1_charmap.tbl
Output: build/eboot/ULJM05030_EBOOT_en.BIN, report logs/sysmsg_report.json
Reference: docs/RESEARCH.md §7 (system messages), §5 (segments and relocations).

The EBOOT's system-message table (248 relocated pointers at .data vaddr 0x25451C) points to strings in the same 16-bit
format as the dialogue (tools/msgtool.py). It corresponds one-to-one (entries 0-241) with ROCK_NEO.EXE's table of 242
pointers at 0x8008CACC; entries 242-247 are PSP additions (screen-size option, analog variants, the save-delete
hint). Found by static analysis; the map is written by research/system_strings.py (logs/system_strings_map.md).
English 16-bit strings don't fit in the Japanese area (12.5 KB vs 9.4 KB), so (project decision 2026-09-29):
  - the converted PS1 strings are appended to the EBOOT as a third loadable segment (vaddr just after .bss);
  - the program-header table is moved to the end of the file (3 entries) - e_phoff/e_phnum updated;
  - each translated table slot's R_MIPS_32 relocation is retargeted to segment 2 (address-base byte = 2) and the
    stored word set to the string's offset in that segment.
Japanese strings stay where they were (other tables still point at some of them). Kept Japanese: KEEP below.
tools/pack_inplace.py later folds the extra segment back into segment 1 (tools/flatten_eboot.py): PPSSPP loads the
3-segment program, but on a real PSP (tested: PSP Go, ARK-5) it crashed at the title screen.

Relocations (PRX format): 8-byte entries (offset, info). info bits 0-7 = type (2 = R_MIPS_32), bits 8-15 = index of
the segment the offset is relative to, bits 16-23 = index of the segment whose address is added to the stored word.
Segment 0 starts at vaddr 0 (.text, .rodata), segment 1 at 0x245200 (.data, .bss).

Which English goes into a slot: the PS1 string of the same index, converted as it is; or, for the slots the PSP changed
or added (the options screen, the save-delete hint), the entry in script/sysmsg_rules.json, built on the Japanese
string's own control codes (rule kinds: see rule_tokens). The rule texts are approved PSP-specific wording and carry
no review marker."""
import sys, struct, json
sys.path.insert(0, 'tools'); import msgtool as M
SRC, DST = 'build/eboot/ULJM05030_EBOOT_vwf.BIN', 'build/eboot/ULJM05030_EBOOT_en.BIN'
X = open('extracted/ps1/ROCK_NEO.EXE', 'rb').read()
d = bytearray(open(SRC, 'rb').read())
SEG = [0, 0x245200]; BASE = 0x80                           # segment vaddrs; file offset of vaddr 0
RELD, RELD_N = 0x3CF6D0, 0x1E6F0 // 8                      # .rel.data (file offset, entries)
# the PSP table (vaddr, entries) and the PS1 table (entries, address in ROCK_NEO.EXE)
TAB, N_PSP, N_PS1, PS1_TAB = 0x25451C, 248, 242, 0x8008CACC
# Entry 1 is the control legend of a leftover developer screen (an appearance / weapon viewer; only its init function
# 0x4AFB0 reads the slot), not reachable in normal play: project decision (2026-09-29) to leave it Japanese.
KEEP = {1: 'PSP control legend'}   # 38/41-44/49 now come from script/sysmsg_rules.json (options screen, 2026-09-29)
GREEK = set()                 # PS1 codes with no PSP glyph: none now (alpha/omega 0x80/0x81 were, before build_font.py)
# A system string has no length field: it runs to the first of these ops (0x95 is the end op, 0x91 ends the entries
# of the name lists, 0x84 is CLOSE; as seen in the data of both games). cut() keeps the tokens up to and including it.
ENDS = {0x91, 0x95, 0x84}
def cut(t):
    for k, x in enumerate(t):
        if x[0] == 'op' and x[1] in ENDS: return t[:k+1]
    raise ValueError('no end op')
# PS1 string at a RAM address: ROCK_NEO.EXE is loaded at 0x80010000 behind an 0x800-byte file header. 3000 bytes is
# simply more than any string needs (cut() finds the real end).
def ps1_tokens(addr):
    o = addr - 0x80010000 + 0x800; return cut(M.parse(X[o:o+3000], False)[0])
# --- relocation entries of the table slots: rel = {vaddr of the relocated word: index in .rel.data}. Every slot
# must be a R_MIPS_32 (type 2) whose stored word is relative to segment 1 (address base 1).
rel = {}
for k in range(RELD_N):
    o, i = struct.unpack_from('<II', d, RELD + 8*k)
    rel[o + SEG[(i >> 8) & 0xFF]] = k
slots = [TAB + 4*j for j in range(N_PSP)]
assert all(s in rel for s in slots), 'table slot without relocation'
for s in slots:
    o, i = struct.unpack_from('<II', d, RELD + 8*rel[s]); assert i & 0xFF == 2 and (i >> 16) & 0xFF == 1, hex(i)
# qt = the PS1 table: address of the English string for entries 0-241
qt = [struct.unpack_from('<I', X, a - 0x80010000 + 0x800)[0] for a in range(PS1_TAB, PS1_TAB + 4*N_PS1, 4)]
# --- options-screen overrides (script/sysmsg_rules.json; project decision 2026-09-29, no review marker)
RULES = json.load(open('script/sysmsg_rules.json'))['entries']
TBL = {}
for l in open('script/ps1_charmap.tbl', encoding='utf-8'):
    k, v = l.rstrip('\n').split('=', 1)
    if len(v) == 1: TBL.setdefault(v, int(k, 16))
def text_tokens(s):          # English -> PS1-code tokens; '{XXX}' = raw PSP code; '{COL n}' = pad to x = n px in the row
    out = []; i = 0
    while i < len(s):
        if s[i] == '{':
            j = s.index('}', i); f = s[i+1:j]
            out.append(('col', int(f.split()[1])) if f.startswith('COL ') else ('raw', int(f, 16))); i = j + 1
        else: out.append(('c', TBL[s[i]])); i += 1
    return out
VWF = d[BASE + 0x226980: BASE + 0x226980 + 0x1A7]    # per-glyph (lb << 4 | rbx) table written by tools/patch_eboot.py
# psp_code: the PSP glyph a token will be drawn with (for measuring), without the multi-glyph sequences of msgtool
def psp_code(x): return x[1] if x[0] == 'raw' else M.PS1_TO_PSP_CHAR.get(x[1], x[1])
ROW_MAX = 253                                       # widest row allowed (Japanese Camera row ends at 252, box edge ~255)
def resolve_cols(t):
    """Replace ('col', n) with a PAD op so the next text starts n px from the row start (x resets at AF, PAD adds).
    x is tracked the way the patched renderer advances: per glyph (rbx + 1), minus the next glyph's lb; a glyph outside
    the width table counts 12. Op 0xAF starts an option row, op 0xA0 (PAD) takes a u16 pixel count.
    Asserts a gap of at least 4 px before each column and that no row passes ROW_MAX."""
    out = []; x = 0
    for k, tok in enumerate(t):
        if tok[0] == 'op':
            if tok[1] == 0xAF: x = 0
            if tok[1] == 0xA0: x += struct.unpack_from('<H', tok[2])[0]
            out.append(tok)
        elif tok[0] == 'col':
            assert tok[1] - x >= 4, ('column overlap', tok[1], x); out.append(('op', 0xA0, struct.pack('<H', tok[1] - x))); x = tok[1]
        else:
            c = psp_code(tok); e = VWF[c] if c < len(VWF) else 0x0B; x += (e & 15) + 1
            nx = t[k+1] if k + 1 < len(t) else None
            if nx and nx[0] in ('c', 'raw'):
                n = psp_code(nx); x -= (VWF[n] >> 4) if n < len(VWF) else 0
            assert x <= ROW_MAX, ('row too wide', x)
            out.append(tok)
    return out
def jp_tokens(j):            # the slot's original Japanese string (stored word + its address-base segment; 4000 bytes
                             # is more than any string, cut() finds the end)
    o, i = struct.unpack_from('<II', d, RELD + 8*rel[slots[j]])
    v = struct.unpack_from('<I', d, BASE + slots[j])[0] + SEG[(i >> 16) & 0xFF]
    return cut(M.parse(bytes(d[BASE + v: BASE + v + 4000]), True, True)[0])
# One entry of script/sysmsg_rules.json -> tokens. Three kinds:
#   'ps1': n          the PS1 string of entry n, verbatim (used where the PSP moved a line to another slot)
#   'layout_runs'     every op of the Japanese string is kept; its text runs are replaced, in order, by the listed
#                     English runs ('{COL n}' = column position, '{XXX}' = raw PSP glyph); optional 'window' = new WIN
#                     arguments (x u16, y u16, columns, rows), e.g. the save-delete hint's box widened 15 -> 18 columns
#   'lines'           help-box text: the Japanese ops up to DECOR (0x93) and from the first 0x8A op after it are kept;
#                     the English lines go between them, each starting with PAD 6
def rule_tokens(j, r):
    if 'ps1' in r: return ps1_tokens(qt[r['ps1']])
    t = jp_tokens(j)
    if 'layout_runs' in r:   # keep every op, replace text runs in order
        out = []; runs = list(r['layout_runs']); prev_c = False
        if r.get('window'):      # formatting: replace the WIN (0x8C) geometry, e.g. a wider box
            t = [('op', 0x8C, bytes.fromhex(r['window'])) if x[0] == 'op' and x[1] == 0x8C else x for x in t]
        for x in t:
            if x[0] == 'c':
                if not prev_c: out += text_tokens(runs.pop(0))
                prev_c = True
            else: out.append(x); prev_c = False
        assert not runs, ('unused runs', j, runs); return resolve_cols(out)
    # 'lines': keep ops up to DECOR (0x93) and from the first op after the text; one PAD 6 per line
    k0 = next(k for k, x in enumerate(t) if x[0] == 'op' and x[1] == 0x93) + 1
    k1 = next(k for k, x in enumerate(t) if x[0] == 'op' and x[1] == 0x8A and k > k0)
    body = []
    for n, line in enumerate(r['lines']):
        if n: body.append(('c', 0x86))
        body += [('op', 0xA0, b'\x06\x00')] + text_tokens(line)
    return t[:k0] + body + t[k1:]
# --- build blob (one string per distinct PS1 pointer / rule)
blob = bytearray(); where = {}; used = []; kept = []
for j in range(N_PSP):
    if str(j) in RULES:
        key, t = ('rule', j), rule_tokens(j, RULES[str(j)])
    elif j >= N_PS1: kept.append((j, 'PSP-only line')); continue
    elif j in KEEP: kept.append((j, KEEP[j])); continue
    else:
        t = ps1_tokens(qt[j]); key = qt[j]
        if any(x[0] == 'c' and x[1] in GREEK for x in t): kept.append((j, 'alpha/omega glyph')); continue
    if key not in where:
        where[key] = len(blob); b = M.tokens_to_psp(t)
        assert M.parse(b, True, True)[1], ('re-parse failed', j)
        blob += b
    used.append((j, where[key]))
# --- MISSION START / MISSION COMPLETE banner sprite lists (2026-09-29; docs/RESEARCH.md §9). The banner is drawn from
# lists of 16-byte sprite records (screen x, y, texture u, v, clut, w, h, end flag 0xFFFF) in .data, reached through the
# pointers below; the PS1 has the same format and pointer pairs (ROCK_NEO.EXE 0x8008ECE0/ECE8 -> 0x8008DD6C/DDAC). The
# English artwork (GAUGE01u, script/texture_swaps.json) is laid out differently and needs 3 + 6 records instead of 2 + 3,
# so the PS1 lists are copied verbatim into this segment and the two pointers retargeted here.
# BANNER: (PSP pointer slot vaddr, its original stored word, PS1 list address, name). A list is a 4-byte header word
# followed by the records; the end flag is the u16 at record offset 12.
BANNER = [(0x2625C8, 0x1C494, 0x8008DD6C, 'MISSION START'), (0x2625D0, 0x1C4C4, 0x8008DDAC, 'MISSION COMPLETE')]
while len(blob) % 4: blob += b'\0'
banner = []
for slot, psp_val, ps1_addr, what in BANNER:
    o = ps1_addr - 0x80010000 + 0x800; lst = X[o:o+4]; o += 4
    while True:
        rec = X[o:o+16]; lst += rec; o += 16
        if struct.unpack_from('<H', rec, 12)[0] == 0xFFFF: break
    assert struct.unpack_from('<I', d, BASE + slot)[0] == psp_val, (what, hex(slot))
    banner.append((slot, len(blob), what, (len(lst) - 4) // 16)); blob += lst
while len(blob) % 16: blob += b'\0'
# --- weapon development screen: the three 7-character labels of the enhancement list (2026-10-02; docs/RESEARCH.md
# section 7). The text op that prints an attribute's level copies 7 units from one of three templates in .data
# (code 0x412C0-0x41338): segment 1 + 0xFB6C "(level) n" with the digit glyph stored into unit 3 by 'sh a0, 6(a3)'
# at 0x41308, + 0xFB7A "(level) max", + 0xFB88 "cannot be enhanced". The US PS1 has the same three templates as
# 7 bytes each at ROCK_NEO.EXE file offsets 0x887DC "Level n" (digit in byte 6), 0x887E4 "Max Lvl", 0x887EC "N/A".
# They are copied here (PS1 codes mapped like dialogue text) and the digit store moves to unit 6 (offset 12).
LEVEL_VA, LEVEL_PS1, LEVEL_SH = 0x245200 + 0xFB6C, (0x887DC, 0x887E4, 0x887EC), 0x41308
jp_level = struct.unpack_from('<21H', d, BASE + LEVEL_VA)
assert jp_level[:3] == (0xD3, 0xF5, 0xD2) and jp_level[7:12] == (0xD3, 0xF5, 0xD2, 0x241, 0x2B9) and jp_level[14:16] == (0x201, 0x1E5), 'level templates not as expected'
assert struct.unpack_from('<I', d, BASE + LEVEL_SH)[0] == 0xA4E40006, 'level digit store not as expected'
en_level = [0 if (k == 0 and i == 6) else M.PS1_TO_PSP_CHAR.get(X[o + i], X[o + i]) for k, o in enumerate(LEVEL_PS1) for i in range(7)]
assert bytes(X[LEVEL_PS1[0]:LEVEL_PS1[0] + 6]) == bytes([0x20, 0x34, 0x46, 0x34, 0x3B, 0x4F]), 'PS1 level templates not as expected'
struct.pack_into('<21H', d, BASE + LEVEL_VA, *en_level); struct.pack_into('<I', d, BASE + LEVEL_SH, 0xA4E4000C)
# --- new segment + program headers at end of file. ELF header: e_phoff at 0x1C, e_phnum at 0x2C. A program header
# is 8 words: type, file offset, vaddr, paddr, file size, memory size, flags, alignment. The new segment starts at
# the end of segment 1 in memory (vaddr + memsz, i.e. after .bss) rounded up to 0x40: vaddr 0x756AC0.
phoff, phnum = struct.unpack_from('<I', d, 0x1C)[0], struct.unpack_from('<H', d, 0x2C)[0]
assert phnum == 2 and phoff == 0x34
ph = [list(struct.unpack_from('<8I', d, phoff + 32*k)) for k in range(2)]
end1 = ph[1][2] + ph[1][5]; NEWV = (end1 + 0x3F) & ~0x3F
while len(d) % 0x40: d += b'\0'
seg_off = len(d); d += blob
ph.append([1, seg_off, NEWV, 0, len(blob), len(blob), 4, 0x10])     # PT_LOAD, R, align 16
while len(d) % 4: d += b'\0'
new_phoff = len(d)
for p in ph: d += struct.pack('<8I', *p)
struct.pack_into('<I', d, 0x1C, new_phoff); struct.pack_into('<H', d, 0x2C, 3)
# --- retarget relocations of translated slots
for j, off in used:
    k = rel[slots[j]]; o, i = struct.unpack_from('<II', d, RELD + 8*k)
    struct.pack_into('<II', d, RELD + 8*k, o, (i & ~0xFF0000) | (2 << 16))
    struct.pack_into('<I', d, BASE + slots[j], off)                  # stored value is segment-relative
for slot, off, what, n in banner:                                   # banner list pointers -> segment 2
    k = rel[slot]; o, i = struct.unpack_from('<II', d, RELD + 8*k); assert i & 0xFF == 2 and (i >> 16) & 0xFF == 1, (what, hex(i))
    struct.pack_into('<II', d, RELD + 8*k, o, (i & ~0xFF0000) | (2 << 16)); struct.pack_into('<I', d, BASE + slot, off)
open(DST, 'wb').write(d)
json.dump({'segment_vaddr': hex(NEWV), 'file_offset': hex(seg_off), 'bytes': len(blob), 'translated': len(used),
           'kept_japanese': [{'entry': j, 'why': w} for j, w in kept], 'rules': sorted(int(k) for k in RULES)},
          open('logs/sysmsg_report.json', 'w'), indent=1)
print(f'system messages: {len(used)} entries English ({len(where)} strings, {len(blob)} bytes, segment 2 at vaddr {NEWV:#x}); '
      f'{len(kept)} kept Japanese ({len(RULES)} from sysmsg_rules.json); banner lists ' + ', '.join(f'{w} {n} sprites' for _, _, w, n in banner) + f'; EBOOT {len(d)} bytes -> {DST}')
