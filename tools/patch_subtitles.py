"""Subtitles on/off: `python build.py <tag> --subtitles=on|off` (default on; project decision, 2026-10-01). build.py
passes the value to this script unchanged.
The PSP adds bottom-of-screen subtitles to voiced scenes (cutscene streams, TV news, radio). All of them start through
one EBOOT function, 0x449D0(scene, set): it picks the scene's timing and string tables, and for a negative scene number
it picks none, shows nothing and returns -1 (the game's own 'no subtitles' path; found by reading the function).
off: the test for a negative scene, 0x44A38 'bltz s1, 0x44A5C', becomes 'b 0x44A5C', so every call takes that path.
The voices, scenes and the subtitle tables themselves are untouched; the word is not relocated.
on: nothing changed here. Which subtitles are shown is --subtitle-language: en = the English tables
tools/build_subtitles.py adds (with English or Japanese audio), jp = the original Japanese ones.
Runs after patch_ps1_dog.py on build/eboot/ULJM05030_EBOOT_en.BIN. See docs/RESEARCH.md §11.
Usage: python3 tools/patch_subtitles.py on|off     Report: build/eboot/subtitles.json"""
import sys, json, struct
MODE = sys.argv[1] if len(sys.argv) > 1 else 'on'; assert MODE in ('on', 'off')
# BASE: file offset of virtual address 0 (code segment); VA: the one word changed
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/subtitles.json'; VA = 0x44A38
if MODE == 'on':
    json.dump(dict(mode='on'), open(REP, 'w')); print('subtitles: on, unchanged'); sys.exit(0)
d = bytearray(open(P, 'rb').read()); r32 = lambda va: struct.unpack_from('<I', d, BASE + va)[0]
# Sony's code relocation table (file offset 0x325018, 0x9F3D8 bytes, 8-byte entries offset + info; bits 8-15 of
# info = the segment the offset is in, 0 = code): the word must not be one the loader rewrites
o = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8]
assert VA not in {struct.unpack_from('<I', o, k)[0] for k in range(0, len(o), 8) if (struct.unpack_from('<I', o, k + 4)[0] >> 8) & 0xFF == 0}, 'relocated word'
# identification: 0x27BDFFE0 addiu sp,sp,-0x20 (function start); 0x06200008 bltz s1,+8 (-> 0x44A5C) with
# 0xAE40AD6C in its delay slot; at 0x44AC4 / 0x44ACC the no-subtitle exit (0x2404FFFF = addiu a0,zero,-1)
assert (r32(0x449D0), r32(VA), r32(VA + 4), r32(0x44AC4), r32(0x44ACC)) == (0x27BDFFE0, 0x06200008, 0xAE40AD6C, 0xAEA0AD4C, 0x2404FFFF), 'subtitle function not as expected'
# 0x10000008 = b +8 (beq zero,zero): same target, always taken
struct.pack_into('<I', d, BASE + VA, 0x10000008); open(P, 'wb').write(d)
json.dump(dict(mode='off', words={hex(VA): ['0x6200008', '0x10000008']}), open(REP, 'w'), indent=1)
print('subtitles: off, 1 EBOOT word changed')
