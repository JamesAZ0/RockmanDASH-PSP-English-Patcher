"""Separate check, NOT run by build.py: test the optional wide-screen HUD code (tools/patch_wide_hud.py, build option
--hud=center|edge) by running it in a MIPS emulator on real frames. Needs: pip install unicorn zstandard, and PPSSPP
save states in savestates/*.ppst and widehudfix_savestates/*.ppst.

Background (docs/RESEARCH.md §13): in the Wide screen setting the game stretches its whole 320x240 frame to 480x272,
so the HUD, windows and text come out about 1.32 times too wide. The frame is drawn by the native DrawOTag
(0x216F0C), which walks one primitive list. Its top-level ordering table is 8 slots at *(segment 1 + 0x500800) +
0x70..0x8C, walked from +0x8C down: +0x80 the 3D world, +0x7C windows and text, +0x78 HUD, +0x74 front. Every
primitive handler converts x positions and widths with one function, 0x217214 (x * 2), after adding the draw offset
(segment 1 + 0x15AD58). The option retargets existing calls to new code appended to the program: DrawOTag's call of
0x2172E0 at its start, its call of 0x2212D8 after each primitive, its call of 0x217530 at the end, and the x-scale
calls. While the Screen setting is Wide (segment 1 + 0x15AD50 == 0) and the walker is past the +0x7C node, x is scaled
by 1.5 instead of 2 and a bias on the draw offset places the result: 53 = centred, 0 = left edge, 107 = right edge.

A save state holds the whole RAM, including the primitive list of the frame being drawn, so the new code can be run
on real frames without the game. For each state, each variant (center, edges, hudonly) and both Screen settings, the assembled
code is written into a copy of the state's memory and:
  - start hook: run up to its call of the original 0x2172E0 (emulated as an immediate return), then to its return;
  - post hook: run once per primitive in list order (as DrawOTag does after drawing it), up to its tail jump to the
    original 0x2212D8, checking it gets there with the caller's return address and s0 intact;
  - end hook: run to its tail jump to 0x217530.
After each step the code's state words and the draw offset are compared with a Python model of the intended rules
(model() and prescan() below): nothing is squeezed in the world/backdrop slots or outside Wide; primitives and clip
rectangles 300 or more units wide (fades, backdrops) are left alone; windows/text and the front slot are centred; in
the HUD slot the 'edges' variant keeps pieces wholly left of x 80 at the left edge and pieces wholly right of x 240 at
the right edge, but only while the world slot has primitives (menus are centred as a whole); and a layer of tiles
running unbroken across the HUD slot (cutscene overlays) turns the squeeze off for that slot in that frame. The
x-scale functions are checked on sample values.
Given a tag, it first checks that the built program holds exactly the assembled code at the recorded address and that
the retargeted calls point at it (or, for hud off, that those call sites are the original's), and then emulates only
the variant that was built. (The variants are called center, edges and hudonly internally; --hud=edge selects edges, --hud=hud-only hudonly.)

Reads:  the save states; tools/patch_wide_hud.py (assemble(), the site lists and constants); with a tag,
        build/test/<tag>/wide_hud.json, EBOOT_plain.BIN and build/diag/BOOT_sony_plain.BIN. Writes nothing.
Prints: per state and variant, the number of primitives and how many were squeezed, by layer and bias.
Failure: an AssertionError naming the step and primitive, or exit 1 when the built code differs. It means the code
        does not implement the rules for that frame. What it cannot show is how the result looks in play.

Usage: python3 research/verify_wide_hud.py [tag]"""
import sys, os, glob, json, struct, collections, zstandard
from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import *
sys.path.insert(0, 'tools'); import patch_wide_hud as W
# BASE = load address of the game module; SEG1 = vaddr of segment 1 (.data). ORIGIN = vaddr the code is placed at for
# the emulation without a tag (a built program records its own in wide_hud.json; why this value: origin not recorded).
# STOP = a return address inside mapped RAM that no code uses; reaching it means "returned to the caller"
BASE = 0x08804000; SEG1 = 0x245200; ORIGIN = 0x75A000; STOP = 0x08000100
# OTP = pointer to the structure holding the top-level ordering table; TVAR / BVAR = the two words DrawOTag uses to
# turn a 24-bit tag into a pointer; WIDE = Screen setting (0 = Wide); OFFX = draw offset x. All are vaddrs in segment
# 1
OTP, TVAR, BVAR, WIDE, OFFX = SEG1 + 0x500800, SEG1 + 0x509668, SEG1 + 0x509678, SEG1 + 0x15AD50, SEG1 + 0x15AD58
def ram(path):
    # PPSSPP state file: 0xB0-byte header (u32 version, compression 2 = zstd, compressed size, raw size), then zstd
    # data; in the raw state the PSP RAM (0x08000000, 32 MB) starts at +0x48
    d = open(path, 'rb').read(); ver, comp, csize, usize = struct.unpack_from('<4I', d, 0); assert comp == 2
    raw = zstandard.ZstdDecompressor().decompress(d[0xB0:0xB0 + csize], max_output_size=usize)
    return bytearray(raw[0x48:0x48 + 0x2000000])                   # PSP RAM 0x08000000..0x0A000000
