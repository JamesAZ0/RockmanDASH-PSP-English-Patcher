"""Build check (run by build.py): the built ISO's PSP_GAME/PARAM.SFO.

PARAM.SFO is what the PSP's own menu reads: the game's name (TITLE), DISC_ID (ULJM05030), version, category. Only the
values named in script/sfo_rules.json may change - in practice TITLE, which tools/build_sfo.py sets per PSP-menu
option ('original' or 'localized', recorded in manifest.json options.menu; build.py picks 'localized' for
--localization=legends). Everything else must be byte-identical to the original, because DISC_ID and the other keys
are how the firmware and existing saves recognise the game (docs/RESEARCH.md §7, §14).

Reads:  the built ISO, the original PSP ISO (tools/inputs.py), script/sfo_rules.json through build_sfo.rules_for(),
        build/test/<tag>/manifest.json. Writes nothing; prints each rule value as found.
Checks: same file size; for every index entry the key, format, slot size and data offset are unchanged; a ruled key
        holds exactly the rule's text + NUL with the rest of its fixed slot zero; every other value and length is
        the original's; and no byte outside the ruled values' slots and their length fields differs.
Failure (exit 1, stops the build): 'size', '<key>: layout', '<key>: value', '<key>: changed' or 'bytes outside the rule
        values changed'.

Usage: python3 tools/checks/verify_sfo.py <tag>"""
import sys, io, json, pycdlib
sys.path.insert(0, 'tools'); import inputs as IN, build_sfo as B
tag = sys.argv[1]
# g(path) = the PARAM.SFO bytes of that ISO; n = built, o = original
g = lambda p: (lambda i, f: (i.open(p), i.get_file_from_iso_fp(f, iso_path='/PSP_GAME/PARAM.SFO'), f.getvalue())[2])(pycdlib.PyCdlib(), io.BytesIO())
n, o = g(f'build/test/{tag}/RockmanDASH_EN_{tag}.iso'), g(IN.PSP)
rules = B.rules_for(json.load(open(f'build/test/{tag}/manifest.json')).get('options', {}).get('menu', 'original'))   # per menu option (original | localized)
bad = []; changed = set()
if len(n) != len(o): bad.append('size')
# build_sfo.entries yields (index, key, format, used length, slot size, data offset) for each entry
for (i, k, fmt, ln, mx, off), (_, k2, fmt2, ln2, mx2, off2) in zip(B.entries(n), B.entries(o)):
    val = n[off:off+ln]
    if (k, fmt, mx, off) != (k2, fmt2, mx2, off2): bad.append(f'{k}: layout')
    elif k in rules:
        if val != rules[k].encode() + b'\0' or any(n[off+ln:off+mx]): bad.append(f'{k}: value')
        # bytes allowed to differ: the value slot, and the used-length field of index entry i (16-byte entries from
        # offset 20; +4)
        changed.update(range(off, off + mx)); changed.update(range(20 + 16 * i + 4, 20 + 16 * i + 8))
        print(f'{k} = {val[:-1].decode()}')
    elif (val, ln) != (o[off2:off2+ln2], ln2): bad.append(f'{k}: changed')
if [j for j in range(min(len(n), len(o))) if n[j] != o[j] and j not in changed]: bad.append('bytes outside the rule values changed')
print('PARAM.SFO problems:', bad or 0); sys.exit(1 if bad else 0)
