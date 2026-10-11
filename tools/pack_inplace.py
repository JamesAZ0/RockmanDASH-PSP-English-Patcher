"""Build the output ISO WITHOUT changing the disc layout: the last build step before the checks.
Usage: python3 tools/pack_inplace.py <tag> [internal arguments, set by build.py - listed below]
Output: build/test/<tag>/RockmanDASH_EN_<tag>.iso, manifest.json (everything that was changed), and the plain copies
of the program EBOOT_unflat.BIN / EBOOT_plain.BIN that the checks read. Reference: docs/RESEARCH.md §15, §2, §5.

Why in place. The game does not open its data files by name: the program holds a table of 204 (LBA, size, 0) entries,
one per DAT/*.BIN (file offset 0x247A54 of the plain EBOOT), and reads by sector. An ISO rebuilt with a normal tool
moves the files and hangs at the first loading screen, even with unchanged game data; a data file that grows without
its table size being updated is read short (both seen in the first test builds). So:
Copies the original ISO byte-for-byte, then for each DAT/*.BIN splices in the new entries (English MSGs from
build/msg_psp, textures and font from build/tex_psp, sound banks from build/vab_psp) and writes the new BIN at its
ORIGINAL sector if it fits in the space before the next file. The directory record's data length is updated
(LE + BE) and, with --eboot, the size in the program's file table. No file moves; all LBAs stay as on the original.
BINs that would not fit are left Japanese and listed in the manifest, unless --relocate is given:
then such a BIN is written into space freed by other moved or dropped files, or after the end of the original image
(16-sector aligned), and its LBA is updated in the ISO directory record, in the EBOOT DAT file table (needs --eboot)
and the volume size in the PVD. Nothing else moves.
The program itself (--eboot) is written back as a plain, unencrypted ELF, folded to two segments
(tools/flatten_eboot.py); custom firmware and PPSSPP run it as it is.

A dialogue file is only replaced if it fits the RAM buffer it loads into (LIMIT; tools/memmap.py); otherwise it stays
Japanese and the manifest says so. Its entry header keeps the name and gets the new size, sector count and - for the
moved buffers - the new load address.

ISO 9660 fields used: directory record +2 / +6 extent LBA (LE / BE), +10 / +14 data length (LE / BE), +25 flags
(bit 1 = directory), +32 name length, +33 name. Primary volume descriptor (sector 16): +80 / +84 volume size in
sectors, +132 / +136 path-table size, +140 / +144 the two little-endian path tables, +148 / +152 the big-endian ones."""
import sys, os, io, struct, json, shutil, pycdlib
TAG = sys.argv[1]
NO_GROW = '--no-grow' in sys.argv   # only change BINs whose size (in sectors) does not change
# Internal arguments (build.py always passes --eboot --relocate --eboot-src=... --sfo=...; the others by option).
EBOOT_PATCH = '--eboot' in sys.argv  # use decrypted EBOOT with the DAT file table (LBA,size,0 x204) updated
NO_TEXT = '--no-text' in sys.argv     # control build: change nothing but the EBOOT
# (--no-flat)       FLAT off: keep the extra segments. Default is the 2-segment EBOOT like Sony's
#                   (tools/flatten_eboot.py; project decision 2026-09-30)
# --audio           English .at3 files from tools/voice/build_audio.py (build/audio_psp/plan.json) and sound banks
# --drop-jp-voice   with English audio: remove the Japanese voice clips (at3/xa18m*), which nothing then plays
#                   (project decision 2026-09-30)
# --relocate        move BINs that don't fit into freed space / to the end of the image (project decision 2026-09-29)
# --sfo=FILE        PSP menu name: build/sfo/PARAM.SFO (tools/build_sfo.py), same size, written in place
# --ps1-title=DIR   PS1 title screen data (tools/build_ps1_title.py); with --localization=legends
# --icon0=FILE      with --localization=legends: PSP menu icon (same picture as the save image), in place
# --drop-icon1      with --localization=legends: remove the Japanese animated menu icon ICON1.PMF
# --pict=FILE       with --localization=legends: save image (tools/build_savepic.py) -> DAT/PICT/savepic.png, in place
FLAT = '--no-flat' not in sys.argv
AUDIO = '--audio' in sys.argv
DROP_JP_VOICE = '--drop-jp-voice' in sys.argv
RELOCATE = '--relocate' in sys.argv
SFO = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--sfo=')), None)
PS1_TITLE = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--ps1-title=')), None)
ICON0 = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--icon0=')), None)
DROP_ICON1 = '--drop-icon1' in sys.argv
# --pic0=FILE      every build: PSP_GAME/PIC0.PNG (menu overlay) without the Japanese tagline (tools/build_xmb.py)
# --drop-snd0      every build: remove the menu music PSP_GAME/SND0.AT3 (project decision 2026-10-05)
PIC0 = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--pic0=')), None); DROP_SND0 = '--drop-snd0' in sys.argv
PICT = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--pict=')), None)
DEC_EBOOT = next((a.split('=',1)[1] for a in sys.argv if a.startswith('--eboot-src=')), 'decrypted_eboot/ULJM05030_EBOOT.BIN')
# DAT file table in the decrypted EBOOT (found 2026-09-28): file offset, and number of 12-byte entries
# (u32 LBA, u32 size in bytes, u32 0), one per DAT/*.BIN
FT_OFF, FT_N = 0x247A54, 204
# import tools/inputs.py from this file's own folder, wherever the tool is run from
import sys as _s, os as _o; _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), '')); import inputs as _IN
SRC = _IN.PSP                    # PSP base image: tools/inputs.py (the path build.py passes in PSP_ISO, or the default)
OUT = f'build/test/{TAG}'; os.makedirs(OUT, exist_ok=True)
OUT_ISO = f'{OUT}/RockmanDASH_EN_{TAG}.iso'
DAT = '/PSP_GAME/USRDIR/DAT'; SEC = 2048
# Stage MSG buffer: 0x80157000 up to 0x8015BC00, where the game's event-flag bit arrays start (EBOOT refs at
# 0xd8f0/0xe5a0/0x1072c use 0x8015BC00 and 0x8015BD00). LIMIT = {load address: most bytes a MSG may have there}.
LIMIT = {0x80157000: 0x4C00}     # only applies with --no-submsg-move (text buffers not moved)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import memmap as MM
LIMIT.update(MM.LIMITS)          # moved text buffers (stage, support car, pause), tools/memmap.py
MOVE_SUBMSG = '--no-submsg-move' not in sys.argv   # must match the EBOOT (tools/patch_eboot.py always moves them)
# round up to whole 2048-byte sectors
def pad(n): return (n + 0x7FF) & ~0x7FF