def run_state(path, variant):
    M = ram(path); u32 = lambda a: struct.unpack_from('<I', M, a - 0x08000000)[0]; s16 = lambda a: struct.unpack_from('<h', M, a - 0x08000000)[0]
    code, L = W.assemble(ORIGIN, SEG1, W.FLAGS[variant]); blob = struct.pack(f'<{len(code)}I', *code)
    otp, T, B = u32(BASE + OTP), u32(BASE + TVAR), u32(BASE + BVAR)
    if not otp: return None
    # nxt: follow a primitive's tag the way the game's walker does: low 24 bits; 0xFFFFFF ends the list; values below
    # *TVAR get *BVAR + 0x1000000 as base, the others *BVAR
    def nxt(a):
        v = u32(a) & 0xFFFFFF
        if v == 0xFFFFFF: return None
        p = v | (B + 0x1000000 if v < T else B)
        return p if p & 0xFFFFFF else None
    # list in order: (ptr, zone, world flag, full-screen-HUD flag) as the look-ahead knows them when it reaches each
    # primitive
    # extent(p) -> (left x, width) of a primitive, from its code byte at +7 (PS1 GPU command codes): E3 = clip
    # rectangle (x in bits 0-9 of the word at +4, w in bits 9-18 of the word at +8); 0x60-0x7F rectangles / sprites
    # (the width word for the free-size kind, else 0 / 8 / 16 for the 1x1, 8x8 and 16x16 kinds); 0x40-0x5F lines and
    # codes below 0x20: no width; 0x20-0x3F polygons: second vertex x minus first (vertex stride depends on the
    # textured and shaded bits)
    def extent(p):
        c = M[p - 0x08000000 + 7]; x0 = s16(p + 8); w = 0
        if c == 0xE3: x0 = u32(p + 4) & 0x3FF; w = (u32(p + 8) >> 9) & 0x3FF
        elif c >= 0x60: w = s16(p + 12 + (c & 4)) if not c & 0x18 else (((c & 0x18) >> 3) - 1) * 8
        elif c >= 0x40 or c < 0x20: w = 0
        else:
            w = s16(p + 12 + (c & 4) + ((c & 0x10) >> 2)) - x0
            if w < 0: x0 += w; w = -w
        return x0, w
    # prescan: one look over the HUD slot (from its node to the +0x74 node). Pieces wholly left of LEFT_MAX / right of
    # RIGHT_MIN form the edge bands; if the middle pieces start exactly where the left band ends and end exactly where
    # the right band starts, the slot is one unbroken layer -> 1 (do not squeeze it this frame)
    def prescan(a):
        cells = set(); n = 0; clamp = lambda k: max(0, min(W.CELLS - 1, k))
        while True:
            a = nxt(a); n += 1
            if a is None or a - otp == 0x74 or n > 400000: break
            # length byte 0 at +3 = an ordering-table node without a primitive; codes 0x80 and above are not shapes
            if not M[a - 0x08000000 + 3] or M[a - 0x08000000 + 7] >= 0x80: continue
            x0, w = extent(a)
            if w >= W.FULL: continue
            k1, k0 = clamp(x0 >> 3), clamp((x0 + max(w, 1) - 1) >> 3)     # 8-unit columns the piece covers
            cells.update(range(k1, k0 + 1))
        return frozenset(cells)
    # walk the frame from the top slot (+0x8C). d_ = offset of a node inside the structure: +0x80 = the world slot was
    # reached, +0x7C / +0x78 / +0x74 start zones 1 (windows + text), 2 (HUD), 3 (front). "world" becomes 1 when a real
    # primitive is seen after the +0x80 node and before any 2D zone
    prims = []; zone = 0; a = otp + 0x8C; n = 0; w80 = world = 0; hudmode = frozenset()
    while True:
        a = nxt(a); n += 1
        if a is None or n > 400000: break
        d_ = a - otp
        if d_ == 0x80: w80 = 1
        if d_ in (0x7C, 0x78, 0x74): zone = {0x7C: 1, 0x78: 2, 0x74: 3}[d_]
        if d_ == 0x78: hudmode = prescan(a)
        if M[a - 0x08000000 + 3]:
            if not zone and w80: world = 1
            prims.append((a, zone, world, hudmode))
    def model(p, zone, world, hudmode, wide):
        """-> (squeeze, bias) intended for primitive p"""
        if not zone or not wide: return 0, 0
        if variant == 'hudonly' and (zone != 2 or not world): return 0, 0   # only the HUD slot, only with a world
        c = M[p - 0x08000000 + 7]
        if c >= 0x80 and c != 0xE3: return 1, W.CENTER
        x0, w = extent(p)
        if w >= W.FULL: return 0, 0
        if zone != 2: return 1, W.CENTER
        # the run of covered columns this piece belongs to (hudmode = the set of covered columns)
        L = R = max(0, min(W.CELLS - 1, x0 >> 3))
        while L > 0 and L - 1 in hudmode: L -= 1
        while R < W.CELLS - 1 and R + 1 in hudmode: R += 1
        if L == 0 and R == W.CELLS - 1: return 0, 0                      # covers the whole width: tiled overlay
        if not world: return 1, W.CENTER                                 # menus
        if L < W.LEFT_MAX // 8:
            if R >= W.RIGHT_MIN // 8: return 1, W.CENTER                 # reaches both bands: banner, title line
            bias = 0
        else:
            if R < W.RIGHT_MIN // 8: return 1, W.CENTER
            bias = W.RIGHT
        if R - L >= W.PANEL: return 0, 0                                 # a wide panel at one side: left alone
        return 1, (bias if W.FLAGS[variant] & 1 else W.CENTER)
    out = {}
    for wide in (1, 0):
        mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 + UC_MODE_LITTLE_ENDIAN); mu.mem_map(0x08000000, 0x2000000)
        mu.mem_write(0x08000000, bytes(M)); mu.mem_write(BASE + ORIGIN, blob)
        # the Screen setting word: 0 = Wide, anything else = the original 4:3 picture; draw offset x starts at 0
        mu.mem_write(BASE + WIDE, struct.pack('<I', 0 if wide else 1)); mu.mem_write(BASE + OFFX, struct.pack('<H', 0))
        A = lambda n: BASE + L[n]; rd = lambda a: struct.unpack('<I', mu.mem_read(a, 4))[0]; off = lambda: struct.unpack('<h', mu.mem_read(BASE + OFFX, 2))[0]
        def call(entry, until, **regs):
            mu.reg_write(UC_MIPS_REG_SP, 0x09F00000); mu.reg_write(UC_MIPS_REG_RA, STOP)
            for k, v in regs.items(): mu.reg_write({'s0': UC_MIPS_REG_S0, 'a0': UC_MIPS_REG_A0, 't8': UC_MIPS_REG_T8}[k], v)
            mu.emu_start(entry, until, count=3000000); return mu.reg_read(UC_MIPS_REG_PC)
        # state words at label 'vars': +0 squeeze on/off, +4 bias, +8 non-zero while the bias is added to the draw
        # offset (as read here), +16 variant (1 = edges), +24 world flag, +28 unbroken-HUD-layer flag. state() =
        # (squeeze, bias in effect, draw offset); want(i) = the model's answer for primitive i
        state = lambda: (rd(A('vars')), rd(A('vars') + 4) if rd(A('vars') + 8) else 0, off())
        want = lambda i: (lambda m, b: (m, b, b))(*model(*prims[i], wide)) if i < len(prims) else (0, 0, 0)
        # x-scale functions
        for mode, bias in ((0, 0), (1, 53), (1, 107), (1, 0)):
            mu.mem_write(A('vars'), struct.pack('<II', mode, bias))
            # f scales a width, fpos a position (adds the bias itself): x * 3 / 2 while squeezing, x * 2 otherwise
            for x in (0, 1, 7, 12, 160, 319, 320, -5, -160, 1000):
                for fn, exp in (('f', (x * 3) >> 1 if mode else x * 2), ('fpos', ((x + bias) * 3) >> 1 if mode else x * 2)):
                    mu.reg_write(UC_MIPS_REG_A0, x & 0xFFFFFFFF); mu.reg_write(UC_MIPS_REG_RA, STOP); mu.emu_start(A(fn), STOP, count=100)
                    # v0 as a signed 32-bit value
                    got = mu.reg_read(UC_MIPS_REG_V0); got -= (got & 0x80000000) << 1
                    assert got == exp and mu.reg_read(UC_MIPS_REG_PC) == STOP, (fn, mode, bias, x, got, exp)
        mu.mem_write(A('vars'), bytes(16) + struct.pack('<I', W.FLAGS[variant]))
        mu.mem_write(A('vars'), struct.pack('<4I', 1, 99, 0, 3)); mu.mem_write(A('vars') + 20, struct.pack('<3I', 1, 1, 1)); mu.mem_write(A('vars') + W.MASK1, struct.pack('<I', 5))                       # stale values the start hook must clear
        # start hook: the original 0x2172E0 is emulated as "return at once"
        def hook(uc, addr, size, ud):
            if addr == BASE + W.START_OLD: uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA)); ud.append(1)
        seen = []; h = mu.hook_add(UC_HOOK_CODE, hook, seen, BASE + W.START_OLD, BASE + W.START_OLD)
        mu.mem_write(BASE + W.START_OLD, struct.pack('<II', 0x03E00008, 0))            # jr ra; nop (only reached through the hook)
        pc = call(A('start'), STOP, s0=otp + 0x8C); mu.hook_del(h)
        assert pc == STOP and mu.reg_read(UC_MIPS_REG_SP) == 0x09F00000, 'start hook did not return cleanly'
        assert state() == want(0), ('first primitive', state(), want(0))
        cnt = collections.Counter()
        for i, (p, zone, wf, hm) in enumerate(prims):
            m, b = model(p, zone, wf, hm, wide); cnt[(zone, m, b)] += 1
            if M[p - 0x08000000 + 7] == 0xE5:                                           # the E5 handler stores the offset from the primitive
                mu.mem_write(BASE + OFFX, struct.pack('<H', u32(p + 8) & 0xFFFF))
            base_off = off() - (rd(A('vars') + 4) if rd(A('vars') + 8) else 0)
            pc = call(A('post'), BASE + W.POST_OLD, s0=p)
            assert pc == BASE + W.POST_OLD and mu.reg_read(UC_MIPS_REG_RA) == STOP and mu.reg_read(UC_MIPS_REG_S0) == p, ('post hook', hex(p))
            w = want(i + 1); got = state()
            assert (got[0], got[1], got[2] - base_off) == w, ('after primitive', i, hex(p), got, base_off, w)
        pc = call(A('end'), BASE + W.END_OLD)
        assert pc == BASE + W.END_OLD and mu.reg_read(UC_MIPS_REG_RA) == STOP and rd(A('vars')) == 0 and rd(A('vars') + 8) == 0, 'end hook'
        mk = sum(1 << k for k in hudmode); assert (rd(A('vars') + W.WORLD), rd(A('vars') + W.MASK0), rd(A('vars') + W.MASK1)) == (world, mk & 0xFFFFFFFF, mk >> 32), ('world flag / column mask', world, hex(mk))
        out['wide' if wide else 'original'] = cnt
    assert not any(m for (z, m, b) in out['original']), 'squeezing in Original mode'
    assert not any(m for (z, m, b) in out['wide'] if z == 0), 'squeezing the world'
    return len(prims), out['wide'], world, hudmode
