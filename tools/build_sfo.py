"""PSP menu (XMB) name: PARAM.SFO values from script/sfo_rules.json -> build/sfo/PARAM.SFO (2026-09-30).
Reference: docs/RESEARCH.md §7, §14.
Input: /PSP_GAME/PARAM.SFO read from the PSP base image (tools/inputs.py); the image is not written.
PARAM.SFO layout: header "\0PSF", version, key-table offset, data-table offset, entry count; then 16-byte index entries
(key offset u16, format u16, used length u32, slot length u32, data offset u32). Format 0x204 = UTF-8 string with NUL,
0x404 = 32-bit integer.
Only UTF-8 string values (fmt 0x204) that already exist can change, each within its fixed slot (max length incl. the NUL);
the file keeps its size and layout, so pack_inplace.py --sfo=build/sfo/PARAM.SFO writes it over the original in place.
DISC_ID, DISC_VERSION, CATEGORY etc. may not change (asserted): the save data and the firmware identify the game by them.
Only TITLE is allowed (ALLOWED); its slot is 128 bytes.
With --menu=localized the values under "localized" replace the top-level ones (2026-10-01).
Usage: python3 tools/build_sfo.py [--menu=original|localized]
--menu is an internal argument, set by build.py: localized for --localization=legends, original otherwise."""
import sys, os, io, json, struct, pycdlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import inputs as IN
ALLOWED = {'TITLE'}
# yield (index, key, format, used length, slot length, absolute offset of the value) for every entry
def entries(d):
    magic, ver, kt, dt, n = struct.unpack_from('<4sIIII', d, 0); assert magic == b'\0PSF'
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', d, 20 + 16 * i)
        yield i, d[kt+ko:d.index(b'\0', kt+ko)].decode(), fmt, ln, mx, dt + do
# the rule file's top-level string values (keys starting with '_' are notes), overridden by 'localized' if asked
def rules_for(menu):
    R = json.load(open('script/sfo_rules.json'))
    r = {k: v for k, v in R.items() if not k.startswith('_') and isinstance(v, str)}
    if menu == 'localized': r.update(R['localized'])
    return r
def main():
    menu = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--menu=')), 'original'); assert menu in ('original', 'localized')
    rules = rules_for(menu)
    assert set(rules) <= ALLOWED, set(rules) - ALLOWED
    iso = pycdlib.PyCdlib(); iso.open(IN.PSP); b = io.BytesIO(); iso.get_file_from_iso_fp(b, iso_path='/PSP_GAME/PARAM.SFO')
    d = bytearray(b.getvalue()); done = set()
    for i, k, fmt, ln, mx, off in list(entries(d)):
        if k not in rules: continue
        v = rules[k].encode('utf-8') + b'\0'; assert fmt == 0x204 and len(v) <= mx, (k, len(v), mx)
        # write the value zero-padded to its slot and update the used length (index entry +4)
        d[off:off+mx] = v + b'\0' * (mx - len(v)); struct.pack_into('<I', d, 20 + 16 * i + 4, len(v)); done.add(k)
        print(f'{k}: {bytes(b.getvalue()[off:off+ln]).rstrip(chr(0).encode()).decode()} -> {rules[k]} ({len(v)}/{mx} bytes)')
    assert done == set(rules), set(rules) - done
    assert len(d) == len(b.getvalue())
    os.makedirs('build/sfo', exist_ok=True); open('build/sfo/PARAM.SFO', 'wb').write(d)
if __name__ == '__main__': main()
