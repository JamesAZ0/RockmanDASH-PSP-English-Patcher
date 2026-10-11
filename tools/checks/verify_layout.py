"""Build check (run by build.py): the built ISO's disc layout is sound. Every file and directory extent must lie inside
the volume and no two may overlap; the path tables and volume descriptors must not be overlapped either.

Why it exists: the game opens its DAT files by disc position (an LBA table in the program, docs/RESEARCH.md §5), so
the packer (tools/pack_inplace.py) never rebuilds the image. It copies the original and writes changed files in
place; a file that outgrows its slot is moved to a slot another file freed, or past the original image end, and the
slot it leaves is zeroed and offered for reuse (introduced 2026-09-30, docs/RESEARCH.md §15). This check proves that
bookkeeping never put two things in the same sectors.

Reads:  build/test/<tag>/RockmanDASH_EN_<tag>.iso (the primary volume descriptor directly, the directory tree via
        pycdlib). Writes nothing.
Prints: number of files and extents, volume size, and how many sectors no extent uses.
Failure (exit 1, stops the build): OUTSIDE VOLUME or OVERLAP with the two paths involved.

Usage: python3 tools/checks/verify_layout.py <tag>"""
import sys, struct, pycdlib
tag = sys.argv[1]; SEC = 2048; P = f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'
# primary volume descriptor = sector 16; +80 = volume size in sectors (little-endian copy), +132 = path table size
f = open(P, 'rb'); f.seek(16 * SEC); pvd = f.read(SEC); vol = struct.unpack_from('<I', pvd, 80)[0]
ptsz = struct.unpack_from('<I', pvd, 132)[0]
ext = [(0, 16, 'system area'), (16, 2, 'volume descriptors')]
# PVD +140/+144 = LBA of the little-endian path table and its optional copy; +148/+152 the big-endian ones
for off in (140, 144): ext.append((struct.unpack_from('<I', pvd, off)[0], (ptsz + SEC - 1) // SEC, 'L path table'))
for off in (148, 152): ext.append((struct.unpack_from('>I', pvd, off)[0], (ptsz + SEC - 1) // SEC, 'M path table'))
iso = pycdlib.PyCdlib(); iso.open(P); files = 0
for root, dirs, fs in iso.walk(iso_path='/'):
    r = iso.get_record(iso_path=root); ext.append((r.extent_location(), (r.data_length + SEC - 1) // SEC, root + '/'))
    for x in fs:
        q = root.rstrip('/') + '/' + x; r = iso.get_record(iso_path=q); files += 1
        if r.data_length: ext.append((r.extent_location(), (r.data_length + SEC - 1) // SEC, q))
# drop entries at LBA 0 (absent optional path tables), then put the system area (LBA 0) back
ext = [e for e in ext if e[0]]  + [ext[0]]
# sorted by start sector: each extent must end inside the volume and before the next one starts
ext.sort(); bad = 0; used = 0
for k in range(len(ext)):
    a, n, q = ext[k]; used += n
    if a + n > vol: bad += 1; print('OUTSIDE VOLUME:', q)
    if k + 1 < len(ext) and a + n > ext[k + 1][0]: bad += 1; print('OVERLAP:', q, 'and', ext[k + 1][2])
print(f'{files} files, {len(ext)} extents in {vol} sectors ({vol * SEC / 1048576:.1f} MB); '
      f'overlaps/outside: {bad}; sectors not used by any extent: {vol - used}')
sys.exit(1 if bad else 0)
