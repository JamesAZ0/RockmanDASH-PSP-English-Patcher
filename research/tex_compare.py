"""Research tool (not run by the build; read-only): compare every TIM texture on the PS1 (USA) and PSP (JP) discs and list
where they differ. This is how the textures carrying text or region-specific artwork were found; the ones the build
swaps are listed in script/texture_swaps.json (docs/RESEARCH.md §9).

Pairing: per data file (DAT/*.BIN) by entry name. The US disc often adds a 'U' before .TIM (SUB02.TIM on the PSP is
SUB02U.TIM on the PS1); failing that, the same name in any other BIN; failing that, the entry at the same position in
the same BIN if the header fields at 0x0C-0x2B (palette and image position in VRAM, colours, palette count, size)
are equal - this finds textures the US disc renamed, e.g. OPMOJI1 -> OPENG0, MAP_A1 -> MAP_A1E.
Status per pair: identical / same pixels, palette differs / pixels differ (with both sizes when the format differs) /
no PS1 counterpart.

Reads:  both disc images (the PS1 path is the constant PS1 below; the PSP one comes from tools/inputs.py).
Writes: logs/texture_compare.md (every non-identical pair) and, for each pair that is not identical, a side-by-side
        sheet build/analysis/tex_compare/<BIN>__<name>.png: PSP left, PS1 right, palette 0 above palette 1.
research/tex_review_page.py executes the first part of this file (the loading and pairing helpers) and builds
a review page from it.

Texture entry layout: see research/tim_dump.py. Only type-1 entries (with pixels) are compared.
Usage: python3 research/tex_compare.py      (needs pycdlib + Pillow)"""
import sys, os, io, struct, hashlib, collections, pycdlib
from PIL import Image, ImageDraw
sys.path.insert(0, 'tools'); from rawiso import open_ps1
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..', 'tools')); import inputs as _IN
PSP = _IN.PSP                    # PSP base image: tools/inputs.py (PSP_ISO=psn|umd|path)
OUT = 'build/analysis/tex_compare'; os.makedirs(OUT, exist_ok=True)
# blocks: for each stored byte in turn, its position in a plain row-by-row image (storage is 64x32-byte blocks)
def blocks(wb, h):
    for y in range(0, h, 32):
        for x in range(0, wb, 64):
            for by in range(32):
                for bx in range(64): yield (y+by)*wb + x+bx
def c15(v): return ((v & 31)*255//31, ((v >> 5) & 31)*255//31, ((v >> 10) & 31)*255//31, 0 if v == 0 else 255)
# info: header fields - colours per palette, palette count, image x / y in VRAM, width in 16-bit words, height,
# palette x / y in VRAM
def info(h):
    g = lambda o: struct.unpack_from('<I', h, o)[0]
    return dict(colors=g(0x14), ncl=g(0x18), vx=g(0x1C), vy=g(0x20), w16=g(0x24), h=g(0x28), clx=g(0x0C), cly=g(0x10))
# image: render with palette number pal (greys if the header has no such palette); None for formats not handled
def image(h, px, pal):
    i = info(h); wb, H = i['w16']*2, i['h']
    if i['colors'] not in (16, 256) or not wb or not H: return None
    lin = bytearray(wb*H)
    for o, p in zip(range(min(len(px), wb*H)), blocks(wb, H)):
        if p < len(lin): lin[p] = px[o]
    n = i['colors']; cl = struct.unpack_from(f'<{n}H', h, 0x100 + pal*n*2) if 0x100 + (pal+1)*n*2 <= 0x800 and pal < max(i['ncl'], 1) else None
    W = wb*2 if n == 16 else wb; data = []
    for y in range(H):
        row = lin[y*wb:(y+1)*wb]
        idx = [v for b in row for v in ((b & 15, b >> 4) if n == 16 else (b,))]
        data += [c15(cl[k]) if cl else ((k*17) % 256,)*3 + (255,) for k in idx[:W]]
    im = Image.new('RGBA', (W, H)); im.putdata(data); return im
# tims: {(BIN stem, entry name): (header, pixels)} for every type-1 .TIM entry in a disc's DAT folder; also fills
# POS[(BIN stem, offset in the BIN, DAT folder)] = entry name, used for the same-position pairing
def tims(iso, dat, suffix):
    res = {}
    for c in iso.list_children(iso_path=dat):
        fn = c.file_identifier().decode().split(';')[0]
        if not c.is_file() or not fn.upper().endswith('.BIN'): continue
        b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=f'{dat}/{fn}{suffix}'); d = b.getvalue()
        for off in range(0, len(d) - 0x7FF, 0x800):
            nm = d[off+0x40:off+0x80].split(b'\0')[0]
            if nm.startswith(b'..\\') and nm.upper().endswith(b'.TIM') and all(32 <= x < 127 for x in nm):
                typ, size = struct.unpack_from('<II', d, off)
                if typ != 1: continue
                h = d[off:off+0x800]; px = d[off+0x800: off+0x800+size]
                res[(fn[:-4].upper(), nm.decode())] = (h, px); POS[(fn[:-4].upper(), off, iso is not None and dat)] = nm.decode()
    return res