iso = pycdlib.PyCdlib(); iso.open(SRC)
# all file extents -> room[path] = bytes from the file's first sector to the next file's (None for the last file)
ext = []
for root, d, f in iso.walk(iso_path='/'):
    for x in f:
        q = root.rstrip('/') + '/' + x; r = iso.get_record(iso_path=q); ext.append((r.extent_location(), r.data_length, q))
ext.sort(); room = {}
for k, (l, s, q) in enumerate(ext):
    room[q] = ((ext[k+1][0] - l) * SEC) if k + 1 < len(ext) else None

# splice: walk one DAT/*.BIN entry by entry (0x800-byte headers: +0 type, +4 data size, +8 sector count, +0x0C load
# address, +0x40 name) and put in whatever the earlier steps built for it. Types seen here: 0 = MSG, 1 = texture,
# 3 = font, 5 = sound bank (VAB), 10 = palette-only twin of a texture. Returns (new bytes, changed?); man = manifest.
def splice(data, stem, man):
    data = bytearray(data); off = 0; changed = False
    while off + 0x800 <= len(data):
        name = bytes(data[off+0x40:off+0x80]).split(b'\0')[0]
        # English voice samples in an SPU sound bank (--audio only): build/vab_psp/<BIN stem>/<entry path> = the whole new
        # entry (header + VAB), from tools/voice/build_vab.py; entries after it shift, like a resized MSG
        # (docs/RESEARCH.md §10). The old entry's length is its sector count (+8).
        if AUDIO and name.startswith(b'..\\') and struct.unpack_from('<I', data, off)[0] == 5:
            vab = 'build/vab_psp/' + stem + '/' + name[3:].decode().replace('\\', '/')
            if os.path.exists(vab):
                secs = struct.unpack_from('<I', data, off+8)[0]; new = open(vab, 'rb').read()
                end = off + secs * 0x800
                assert end == len(data) or bytes(data[end+0x40:end+0x43]) == b'..\\' or struct.unpack_from('<I', data, end)[0] == 0xFFFFFFFF, (vab, 'old entry end is not an entry header / terminator')
                assert len(new) % 0x800 == 0 and new[0x40:0x80] == bytes(data[off+0x40:off+0x80]) and struct.unpack_from('<I', new, 8)[0] * 0x800 == len(new), vab
                data[off:end] = new; changed = True
                man.setdefault('vab', []).append(dict(bin=stem, entry=name.decode(), old_sectors=secs, new_sectors=len(new) // 0x800))
                off += len(new); continue
        # texture/data replacement: build/tex_psp/<BIN stem>/<entry path>.pix = entry data, same size (e.g. title menu)
        # --ps1-title=DIR: DIR/<BIN stem>/<entry path>.pix/.hdr take precedence; .head = the whole 0x800-byte entry header
        # (e.g. a palette count change), .insert = whole entries inserted right after this entry (docs/RESEARCH.md §8)
        if name.startswith(b'..\\') and not name.lower().endswith(b'.msg'):
            rel_ = stem + '/' + name[3:].decode().replace('\\', '/')
            pix = 'build/tex_psp/' + rel_ + '.pix'
            OVL = [x for x in (PS1_TITLE,) if x]          # option data directories (same layout as build/tex_psp)
            for x in OVL:
                if os.path.exists(x + '/' + rel_ + '.pix'): pix = x + '/' + rel_ + '.pix'
            etype = struct.unpack_from('<I', data, off)[0]
            if etype == 10 and os.path.exists(pix[:-4] + '.hdr'):
                # palette-only twin of a texture (same name, type 10, no data; e.g. GAUGE01): give it the same palettes
                # so a palette reload uses the swapped colours too
                hdr = open(pix[:-4] + '.hdr', 'rb').read(); assert len(hdr) == 0x700, pix
                data[off+0x100: off+0x800] = hdr; changed = True
                man.setdefault('textures', []).append(dict(bin=stem, entry=name.decode(), bytes=0, palette_only=True))
            if os.path.exists(pix) and etype != 10:         # data into the entry itself, never into a type-10 palette twin (no data)
                size = struct.unpack_from('<I', data, off+4)[0]; new = open(pix, 'rb').read()
                assert len(new) <= size, (pix, len(new), size)
                # never write into a following entry's header (the size field counts palette bytes kept in the header)
                for s2 in range(off + 0x800, off + 0x800 + len(new), 0x800):
                    assert not bytes(data[s2+0x40:s2+0x43]) == b'..\\', (pix, 'would overwrite the header at', hex(s2))
                data[off+0x800: off+0x800+len(new)] = new; changed = True
                if os.path.exists(pix[:-4] + '.hdr'):     # palettes (header bytes 0x100-0x800), from tools/build_textures.py
                    hdr = open(pix[:-4] + '.hdr', 'rb').read(); assert len(hdr) == 0x700, pix
                    data[off+0x100: off+0x800] = hdr
                man.setdefault('textures', []).append(dict(bin=stem, entry=name.decode(), bytes=size, **({'source': os.path.dirname(pix)} if any(pix.startswith(x) for x in OVL) else {})))
            hd_ = [x + '/' + rel_ + '.head' for x in OVL if os.path.exists(x + '/' + rel_ + '.head')]
            if hd_ and etype != 10:
                head = open(hd_[0], 'rb').read(); old = bytes(data[off:off+0x800])
                assert len(head) == 0x800 and head[:4] == old[:4] and head[0x40:0x80] == old[0x40:0x80] and head[8:12] == old[8:12], ('entry header', rel_)
                fields = sorted({(i // 4) * 4 for i in range(0x100) if head[i] != old[i]})
                data[off:off+0x800] = head; changed = True
                man.setdefault('textures', []).append(dict(bin=stem, entry=name.decode(), header=True, header_fields=fields))
            in_ = [x + '/' + rel_ + '.insert' for x in OVL if os.path.exists(x + '/' + rel_ + '.insert')]
            if in_:
                ins = open(in_[0], 'rb').read(); assert len(ins) % 0x800 == 0 and ins[0x40:0x43] == b'..\\', rel_
                end = next((o_ for o_ in range(off + 0x800, len(data) - 0x7FF, 0x800) if bytes(data[o_+0x40:o_+0x43]) == b'..\\'), None)
                assert end is not None, ('no entry after', rel_)   # insert between two entries (the next header stays intact)
                data[end:end] = ins; changed = True
                man.setdefault('inserted', []).append(dict(bin=stem, after=name.decode(), entry=ins[0x40:0x80].split(b'\0')[0].decode(), sectors=len(ins) // 0x800, at=end))
        # dialogue: replace the entry with the English file from build/msg_psp (entry header + data), provided it fits
        # the buffer it loads into; entries after it shift when the padded size changes
        if name.lower().endswith(b'.msg') and name.startswith(b'..\\') and struct.unpack_from('<I', data, off)[0] == 0:
            size = struct.unpack_from('<I', data, off+4)[0]; addr = struct.unpack_from('<I', data, off+12)[0]
            if addr in MM.MOVED and EBOOT_PATCH and MOVE_SUBMSG:
                # text buffer moved (the patched EBOOT reads it at the new address) - move it even if it stays Japanese
                addr = MM.MOVED[addr]; struct.pack_into('<I', data, off+12, addr); changed = True
            rel = stem + '/' + name[3:].decode().replace('\\', '/')
            new = open('build/msg_psp/' + rel, 'rb').read(); nsize = struct.unpack_from('<I', new, 4)[0]
            limit = LIMIT.get(addr, size)
            if nsize > limit:
                man['kept_japanese'].append(dict(msg=rel, reason='over RAM limit', en_size=nsize, limit=limit)); off += 0x800; continue
            data[off:off + 0x800 + pad(size)] = new[:0x800 + pad(nsize)]
            struct.pack_into('<I', data, off+12, addr)          # keep the (possibly moved) load address
            man['replaced'].append(dict(msg=rel, jp_size=size, en_size=nsize)); changed = True
            off += 0x800 + pad(nsize); continue
        off += 0x800
    return bytes(data), changed


def add_new_dir(fo, files, end_lba, man):
    """New files in ONE new directory (/PSP_GAME/USRDIR/DAT/at3/xaen, the English voice clips; the game opens audio
    files by path, so they need real directory entries - docs/RESEARCH.md §10, §15). The directory
    must sort after every sibling (and its parent must be the last parent in the path table), so nothing else is
    renumbered: its record is appended to the parent's extent (asserted to fit) and its entry to the end of the L and M
    path tables (+ copies); PVD path-table size updated. Records copy the layout of existing ones (XA system-use area).
    Files and the directory extent are placed by ALLOC (freed slots first, then after the image end)."""
    dirs = {q.rsplit('/', 1)[0] for q in files}; assert len(dirs) == 1, dirs
    dpath = dirs.pop(); parent, dname = dpath.rsplit('/', 1)
    pr = iso.get_record(iso_path=parent); sibs = [c for c in iso.list_children(iso_path=parent) if c.is_dir() and c.file_identifier() not in (b'.', b'..')]
    tmpl_dir = max(sibs, key=lambda c: c.file_identifier()); assert dname.encode() > tmpl_dir.file_identifier(), 'new directory must sort last'
    fo.seek(tmpl_dir.extent_location() * SEC); td = fo.read(SEC)
    dot, dotdot = td[:td[0]], td[td[0]:td[0] + td[td[0]]]
    ft = td[td[0] + td[td[0]]:]; ft = ft[:ft[0]]; assert not ft[25] & 2, 'template file record'
    # rec: a directory record copied from a template record, with a new extent, size and name; the template's
    # system-use area (the bytes after its padded name) is kept
    def rec(tmpl, lba, size, name, flags=None):
        nl = len(name); body = bytearray(tmpl[:33]); su = tmpl[33 + tmpl[32] + (0 if tmpl[32] % 2 else 1):]
        struct.pack_into('<I', body, 2, lba); struct.pack_into('>I', body, 6, lba); struct.pack_into('<I', body, 10, size); struct.pack_into('>I', body, 14, size)
        body[32] = nl; r = bytes(body) + name + (b'' if nl % 2 else b'\0') + su; return bytes([len(r)]) + r[1:]
    # file data
    entries = []
    for q in sorted(files):
        data = open(files[q]['file'], 'rb').read(); lba = ALLOC.take(len(data)); fo.seek(lba * SEC); fo.write(data + b'\0' * (pad(len(data)) - len(data)))
        entries.append((q.rsplit('/', 1)[1].encode(), lba, len(data)))
        man['audio'].append(dict(path=q, new_file=True, lba=entries[-1][1], new=len(data), source=files[q].get('source')))
    # directory extent
    recs = [None, dotdot] + [rec(ft, l, n, nm) for nm, l, n in entries]
    ext = bytearray(); 
    def put(r):
        nonlocal ext
        if len(ext) % SEC + len(r) > SEC: ext += b'\0' * (SEC - len(ext) % SEC)
        ext += r
    put(b'\0' * len(dot))
    for r in recs[1:]: put(r)
    ext += b'\0' * (pad(len(ext)) - len(ext)); dsize = len(ext); dlba = ALLOC.take(dsize)
    ext[:len(dot)] = rec(dot, dlba, dsize, b'\0')
    fo.seek(dlba * SEC); fo.write(ext)
    # parent: append the directory record
    fo.seek(pr.extent_location() * SEC); pd = bytearray(fo.read(pr.data_length)); pos = 0
    while pos < len(pd) and pd[pos]: pos += pd[pos]
    fo.seek(tmpl_dir.extent_location() * SEC)
    pos2 = 0; tdr = None
    while pos2 < len(pd) and pd[pos2]:
        if pd[pos2 + 33:pos2 + 33 + pd[pos2 + 32]] == tmpl_dir.file_identifier(): tdr = bytes(pd[pos2:pos2 + pd[pos2]])
        pos2 += pd[pos2]
    nr = rec(tdr, dlba, dsize, dname.encode()); assert pos + len(nr) <= min(len(pd), SEC * (pos // SEC + 1)), 'parent directory full'
    pd[pos:pos + len(nr)] = nr; fo.seek(pr.extent_location() * SEC); fo.write(pd)
    # path tables
    fo.seek(16 * SEC); pvd = bytearray(fo.read(SEC)); ptsize = struct.unpack_from('<I', pvd, 132)[0]
    fo.seek(struct.unpack_from('<I', pvd, 140)[0] * SEC); lt = fo.read(ptsize); o = 0; num = 0; pnum = None
    while o < len(lt):
        l = lt[o]; num += 1
        if struct.unpack_from('<I', lt, o + 2)[0] == pr.extent_location(): pnum = num
        last_parent = struct.unpack_from('<H', lt, o + 6)[0]; o += 8 + l + (l & 1)
    assert pnum and last_parent <= pnum, ('new directory would not be last in the path table', pnum, last_parent)
    nm = dname.encode(); padn = b'\0' if len(nm) % 2 else b''
    # path-table entry: name length, 0, extent LBA (u32), parent directory number (u16), name, pad to even length;
    # appended to both little-endian tables and both big-endian ones
    for loc_off, le in ((140, True), (144, True), (148, False), (152, False)):
        loc = struct.unpack_from('<I' if le else '>I', pvd, loc_off)[0]
        if not loc: continue
        ent = bytes([len(nm), 0]) + struct.pack('<I' if le else '>I', dlba) + struct.pack('<H' if le else '>H', pnum) + nm + padn
        assert (ptsize + len(ent)) <= SEC, 'path table would need another sector'
        fo.seek(loc * SEC + ptsize); fo.write(ent)
    ptsize += 8 + len(nm) + len(padn); struct.pack_into('<I', pvd, 132, ptsize); struct.pack_into('>I', pvd, 136, ptsize)
    fo.seek(16 * SEC); fo.write(pvd)
    man['new_dir'] = dict(path=dpath, lba=dlba, bytes=dsize, files=len(entries), path_table_number=num + 1)
    return None
# raw directory records of DAT
# --- main part: copy the image, then change it in this order: drop Japanese voice files, data files (BINs),
# PARAM.SFO, pictures, audio files, volume size, the program
drec = iso.get_record(iso_path=DAT); dext, dlen = drec.extent_location(), drec.data_length
shutil.copyfile(SRC, OUT_ISO)
PVD0 = open(SRC, 'rb').read(17 * SEC)[16 * SEC:]
if RELOCATE: assert EBOOT_PATCH, '--relocate needs --eboot (the game finds BINs by the LBA in the EBOOT file table)'
end_lba = (os.path.getsize(SRC) // SEC + 15) & ~15   # first free sector after the original image, rounded up to 16
                                                     # (so the known one-sector-short UMD dump gives the same layout)
class Alloc:
    """Disc space for files that no longer fit their original slot (project decision 2026-09-30): the slots they leave
    are zeroed and reused (best fit, sector granular) before anything is added after the original image end.
    free = sorted [first LBA, sectors] blocks, neighbours merged; end = next free LBA after the image (16-aligned)."""
    def __init__(s, end): s.end = end; s.free = []
    def release(s, fo, lba, nbytes):
        n = pad(nbytes) // SEC
        fo.seek(lba * SEC); fo.write(b'\0' * (n * SEC)); s.free.append([lba, n]); s.free.sort()
        merged = []
        for a, b in s.free:
            if merged and merged[-1][0] + merged[-1][1] == a: merged[-1][1] += b
            else: merged.append([a, b])
        s.free = merged
    def take(s, nbytes):
        n = pad(nbytes) // SEC
        fit = [x for x in s.free if x[1] >= n]
        if fit:
            x = min(fit, key=lambda x: (x[1], x[0])); lba = x[0]; x[0] += n; x[1] -= n
            s.free = [y for y in s.free if y[1] > 0]; return lba
        lba = s.end; s.end = (s.end + n + 15) & ~15; return lba
    def unused_sectors(s): return sum(b for _, b in s.free)
ALLOC = Alloc(end_lba)
man = {'tag': TAG, 'method': 'in-place, layout preserved' + (', no-grow' if NO_GROW else '') + (', decrypted EBOOT + file table sizes' if EBOOT_PATCH else '') + (', NO TEXT (control)' if NO_TEXT else '') + (', relocate non-fitting BINs to end' if RELOCATE else ''), 'replaced': [], 'kept_japanese': [], 'bins_changed': [], 'base': dict(path=SRC, kind=_IN.describe(SRC)[0]), 'options': dict(title='ps1' if PS1_TITLE else 'psp', menu='localized' if (PICT and ICON0 and DROP_ICON1) else 'original')}
with open(OUT_ISO, 'r+b') as fo:
    fo.seek(dext * SEC); dirdata = bytearray(fo.read(dlen))
    if DROP_JP_VOICE:
        # Japanese voice folders at3/xa18m*: every file's sectors are zeroed and handed to ALLOC before anything is placed
        # (so moved BINs, English clips and the EBOOT can use them); each folder keeps only its '.' and '..' records.
        # The folders themselves, the path tables and the EBOOT's path strings stay (the paths are never opened:
        # tools/checks/jp_audio_audit.py, checked by tools/checks/verify_dropped.py). Only the file's own sectors are
        # freed (the gap after a file can hold a directory extent).
        assert AUDIO and RELOCATE, '--drop-jp-voice needs --audio and --relocate'
        at3 = '/PSP_GAME/USRDIR/DAT/at3'; man['dropped'] = []
        # the unused (all-zero) sectors between a dropped file and the next extent of any kind are freed with it, so a
        # folder's files merge into one large free block
        starts = sorted({l for l, _, _ in ext} | {iso.get_record(iso_path=r_).extent_location() for r_, _, _ in iso.walk(iso_path='/')}
                        | {struct.unpack_from('<I', PVD0, o_)[0] for o_ in (140, 144)} | {struct.unpack_from('>I', PVD0, o_)[0] for o_ in (148, 152)} | {16})
        import bisect
        for c in iso.list_children(iso_path=at3):
            dn = c.file_identifier().decode()
            if not (c.is_dir() and dn.startswith('xa18m')): continue
            dr = iso.get_record(iso_path=at3 + '/' + dn)
            for f in iso.list_children(iso_path=at3 + '/' + dn):
                if f.file_identifier() in (b'.', b'..'): continue
                assert not f.is_dir()
                l0 = f.extent_location(); nxt = starts[bisect.bisect_right(starts, l0)] if bisect.bisect_right(starts, l0) < len(starts) else end_lba
                span = max(pad(f.data_length), (nxt - l0) * SEC); fo.seek(l0 * SEC + pad(f.data_length)); gap = fo.read(span - pad(f.data_length))
                ALLOC.release(fo, l0, span if gap.count(0) == len(gap) else f.data_length)
                man['dropped'].append(dict(path=at3 + '/' + dn + '/' + f.file_identifier().decode().split(';')[0], lba=f.extent_location(), size=f.data_length))
            fo.seek(dr.extent_location() * SEC); dd = fo.read(dr.data_length); n = dd[0] + dd[dd[0]]
            fo.seek(dr.extent_location() * SEC); fo.write(dd[:n] + b'\0' * (len(dd) - n))
    # --- every DAT/*.BIN: splice, then write in place if it fits before the next file, else (--relocate) into free
    # space or after the image end; a BIN that can do neither is left as the original and reported as kept Japanese
    for bn in sorted(c.file_identifier().decode() for c in iso.list_children(iso_path=DAT) if c.is_file() and c.file_identifier().upper().endswith(b'.BIN')):
        q = f'{DAT}/{bn}'; b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path=q); orig = b.getvalue()
        before = len(man['replaced'])
        new, changed = splice(orig, bn.rsplit('.', 1)[0], man)
        if not changed or NO_TEXT:
            if NO_TEXT: man['replaced'] = [r for r in man['replaced'][:before]]
            continue
        l_old = iso.get_record(iso_path=q).extent_location(); l = l_old; moved = False
        if RELOCATE and len(new) > room[q] and not NO_GROW:
            l = ALLOC.take(len(new)); moved = True
        elif len(new) > room[q] or (NO_GROW and pad(len(new)) != pad(len(orig))):
            # revert: keep this BIN Japanese
            for r in man['replaced'][before:]: man['kept_japanese'].append(dict(msg=r['msg'], reason='BIN would not fit in place' if len(new) > room[q] else 'no-grow mode: BIN size would change', en_size=r['en_size']))
            del man['replaced'][before:]; continue
        if moved: ALLOC.release(fo, l_old, room[q])         # old slot: zeroed, reusable
        elif len(new) < len(orig): fo.seek(l * SEC + len(new)); fo.write(b'\0' * (pad(len(orig)) - len(new)))
        fo.seek(l * SEC); fo.write(new + b'\0' * (pad(len(new)) - len(new)))
        # update directory record length (find record by name within DAT directory sectors)
        pos = 0; found = False
        while pos < len(dirdata):
            rl = dirdata[pos]
            if rl == 0: pos = (pos // SEC + 1) * SEC; continue
            nl = dirdata[pos+32]; nm = bytes(dirdata[pos+33:pos+33+nl]).split(b';')[0]
            if nm == bn.encode() and struct.unpack_from('<I', dirdata, pos+2)[0] == l_old:
                struct.pack_into('<I', dirdata, pos+2, l); struct.pack_into('>I', dirdata, pos+6, l)
                struct.pack_into('<I', dirdata, pos+10, len(new)); struct.pack_into('>I', dirdata, pos+14, len(new)); found = True; break
            pos += rl
        assert found, bn
        man['bins_changed'].append(dict(bin=bn, lba=l_old, old=len(orig), new=len(new), room=room[q], **({'moved_to_lba': l} if moved else {})))
    fo.seek(dext * SEC); fo.write(dirdata)
    if SFO:
        sfo = open(SFO, 'rb').read(); r = iso.get_record(iso_path='/PSP_GAME/PARAM.SFO')
        assert len(sfo) == r.data_length, ('PARAM.SFO must keep its size', len(sfo), r.data_length)
        fo.seek(r.extent_location() * SEC); fo.write(sfo); man['param_sfo'] = dict(source=SFO, lba=r.extent_location(), size=len(sfo))
    # the three picture arguments belong to one build option (--localization=legends)
    assert bool(PICT) == bool(ICON0) == DROP_ICON1, '--pict, --icon0 and --drop-icon1 go together (--psp-menu=localized)'
    for q, src in (('/PSP_GAME/USRDIR/DAT/PICT/savepic.png', PICT), ('/PSP_GAME/ICON0.PNG', ICON0), ('/PSP_GAME/PIC0.PNG', PIC0)):
        if not src: continue
        # PS1 save image / menu icon: in place, within the original file's own sectors; directory record size updated
        png = open(src, 'rb').read(); r = iso.get_record(iso_path=q); l = r.extent_location()
        # 30000 (0x7530) = size of the buffer the game loads savepic.png into and gives the save utility as the icon
        assert pad(len(png)) <= pad(r.data_length) and len(png) <= 30000, (q, 'does not fit', len(png), r.data_length)
        fo.seek(l * SEC); fo.write(png + b'\0' * (pad(r.data_length) - len(png)))
        pr = iso.get_record(iso_path=q.rsplit('/', 1)[0]); fo.seek(pr.extent_location() * SEC); pd = bytearray(fo.read(pr.data_length)); pos = 0; hit = 0
        while pos < len(pd):
            rl = pd[pos]
            if rl == 0: pos = (pos // SEC + 1) * SEC; continue
            nl = pd[pos+32]
            if bytes(pd[pos+33:pos+33+nl]).split(b';')[0].lower() == q.rsplit('/', 1)[1].lower().encode() and struct.unpack_from('<I', pd, pos+2)[0] == l:
                struct.pack_into('<I', pd, pos+10, len(png)); struct.pack_into('>I', pd, pos+14, len(png)); hit += 1
            pos += rl
        assert hit == 1, (q, 'directory record not found')
        fo.seek(pr.extent_location() * SEC); fo.write(pd); man.setdefault('pict', []).append(dict(path=q, source=src, lba=l, old=r.data_length, new=len(png)))
    for name, key in (('ICON1.PMF', 'dropped_icon1'), ('SND0.AT3', 'dropped_snd0')):
        if not {'ICON1.PMF': DROP_ICON1, 'SND0.AT3': DROP_SND0}[name]: continue
        # remove /PSP_GAME/<name>: its directory record is taken out (later records in that sector move up, the rest is
        # zero-filled) and its sectors are zeroed (not reused). Without ICON1.PMF the menu shows ICON0 (still) when the
        # game is highlighted; without SND0.AT3 it plays no music.
        q = '/PSP_GAME/' + name; r = iso.get_record(iso_path=q); l = r.extent_location(); n_ = r.data_length
        pr = iso.get_record(iso_path='/PSP_GAME'); fo.seek(pr.extent_location() * SEC); pd = bytearray(fo.read(pr.data_length)); pos = 0; hit = 0
        while pos < len(pd):
            rl = pd[pos]
            if rl == 0: pos = (pos // SEC + 1) * SEC; continue
            nl = pd[pos+32]
            if bytes(pd[pos+33:pos+33+nl]).split(b';')[0] == name.encode() and struct.unpack_from('<I', pd, pos+2)[0] == l:
                end = (pos // SEC + 1) * SEC; pd[pos:end] = pd[pos+rl:end] + b'\0' * rl; hit += 1; break
            pos += rl
        assert hit == 1, name + ' directory record not found'
        fo.seek(pr.extent_location() * SEC); fo.write(pd)
        fo.seek(l * SEC); fo.write(b'\0' * pad(n_))   # zeroed, not reused (verify_slack.py expects reused space to have been empty)
        man[key] = dict(path=q, lba=l, size=n_)
    if AUDIO:
        # replace whole files by path (audio): in place if the new data fits before the next file, else after the image end
        plan = json.load(open('build/audio_psp/plan.json'))['files']; man['audio'] = []
        newfiles = {}; pending_new = None
        for q in list(plan):
            try: iso.get_record(iso_path=q)
            except Exception: newfiles[q] = plan.pop(q)
        pending_new = newfiles   # replaced files first (their old slots become free), then the new folder
        for q, info in sorted(plan.items()):
            new = open(info['file'], 'rb').read(); r = iso.get_record(iso_path=q); l_old = r.extent_location(); l = l_old
            fit = room[q] if room[q] is not None else pad(r.data_length)   # last file on the disc: only its own sectors
            if len(new) > fit:
                assert RELOCATE, ('audio file does not fit in place', q); l = ALLOC.take(len(new)); ALLOC.release(fo, l_old, fit)
            if l == l_old and len(new) < r.data_length: fo.seek(l * SEC + len(new)); fo.write(b'\0' * (pad(r.data_length) - len(new)))
            fo.seek(l * SEC); fo.write(new + b'\0' * (pad(len(new)) - len(new)))
            parent, leaf = q.rsplit('/', 1); pr = iso.get_record(iso_path=parent)
            fo.seek(pr.extent_location() * SEC); pd = bytearray(fo.read(pr.data_length)); pos = 0; hit = 0
            while pos < len(pd):
                rl = pd[pos]
                if rl == 0: pos = (pos // SEC + 1) * SEC; continue
                nl = pd[pos+32]
                if bytes(pd[pos+33:pos+33+nl]).split(b';')[0].lower() == leaf.lower().encode() and struct.unpack_from('<I', pd, pos+2)[0] == l_old:
                    struct.pack_into('<I', pd, pos+2, l); struct.pack_into('>I', pd, pos+6, l)
                    struct.pack_into('<I', pd, pos+10, len(new)); struct.pack_into('>I', pd, pos+14, len(new)); hit += 1
                pos += rl
            assert hit == 1, ('directory record not found', q)
            fo.seek(pr.extent_location() * SEC); fo.write(pd)
            man['audio'].append(dict(path=q, lba=l_old, old=r.data_length, new=len(new), **({'moved_to_lba': l} if l != l_old else {}), source=info.get('source')))
        if pending_new: add_new_dir(fo, pending_new, None, man)
    if RELOCATE:
        fo.seek(0, 2); tot = fo.tell() // SEC
        if tot < ALLOC.end: fo.write(b'\0' * ((ALLOC.end - tot) * SEC)); tot = ALLOC.end
        fo.seek(16 * SEC); pvd = bytearray(fo.read(SEC)); assert pvd[1:6] == b'CD001' and pvd[0] == 1
        struct.pack_into('<I', pvd, 80, tot); struct.pack_into('>I', pvd, 84, tot)
        fo.seek(16 * SEC); fo.write(pvd); man['volume_sectors'] = tot
    if EBOOT_PATCH:
        eb = bytearray(open(DEC_EBOOT, 'rb').read())
        er = iso.get_record(iso_path='/PSP_GAME/SYSDIR/EBOOT.BIN')
        # file table: original LBA -> file offset of that entry; set the new size (and LBA if the BIN moved)
        table = {struct.unpack_from('<I', eb, FT_OFF + 12*k)[0]: FT_OFF + 12*k for k in range(FT_N)}
        for b in man['bins_changed']:
            o = table[b['lba']]; assert struct.unpack_from('<I', eb, o+4)[0] == b['old']
            struct.pack_into('<I', eb, o+4, b['new'])
            if 'moved_to_lba' in b: struct.pack_into('<I', eb, o, b['moved_to_lba'])
        if FLAT:
            # 2 segments like Sony's (tools/flatten_eboot.py): the 3-/4-segment EBOOTs crashed / gave 80020148 on a
            # PSP Go (ARK-5). Both forms are kept for the checks (compare_loaded.py proves they load identically).
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import flatten_eboot
            open(f'{OUT}/EBOOT_unflat.BIN', 'wb').write(eb); eb = bytearray(flatten_eboot.flatten(bytes(eb)))
            open(f'{OUT}/EBOOT_plain.BIN', 'wb').write(eb)   # the plain ELF (verify_sysmsg.py, compare_loaded.py read it)
        # The EBOOT may grow (tools/build_sysmsg.py adds a segment) as long as it fits before the next file on the disc.
        # Flattening (and the English voice tables) make it too big for its slot: then it moves to free space
        # like a grown BIN (the firmware and PPSSPP open it by path; its directory record gets the new LBA).
        eb_lba = er.extent_location()
        if len(eb) > room['/PSP_GAME/SYSDIR/EBOOT.BIN']:
            assert RELOCATE, ('EBOOT too big for its slot', len(eb), room['/PSP_GAME/SYSDIR/EBOOT.BIN'])
            eb_lba = ALLOC.take(len(eb)); ALLOC.release(fo, er.extent_location(), room['/PSP_GAME/SYSDIR/EBOOT.BIN'])
            fo.seek(0, 2); tot = fo.tell() // SEC
            if tot < ALLOC.end: fo.write(b'\0' * ((ALLOC.end - tot) * SEC)); tot = ALLOC.end
            fo.seek(16 * SEC); pvd = bytearray(fo.read(SEC))
            struct.pack_into('<I', pvd, 80, tot); struct.pack_into('>I', pvd, 84, tot)
            fo.seek(16 * SEC); fo.write(pvd); man['volume_sectors'] = tot
        if len(eb) != er.data_length or eb_lba != er.extent_location():
            sr = iso.get_record(iso_path='/PSP_GAME/SYSDIR'); fo.seek(sr.extent_location() * SEC); sd = bytearray(fo.read(sr.data_length))
            pos = 0; hit = 0
            while pos < len(sd):
                rl = sd[pos]
                if rl == 0: pos = (pos // SEC + 1) * SEC; continue
                nl = sd[pos+32]
                if bytes(sd[pos+33:pos+33+nl]).split(b';')[0] == b'EBOOT.BIN' and struct.unpack_from('<I', sd, pos+2)[0] == er.extent_location():
                    struct.pack_into('<I', sd, pos+10, len(eb)); struct.pack_into('>I', sd, pos+14, len(eb))
                    struct.pack_into('<I', sd, pos+2, eb_lba); struct.pack_into('>I', sd, pos+6, eb_lba); hit += 1
                pos += rl
            assert hit == 1, 'EBOOT directory record not found'
            fo.seek(sr.extent_location() * SEC); fo.write(sd)
        fo.seek(eb_lba * SEC); fo.write(eb + b'\0' * (pad(len(eb)) - len(eb)))
        man['eboot'] = dict(source=DEC_EBOOT, table_offset=hex(FT_OFF), sizes_patched=len(man['bins_changed']), size=len(eb), **({'moved_to_lba': eb_lba} if eb_lba != er.extent_location() else {}))
man['free_sectors_left'] = ALLOC.unused_sectors(); man['free_slots_left'] = ALLOC.free
json.dump(man, open(f'{OUT}/manifest.json', 'w'), indent=1)
print(('audio files %d, ' % len(man['audio'])) if AUDIO else '', end='')
print('replaced', len(man['replaced']), 'kept JP', len(man['kept_japanese']), 'BINs changed', len(man['bins_changed']), '->', OUT_ISO)
