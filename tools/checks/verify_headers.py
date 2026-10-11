r"""Build check (run by build.py): no container entry in a changed data file was altered except in the ways the build
intends.

Background (docs/RESEARCH.md §2): each DAT/*.BIN is a chain of entries on 0x800-byte sector boundaries. An entry is a
0x800-byte header followed by its data, padded to whole sectors. Header fields used here:
  +0x00 u32 type            +0x04 u32 data size in bytes       +0x08 u32 sector count
  +0x0C u32 load address (PS1-style 0x80xxxxxx; MSG entries are loaded there)
  +0x40 the entry's source path as a NUL-terminated string starting with ..\  (this is how an entry is recognised)
  +0x100..0x800 for textures: the palettes (CLUTs)
The game loads entries by walking these headers, so a header byte changed by accident breaks loading in ways that are
hard to trace back; hence a byte-level comparison of every header.

Reads:  build/test/<tag>/manifest.json (written by tools/pack_inplace.py: bins_changed, replaced, textures, vab,
        inserted), the built ISO, and the original PSP ISO (tools/inputs.py). Writes nothing.

For every changed BIN, each entry header must equal the original's except:
  - MSG entries replaced with English, and VAB sound banks given English voice samples: bytes 4..11 (size and
    sector count) may differ; the VAB data itself is checked by verify_vab.py;
  - texture entries: bytes 0x100..0x7FF (palettes) may differ; where the manifest records 'header_fields' (the PS1
    title's menu-word texture, whose whole header is replaced), those 4-byte fields may differ too;
  - MSG entries whose text buffer was moved on purpose (tools/memmap.py MOVES: stage, support car and pause-screen
    text go to RAM the PSP port leaves unused, because 16-bit English text does not fit the Japanese buffers; see
    docs/RESEARCH.md §6): bytes 12..15 may change from the old load address to exactly the new one;
  - entries inserted by the build (the PS1 title background NTITLE3U.TIM, with --localization=legends) are left out
    here and checked by verify_ps1_title.py.
The data of every entry that is not a replaced MSG/VAB and not a swapped texture must be byte-identical. After a
resized or inserted entry the following entries shift, so from there on only replaced entries are compared, by index.

A failure (exit 1, stops the build) prints ENTRY COUNT CHANGED, HEADER CHANGED (with the first differing offsets) or
DATA CHANGED: the packer wrote somewhere it should not have.

Usage: python3 tools/checks/verify_headers.py <tag>"""
import sys, io, os, json, struct, pycdlib
sys.path.insert(0, 'tools'); import memmap as MM
tag = sys.argv[1]; P = f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'
man = json.load(open(f'build/test/{tag}/manifest.json'))
# replaced dialogue files as 'BINSTEM|PATH\INSIDE.MSG' (upper case), the form the entry names take below
rep = {m['msg'].split('/')[0].upper() + '|' + m['msg'].split('/', 1)[1].replace('/', '\\').upper() for m in man['replaced']}
tex = {(t['bin'].upper(), t['entry'].upper()) for t in man.get('textures', [])}
vab = {(v['bin'].upper(), v['entry'].upper()) for v in man.get('vab', [])}
# textures whose whole header was replaced: the offsets of the 4-byte header fields that are allowed to differ
hfields = {(t['bin'].upper(), t['entry'].upper()): t['header_fields'] for t in man.get('textures', []) if t.get('header')}
ins = {}
for i_ in man.get('inserted', []): ins.setdefault(i_['bin'].upper(), []).append(i_)   # entries the build inserts after a named entry (the PS1 title background)
# make tools/ importable wherever this file is run from, then take the PSP image path from tools/inputs.py
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '..')); import inputs as _IN
new = pycdlib.PyCdlib(); new.open(P); org = pycdlib.PyCdlib(); org.open(_IN.PSP)
bad = 0; checked = 0
for b in man['bins_changed']:
    # get(iso) = the whole BIN read from that ISO; a = built, o = original
    bn = b['bin']; get = lambda iso: (lambda f: (iso.get_file_from_iso_fp(f, iso_path=f'/PSP_GAME/USRDIR/DAT/{bn}'), f.getvalue())[1])(io.BytesIO())
    a, o = get(new), get(org); stem = bn[:-4].upper()
    # entry headers sit on 0x800 boundaries and carry their path ("..\...") at +0x40
    offs = [off for off in range(0, len(o) - 0x7FF, 0x800) if o[off+0x40:off+0x43] == b'..\\']
    onames = {o[off+0x40:off+0x80].split(b'\0')[0].decode().upper() for off in offs}
    inserted = {i_['entry'].upper() for i_ in ins.get(stem, []) if i_['entry'].upper() not in onames}
    after = {i_['after'].upper() for i_ in ins.get(stem, [])}
    # the same list for the built BIN, without the entries the build inserted, so both lists pair up by index
    noffs = [off for off in range(0, len(a) - 0x7FF, 0x800) if a[off+0x40:off+0x43] == b'..\\' and a[off+0x40:off+0x80].split(b'\0')[0].decode().upper() not in inserted]
    if len(noffs) != len(offs): bad += 1; print('ENTRY COUNT CHANGED', bn, len(offs), len(noffs)); continue
    moved = False
    for k, off in enumerate(offs):
        nm = o[off+0x40:off+0x80].split(b'\0')[0].decode(); key = stem + '|' + nm[3:].upper()
        is_msg = (nm.upper().endswith('.MSG') and key in rep) or (stem, nm.upper()) in vab   # resized entries: size/sectors may change
        if is_msg: moved = True        # entries after a resized MSG shift; stop strict comparison for this BIN
        if moved and not is_msg: continue
        ha, ho = a[noffs[k]:noffs[k]+0x800], o[off:off+0x800]; checked += 1   # same entry in the new BIN (entries shift after a resized one)
        # bytes 4..11 = size + sector count; 0x100..0x7FF = the palette area of a texture header
        allowed = set(range(4, 12)) if is_msg else (set(range(0x100, 0x800)) if (stem, nm.upper()) in tex else set())
        for f_ in hfields.get((stem, nm.upper()), []): allowed |= set(range(f_, f_ + 4)) | set(range(0x100, 0x800))
        # text buffers' load addresses are moved on purpose (tools/memmap.py MOVES: stage, support car, pause)
        # +12 = load address: may change only from a moved buffer's old address to its new one
        if nm.upper().endswith('.MSG') and MM.MOVED.get(struct.unpack_from('<I', ho, 12)[0]) == struct.unpack_from('<I', ha, 12)[0]:
            allowed |= set(range(12, 16))
        diff = [i for i in range(0x800) if ha[i] != ho[i] and i not in allowed]
        if diff: bad += 1; print('HEADER CHANGED', bn, nm, [hex(i) for i in diff[:8]])
        if not is_msg and (stem, nm.upper()) not in tex:
            end = offs[k+1] if k + 1 < len(offs) else len(o)
            if a[off+0x800:end] != o[off+0x800:end]: bad += 1; print('DATA CHANGED', bn, nm)
        if nm.upper() in after: moved = True     # entries after an inserted one shift (checked by index only from here)
print(f'{checked} entry headers checked in {len(man["bins_changed"])} BINs; problems: {bad}')
sys.exit(1 if bad else 0)
