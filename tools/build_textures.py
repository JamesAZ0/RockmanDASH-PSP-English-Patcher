"""Copy reviewed PS1 (USA) textures over their PSP (JP) counterparts (list: script/texture_swaps.json).
Reference: docs/RESEARCH.md §9, §2. Inputs: both disc images (read-only) and the swap list.
Background: the two games share the container format and most textures are byte-identical (JP/US comparison of all
~1,850 container textures: research/tex_compare.py). Where the US game changed a texture that carries text or a
name, the listed textures keep the size, format and VRAM position, so the PS1 pixels can replace the PSP's
directly. US names often
add a 'U' or 'E' (SUB02U, MAP_A1E) or differ entirely (OPENG0-3 for OPMOJI1-4); the list pairs them explicitly.
For each swap and every PSP data file containing that entry, writes
  build/tex_psp/<BIN>/<entry path>.pix   the PS1 pixel data (width*height bytes; same format as the PSP entry)
  build/tex_psp/<BIN>/<entry path>.hdr   (only if "clut": true) PS1 header bytes 0x100-0x800 = the palettes
tools/pack_inplace.py puts these into the ISO. Size/format (colours, width, height, VRAM position) must match.
Swaps marked "legends": true (US name and artwork changes) are only made with --legends, an internal argument set by
build.py for --localization=legends; text and audio builds get only the text-bearing swaps.
"name": every entry with that file name, each from the same data file on the US disc; "clut": "auto" copies the
palette colours where they differ, keeping the PSP's semi-transparency bits."""
import sys, os, io, json, struct, pycdlib
sys.path.insert(0, 'tools'); from rawiso import open_ps1
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
# import tools/inputs.py from this file's own folder, wherever the tool is run from
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '')); import inputs as _IN
PSP = _IN.PSP                    # PSP base image: tools/inputs.py (the path build.py passes in PSP_ISO, or the default)
# All texture entries of every DAT/*.BIN on a disc -> {ENTRY NAME (upper case): [(BIN stem, name, header, data), ...]}.
# An entry starts on a 0x800 boundary with a header whose +0 is the type (1 = texture), +4 the size and +0x40 the
# name "..\dir\file.TIM". suffix = ';1' for the PS1 disc's ISO 9660 version numbers.
def entries(iso, dat, suffix):
    out = {}
    for c in iso.list_children(iso_path=dat):
        fn = c.file_identifier().decode().split(';')[0]
        if not c.is_file() or not fn.upper().endswith('.BIN'): continue
        b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=f'{dat}/{fn}{suffix}'); d = b.getvalue()
        for off in range(0, len(d) - 0x7FF, 0x800):
            nm = d[off+0x40:off+0x80].split(b'\0')[0]
            if nm.startswith(b'..\\') and all(32 <= x < 127 for x in nm) and struct.unpack_from('<I', d, off)[0] == 1:
                size = struct.unpack_from('<I', d, off+4)[0]
                out.setdefault(nm.decode().upper(), []).append((fn[:-4], nm.decode(), d[off:off+0x800], d[off+0x800:off+0x800+size]))
    return out
LEGENDS = '--legends' in sys.argv     # internal argument (build.py --localization=legends): also the "legends" swaps
cfg = json.load(open('script/texture_swaps.json'))
psp = pycdlib.PyCdlib(); psp.open(PSP)
A = entries(psp, '/PSP_GAME/USRDIR/DAT', '')
B = entries(open_ps1(PS1), '/CDDATA/DAT', ';1')
n = skipped = 0
def pairs(sw):
    """(PSP entry path, PS1 entry path) pairs of a swap: "psp"/"ps1" paths, or "name": every entry with that file name."""
    if 'name' in sw: return [(k, k) for k in sorted(A) if k.split(chr(92))[-1] == sw['name'].upper()]
    return [(sw['psp'].upper(), sw['ps1'].upper())]
for sw in cfg['swaps']:
    ps = pairs(sw); assert ps, ('no PSP entry', sw)
    for kp, k1 in ps:
        for bn, nm, h, px in A[kp]:
            base = f"build/tex_psp/{bn}/{nm[3:].replace(chr(92), '/')}"
            if sw.get('legends') and not LEGENDS:               # not in this build: remove an earlier build's files
                for e in ('.pix', '.hdr'):
                    if os.path.exists(base + e): os.replace(base + e, base + e + '.unused')   # (renamed, not deleted: the build folder may not allow deletes)
                skipped += 1; continue
            src = [x for x in B[k1] if x[0].upper() == bn.upper()] or B[k1][:1]   # the same data file's copy if the US disc has one
            _, _, h1, px1 = src[0]
            assert len(px) == len(px1), (sw, len(px), len(px1))
            # The entry's size field also counts the palette bytes, which live in the header, so the data area is shorter
            # than 'size': only the pixel bytes (width*height) may be copied. Copying 'size' bytes ran into the next
            # entry's header (early test build: SUB_WPN's STFF_FE.MSG header got PS1 values, the weapon screen hung).
            # Header +0x24 = width in 16-bit units, +0x28 = height.
            npx = struct.unpack_from('<I', h, 0x24)[0] * 2 * struct.unpack_from('<I', h, 0x28)[0]
            assert npx <= len(px1), (sw, npx, len(px1)); pix = px1[:npx]   # (don't trim px1 itself: an entry can be in several BINs)
            # header 0x0C-0x2C: colour depth, CLUT count, VRAM position, width, height - must be the same on both discs
            assert h[0x0C:0x2C] == h1[0x0C:0x2C], ('format/VRAM position differs', sw)
            clut = sw.get('clut')
            if clut == 'auto':                                   # palettes (header 0x100.., size - pixels - 0x20 bytes) differ?
                nb = struct.unpack_from('<I', h, 4)[0] - npx - 0x20; assert 0 < nb <= 0x700, (sw, nb)
                # The two discs differ in bit 15 (the semi-transparency flag) of most colours; that flag is kept as the
                # PSP has it, only the 15 colour bits come from the PS1.
                ca = struct.unpack_from(f'<{nb // 2}H', h, 0x100); cb = struct.unpack_from(f'<{nb // 2}H', h1, 0x100)
                merged = struct.pack(f'<{nb // 2}H', *[(x & 0x8000) | (y & 0x7FFF) for x, y in zip(ca, cb)])
                clut = merged != h[0x100:0x100 + nb]; h1 = h1[:0x100] + merged + h[0x100 + nb:0x800]
            os.makedirs(os.path.dirname(base), exist_ok=True)
            open(base + '.pix', 'wb').write(pix)
            if clut: open(base + '.hdr', 'wb').write(h1[0x100:0x800])
            elif os.path.exists(base + '.hdr'): os.replace(base + '.hdr', base + '.hdr.unused')
            n += 1; print('swap', bn, nm, '<-', k1, '(+ palettes)' if clut else '')
print(n, 'texture entries written;', skipped, 'legends-only entries left Japanese')
