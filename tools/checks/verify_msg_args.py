"""Build check (run by build.py after tools/build_text.py): the dialogue conversion's control-code argument handling.

Background (docs/RESEARCH.md §3): a dialogue file (MSG) is a list of blocks of text and control codes. On the PS1
everything is 8-bit; codes are the bytes 0x84..0xED. On the PSP characters and codes are 16-bit, a code is the PS1 byte
+ 0x2EE, its argument bytes follow unchanged, and an odd number of argument bytes is followed by one 0x00 pad byte.
The argument lengths were derived from the US executable's text engine (script/opcode_args_exe.json,
research/opcode_args_from_exe.py). Three times a wrong length slipped through and broke a menu in play-testing,
because the bytes of a too-short argument are then emitted as text and the jump target or choice count they carried is
lost:
  - E2 / E4 (pause-screen selection ops): 4 argument bytes, not the 1 the engine's scan pass suggests;
  - EC (custom "Original" sort list, block to return to): 2 bytes;
  - B9, CE, E9: laid out differently on the PSP (PS1 'a b c' -> PSP 'a 00 b c'; PS1 'n' -> PSP '00 n').
This script checks for that whole class of error on every block of every file.

Reads:  extracted/psp/**/*.MSG (Japanese PSP, from tools/extract.py) and build/msg_psp/**/*.MSG (built English).
Writes: nothing. Exit 1 on any problem (stops the build).

1. Japanese PSP data: after every odd-length argument the pad byte must be 0 with the current argument table
   (msgtool ARGS / PSP_ARGS). A non-zero pad means the op really has one more argument byte on the PSP - this is the
   test that found EC and CE.
2. Every block of every Japanese and every built English MSG must parse to exactly its end.
3. Ops whose PSP layout differs from the PS1 or that carry jump targets / choice counts (E2 E4 EC B9 CE E9): in
   every built English block that uses them, op and arguments must equal the Japanese block's (same file, same block).
4. PSP-only choice ops (added 2026-09-30): A3 is the Data (save) menu's choice op and AB its MULTI. The PS1 text
   has ordinary SEL / MULTI there; build_text.py gives the English the Japanese ops. Wherever the Japanese block has
   them the English block must have the same ops with the same arguments.

Usage: python3 tools/checks/verify_msg_args.py"""
import sys, os, glob, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); import msgtool as M
def msgs(root): return sorted(p.replace('\\', '/') for p in glob.glob(root + '/**/*.[Mm][Ss][Gg]', recursive=True))   # '/' on every platform
bad = 0
# 1. pad bytes in the Japanese data
nz = {}
for f in msgs('extracted/psp'):
    for bi, b in enumerate(M.blocks(open(f, 'rb').read())[0]):
        # walk the block by hand (not msgtool.parse) so the pad byte itself can be inspected; sel = running choice
        # count
        i = 0; sel = 0
        while i + 2 <= len(b):
            v = struct.unpack_from('<H', b, i)[0]; i += 2; op = v - M.OP_SHIFT
            # below 0x84 + 0x2EE = a character; 0x86 + 0x2EE (0x374) = newline, also a character
            if v < M.FIRST_OP + M.OP_SHIFT or v == 0x86 + M.OP_SHIFT: continue
            n = M.PSP_ARGS.get(op, M.ARGS.get(op, 0))
            # D5 = branch list ended by 0xFF; an argument length of None = MULTI: a type byte + one byte per choice
            if op == 0xD5: j = b.find(b'\xff', i); n = (j - i + 1) if j >= 0 else 2
            elif n is None: n = 1 + sel
            a = b[i:i+n]; i += n
            if op in M.CHOICE_ADD or op in M.PSP_CHOICE_ADD: sel += 1
            if op in M.CHOICE_SET and a: sel = a[-1]
            if op in M.CHOICE_RESET: sel = 0
            # odd argument length: the next byte is the pad; remember the first place it is not 0
            if n % 2:
                if i < len(b) and b[i] != 0: nz.setdefault(op, (f, bi))
                i += 1
print('1. non-zero pad bytes in the Japanese data:', {('%02X' % k): v for k, v in nz.items()} or 'none')
bad += bool(nz)
# 2. clean parse
fails = [(f, bi) for root in ('extracted/psp', 'build/msg_psp') for f in msgs(root)
         for bi, b in enumerate(M.blocks(open(f, 'rb').read())[0]) if not M.parse(b, True, True)[1]]
print('2. blocks that do not parse cleanly:', fails[:5] or 'none'); bad += bool(fails)
# 3. special ops match the Japanese
# x = (kind, op, argument bytes) tokens from msgtool.parse; compare the (op, arguments) lists of both languages
SPECIAL = {0xE2, 0xE4, 0xEC, 0xB9, 0xCE, 0xE9}; ok = 0; diff = []
for f in msgs('build/msg_psp'):
    rel = f[len('build/msg_psp/'):]
    J = M.blocks(open('extracted/psp/' + rel, 'rb').read())[0]; E = M.blocks(open(f, 'rb').read())[0]
    for bi, (a, b) in enumerate(zip(J, E)):
        ea = [(x[1], x[2]) for x in M.parse(b, True, True)[0] if x[0] == 'op' and x[1] in SPECIAL]
        if not ea: continue
        ja = [(x[1], x[2]) for x in M.parse(a, True, True)[0] if x[0] == 'op' and x[1] in SPECIAL]
        if ea == ja: ok += 1
        else: diff.append((rel, '%02X' % bi))
print('3. English blocks with E2/E4/EC/B9/CE/E9 matching the Japanese: %d, differing: %s' % (ok, diff[:5] or 'none'))
bad += bool(diff)
# 4. PSP-only choice ops (A3 = the Data menu's Save choice, AB = its MULTI; added 2026-09-30): wherever the Japanese
#    block has them, the English block must have the same
PSPONLY = {0xA3, 0xAB}; ok4 = 0; diff4 = []
for f in msgs('build/msg_psp'):
    rel = f[len('build/msg_psp/'):]
    J = M.blocks(open('extracted/psp/' + rel, 'rb').read())[0]; E = M.blocks(open(f, 'rb').read())[0]
    for bi, (a, b) in enumerate(zip(J, E)):
        ja = [(x[1], x[2]) for x in M.parse(a, True, True)[0] if x[0] == 'op' and x[1] in PSPONLY]
        if not ja: continue
        ea = [(x[1], x[2]) for x in M.parse(b, True, True)[0] if x[0] == 'op' and x[1] in PSPONLY]
        if ea == ja: ok4 += 1
        else: diff4.append((rel, '%02X' % bi))
print('4. blocks with the PSP-only choice ops A3/AB (Save menu) matching the Japanese: %d, differing: %s' % (ok4, diff4[:5] or 'none'))
bad += bool(diff4)
sys.exit(1 if bad else 0)