POS = {}
ps1 = open_ps1(PS1); psp = pycdlib.PyCdlib(); psp.open(PSP)
# A = PSP textures, B = PS1 textures; Bn = PS1 textures per BIN, keyed by upper-case name
A = tims(psp, '/PSP_GAME/USRDIR/DAT', ''); B = tims(ps1, '/CDDATA/DAT', ';1')
def key(n): s = n.upper().replace('\\', '/'); return s
Bn = collections.defaultdict(dict)
for (bn, nm), v in B.items(): Bn[bn][key(nm)] = (nm, v)
rows = []; seen = {}
for (bn, nm), (h, px) in sorted(A.items()):
    # candidates on the PS1 side: the same name, or the name with 'U' before .TIM
    k = key(nm); cand = [k, k[:-4] + 'U.TIM']
    m = next(((Bn[bn][c]) for c in cand if c in Bn.get(bn, {})), None)
    if m is None:   # same name in any other BIN
        m = next((Bn[b2][c] for b2 in Bn for c in cand if c in Bn[b2]), None)
    if m is None:   # renamed on the US disc (e.g. OPMOJI1 -> OPENG0, MAP_A1 -> MAP_A1E): same BIN, same position, same format
        off = next(o for (b2, o, d), n in POS.items() if b2 == bn and n == nm and d == '/PSP_GAME/USRDIR/DAT')
        n1 = POS.get((bn, off, '/CDDATA/DAT'))
        if n1 and key(n1) in Bn[bn] and Bn[bn][key(n1)][1][0][0x0C:0x2C] == h[0x0C:0x2C]: m = Bn[bn][key(n1)]
    if m is None: rows.append((bn, nm, '-', 'no PS1 counterpart', '')); continue
    nm1, (h1, px1) = m; ia, ib = info(h), info(h1)
    same_fmt = all(ia[x] == ib[x] for x in ('colors', 'w16', 'h'))
    if px == px1 and h[0x100:0x800] == h1[0x100:0x800]: status = 'identical'
    elif px == px1: status = 'same pixels, palette differs'
    else: status = 'pixels differ' + ('' if same_fmt else f" (size PSP {ia['w16']*2*(2 if ia['colors']==16 else 1)}x{ia['h']} vs PS1 {ib['w16']*2*(2 if ib['colors']==16 else 1)}x{ib['h']})")
    img = ''
    if status != 'identical':
        # the same texture pair occurs in many BINs: one sheet per distinct pixel pair
        hsh = hashlib.md5(px + px1).hexdigest()
        if hsh in seen: img = seen[hsh]
        else:
            ims = [image(h, px, 0), image(h1, px1, 0), image(h, px, 1) if ia['ncl'] > 1 else None, image(h1, px1, 1) if ib['ncl'] > 1 else None]
            if ims[0] and ims[1]:
                W = max(i.width for i in ims if i); Hh = max(i.height for i in ims if i)
                sheet = Image.new('RGBA', (2*W + 12, 2*Hh + 40), (40, 40, 70, 255)); d = ImageDraw.Draw(sheet)
                d.text((2, 2), f'PSP {bn} {nm}', fill=(255, 255, 0, 255)); d.text((W + 12, 2), f'PS1 {nm1}', fill=(255, 255, 0, 255))
                for k, im in enumerate(ims):
                    if im: sheet.alpha_composite(im, ((k % 2)*(W + 12), 16 + (k//2)*(Hh + 8)))
                img = f"{OUT}/{bn}__{nm.split(chr(92))[-1][:-4]}.png"; sheet.save(img); seen[hsh] = img
    rows.append((bn, nm, nm1, status, img))
L = ['# Texture comparison: PSP (JP) vs PS1 (USA)', '', f'{len(A)} PSP TIM entries, {len(B)} PS1.', '']
cnt = collections.Counter(r[3].split(' (')[0] for r in rows); L += [f'- {k}: {v}' for k, v in cnt.most_common()] + ['']
L += ['| BIN | PSP entry | PS1 entry | Status | Image |', '|---|---|---|---|---|']
for r in rows:
    if r[3] != 'identical': L.append('| ' + ' | '.join(r) + ' |')
open('logs/texture_compare.md', 'w').write('\n'.join(L) + '\n'); print('\n'.join(L[:12])); print(len([r for r in rows if r[3] != 'identical']), 'non-identical rows;', len(set(seen.values())), 'images')
