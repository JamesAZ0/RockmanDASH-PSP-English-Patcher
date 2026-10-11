"""Research tool (not run by the build; read-only; run it by hand whenever tools/memmap.py MOVES changes): use PPSSPP save
states of the ORIGINAL Japanese game to see which parts of the game's PS1-style RAM are really in use, and confirm
that the moved text buffers land in memory that is empty in every state.

Why: the English text needs larger buffers than the Japanese (docs/RESEARCH.md §6). A first choice of new addresses,
picked from static analysis alone, overlapped working memory and crashed. Save states show actual use: the buffers now
sit in the PS1 program area 0x80040100-0x800D9B00, which the PSP port never touches (its code is native), and that
area is empty in every state taken (pause menu, town, shop, ruins, boss fight, cutscene, ...).

State format (PPSSPP 1.20): 0xB0-byte header (u32 version, u32 compression 2 = zstd, u32 compressed size, u32 raw
size, ...), then zstd data. In the raw state the PSP RAM starts at +0x48 (= address 0x08000000); the game module loads
at 0x08804000, and inside it PS1 address 0x80000000 is at vaddr 0x517B00, so PS1 address p is at
raw + 0x804048 + 0x517B00 + (p - 0x80000000). Checked 2026-09-29: the Apple Market state holds the Japanese
ST04_00.MSG exactly at 0x80157000, the stage text's original load address.

Reads:  savestates/*.ppst (or the files given), tools/memmap.py. Needs: pip install zstandard. Writes nothing.
Prints: per moved buffer 'empty in every state' or the range that is in use; then every span of at least 8 KB that
        is empty in all states. Memory is judged in 256-byte steps: a step is 'used' if any byte in it is non-zero
        in any state. Exit 1 if a buffer overlaps used memory.
Limit:  empty in the states taken is evidence, not proof; take states in varied places.

Usage: python3 research/savestate_check.py [savestates/*.ppst]"""
import sys, glob, struct, os, zstandard
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools')); import memmap as MM
# offset of PS1 address 0x80000000 in the raw state: 0x48 + (0x08804000 - 0x08000000) + vaddr 0x517B00
PS1_AT = 0x804048 + 0x517B00
def ps1_ram(path):
    d = open(path, 'rb').read(); ver, comp, csize, usize = struct.unpack_from('<4I', d, 0)
    assert comp == 2, ('not zstd', path)
    raw = zstandard.ZstdDecompressor().decompress(d[0xB0:0xB0 + csize], max_output_size=usize)
    return raw[PS1_AT: PS1_AT + 0x200000]
files = sys.argv[1:] or sorted(glob.glob('savestates/*.ppst'))
R = {os.path.basename(f): ps1_ram(f) for f in files}
# G = granularity in bytes; used_any[k] = 1 when step k of the 2 MB is non-zero in any state
G = 0x100
used_any = bytearray(0x200000 // G)
for r in R.values():
    for k in range(len(used_any)):
        if any(r[k*G:(k+1)*G]): used_any[k] = 1
print('%d states: %s' % (len(R), ', '.join(R)))
bad = 0
# each moved buffer: (old PS1 address, new PS1 address, size limit)
for key, (old, new, lim) in MM.MOVES.items():
    a, b = (new - 0x80000000) // G, (new + lim - 0x80000000) // G
    hit = [0x80000000 + k*G for k in range(a, b) if used_any[k]]
    print('%-8s %08X-%08X: %s' % (key, new, new + lim, 'empty in every state' if not hit else 'IN USE at %X..%X (%d x 256 B)' % (hit[0], hit[-1], len(hit))))
    bad += bool(hit)
print('free spans (empty in every state, >= 8 KB):')
cur = None
for k in range(len(used_any) + 1):
    free = k < len(used_any) and not used_any[k]
    if free and cur is None: cur = k
    if not free and cur is not None:
        if (k - cur) * G >= 0x2000: print('  %08X-%08X %4d KB' % (0x80000000 + cur*G, 0x80000000 + k*G, (k - cur) * G // 1024))
        cur = None
sys.exit(1 if bad else 0)
