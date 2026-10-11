"""Build check (run by build.py): the English text the game hands to the PSP's save utility is in the built program,
and the strings that identify the save are untouched.

Background (docs/RESEARCH.md §7, §14): the save screen's title, difficulty, play time, location names and the two
Memory Stick errors are UTF-8 C strings in the program's read-only data, each reached through a relocated pointer
slot. tools/build_savetext.py writes the English over the Japanese, or - when it does not fit - into added data with
the slot's relocation retargeted. script/savedata_rules.json lists each string by its pointer slot ('strings') and the
format strings patched in place by address ('formats', e.g. the play time). With the PSP-menu option 'localized'
(--localization=legends) the save name uses the rule's en_ps1_save value instead of en.

Reads:  build/test/<tag>/EBOOT_plain.BIN and build/diag/BOOT_sony_plain.BIN, both loaded like the PSP loader does
        (the loader part of compare_loaded.py, so pointers are real addresses), script/savedata_rules.json, and
        build/test/<tag>/manifest.json (options.menu). Writes nothing.
Checks: every slot's pointer leads to exactly the expected English string; every format string is as given; and the
        save identity strings ULJM05030, %04d and DATA.BIN are found at the same address in both programs. The
        identity is what makes saves interchangeable with the unmodified Japanese game, so it must never move or change.
Failure (exit 1, stops the build): WRONG / WRONG FORMAT with the slot or address, or fewer than 3 identity strings.

Usage: python3 tools/checks/verify_savetext.py <tag>"""
import sys, os, json, struct
# take compare_loaded.py's loader (everything before its command-line part) and run it here: defines BASE and load()
src = open(os.path.join(os.path.dirname(__file__), 'compare_loaded.py')).read().split('a, na, pa = load')[0]
tag = sys.argv[1]; sys.argv = [sys.argv[0]]; exec(src)
B, _, _ = load(f'build/test/{tag}/EBOOT_plain.BIN'); A, _, _ = load('build/diag/BOOT_sony_plain.BIN')
# cs: the NUL-terminated string at vaddr a of a loaded image
def cs(m, a): e = m.index(b'\0', a); return bytes(m[a:e])
bad = 0; R = json.load(open('script/savedata_rules.json'))['strings']
MENU = json.load(open(f'build/test/{tag}/manifest.json')).get('options', {}).get('menu', 'original')   # menu 'localized' (--localization=legends) -> PS1 save name
for s in R:
    # the slot holds an absolute address after relocation; minus the load base = vaddr of the string
    slot = int(s['slot'], 16); p = struct.unpack_from('<I', B, slot)[0] - BASE
    if cs(B, p).decode('utf-8') != (s.get('en_ps1_save', s['en']) if MENU == 'localized' else s['en']): bad += 1; print('WRONG', s['slot'], cs(B, p)[:40])
F = json.load(open('script/savedata_rules.json')).get('formats', [])
for f in F:
    if cs(B, int(f['va'], 16)).decode() != f['en']: bad += 1; print('WRONG FORMAT', f['va'], cs(B, int(f['va'], 16)))
same = 0
for ident in (b'ULJM05030\0', b'%04d\0', b'DATA.BIN\0'):
    # first occurrence in each loaded image; equal positions = the string did not move (0 or -1 = not found / invalid)
    ka = A.find(ident); kb = B.find(ident); same += (ka == kb and ka > 0)
print(f'save-screen strings ({MENU} save name): {len(R) + len(F) - bad}/{len(R) + len(F)} correct (incl. {len(F)} format); save identity strings unchanged at the same address: {same}/3')
sys.exit(1 if bad or same != 3 else 0)