bad = 0
if len(sys.argv) > 1:                                                                   # the built EBOOT holds exactly this code
    tag = sys.argv[1]; rep = json.load(open(f'build/test/{tag}/wide_hud.json'))
    src = open(os.path.join(os.path.dirname(__file__), 'compare_loaded.py')).read().split('a, na, pa = load')[0]
    _argv = sys.argv; sys.argv = [sys.argv[0]]; exec(src); sys.argv = _argv
    Bm, _, _ = load(f'build/test/{tag}/EBOOT_plain.BIN'); Am, _, _ = load('build/diag/BOOT_sony_plain.BIN')
    if rep['mode'] == 'off':
        ok = all(Bm[va:va+4] == Am[va:va+4] for va in W.F_SITES + W.FPOS_SITES + [W.START_SITE, W.POST_SITE, W.END_SITE])
        print('wide HUD off: the hooked calls are the original:', ok); sys.exit(0 if ok else 1)
    code, L = W.assemble(rep['origin'], SEG1, W.FLAGS[rep['mode']], [bytes.fromhex(x) for x in rep['strings']]); blob = struct.pack(f'<{len(code)}I', *code)
    ok1 = bytes(Bm[rep['origin']:rep['origin'] + len(blob)]) == blob == bytes.fromhex(rep['code'])
    # a jal to vaddr "to" as it reads in loaded memory: opcode 3, target (load base + vaddr) / 4
    jal = lambda to: (0x0C000000 | ((to + BASE) >> 2)) & 0xFFFFFFFF                     # as relocated at the load address
    # every retargeted call site -> the label it must now call
    exp = {**{va: L['f'] for va in W.F_SITES}, **{va: L['fpos'] for va in W.FPOS_SITES}, W.OPT_SITE: L['opt'], W.START_SITE: L['start'], W.POST_SITE: L['post'], W.END_SITE: L['end']}
    ok2 = all(struct.unpack_from('<I', Bm, va)[0] == jal(to) for va, to in exp.items())
    print(f'wide HUD {rep["mode"]}: code in the loaded EBOOT = assembled: {ok1}; {len(exp)} calls go to the new code: {ok2}'); bad += not (ok1 and ok2)
    variants = [rep['mode']]
else: variants = ['center', 'edges', 'hudonly']
for v in variants:
    for f in sorted(glob.glob('savestates/*.ppst')) + sorted(glob.glob('widehudfix_savestates/*.ppst')):
        r = run_state(f, v)
        if r is None: print(v, os.path.basename(f), 'no frame list'); continue
        n, cnt, world, hudmode = r
        z = {0: 'world/backdrop', 1: 'windows+text', 2: 'HUD', 3: 'front'}
        print(f'{v:6s} {os.path.basename(f)}: {n} primitives OK; world {world}, HUD columns {len(hudmode)}; Wide: ' + ', '.join(f'{z[k[0]]} {"squeezed bias %d" % k[2] if k[1] else "unchanged"}: {c}' for k, c in sorted(cnt.items())))
print('wide HUD emulation problems:', bad); sys.exit(1 if bad else 0)
