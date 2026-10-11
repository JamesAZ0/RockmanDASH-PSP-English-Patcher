"""The lamp-post scene's dog, as the US PS1 release has it. Build option, off by default:
`python build.py <tag> --paprika=good-dog` (project decision, 2026-10-01); build.py then passes the internal argument
`ps1` to this script, and `jp` for the default --paprika=fair-game.
In the scene where Tron is stuck on a lamp post and Paprika growls at her, the Japanese game lets the player either
talk to the dog (ST05_00.MSG block 04, "Hey, cut it out! ...") or kick it. The US PS1 release removed the kick; this
option does the same. The dialogue is the same in both games: the difference is code only.
Where: the PSP runs its own native port of the stage code in the EBOOT (the PS1 R3000 stage program in ST05.BIN is
still on the disc but is not what runs: a build that patched it was tested in game and the dog could still be
kicked). The US changes were found by diffing the Japanese and US PS1 stage programs (R3_ST05: kick-target
registration and both 'kicked' tests deleted, wait after the talk scene 0x8C -> 0xAA frames); the same spots in the
PSP's native dog code (EBOOT 0xA7xxx-0xA8xxx, identified by the same hit flags at +0x358, 0x20000000 test, yelp
sound 0xAF, state 7, sounds 0x16F/0x171) are patched here:
  0xA7D10/14  b 0xA7CE8 ; move a0,s0   skip the kick-target registration (jal 0x20C2C with s0+0x358), as the existing
                                       'j 0xA7CE8 ; move a0,s0' after it does
  0xA7ECC     bnez v0,kicked -> nop    first 'kicked' test never taken (delay slot addiu v0,0x7FFF is overwritten next)
  0xA80F0     bnez v0,kicked -> nop    second 'kicked' test, same
  0xA87F8     sltiu v1,v0,0x8C -> 0xAA wait after the talk scene, as the US (longer English lines)
No relocated word is touched. Runs after build_savetext.py (build.py: after patch_wide_hud.py) on
build/eboot/ULJM05030_EBOOT_en.BIN. Not included: the other US/JP differences of that stage program (lip-sync
timings; a second kickable object). See docs/RESEARCH.md §12.
Usage: python3 tools/patch_ps1_dog.py ps1|jp   (internal argument, set by build.py)
Report: build/eboot/ps1_dog.json"""
import sys, json, struct
MODE = sys.argv[1] if len(sys.argv) > 1 else 'jp'; assert MODE in ('ps1', 'jp')
# BASE: file offset of virtual address 0 (code segment)
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/ps1_dog.json'
if MODE == 'jp':
    json.dump(dict(mode='jp'), open(REP, 'w')); print('dog scene: Japanese (talk or kick), unchanged'); sys.exit(0)
d = bytearray(open(P, 'rb').read()); words = {}
def r32(va): return struct.unpack_from('<I', d, BASE + va)[0]
def w32(va, old, new):
    assert r32(va) == old, ('unexpected original word', hex(va), hex(r32(va))); words[va] = [old, new]; struct.pack_into('<I', d, BASE + va, new)
# b: unconditional branch (beq zero,zero) from address `at` to `to`
def b(at, to): return 0x10000000 | (((to - (at + 4)) >> 2) & 0xFFFF)
# rel = the code addresses Sony's relocation table rewrites at load (table at file offset 0x325018, 0x9F3D8 bytes,
# 8-byte entries offset + info; bits 8-15 of info = the segment the offset is in, 0 = code)
o = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8]
rel = {struct.unpack_from('<I', o, k)[0] for k in range(0, len(o), 8) if (struct.unpack_from('<I', o, k + 4)[0] >> 8) & 0xFF == 0}
# identification asserts: the kicked tests and the registration call as described above
# each kicked test: 0x8E020358 lw v0,0x358(s0) (hit flags) and 0x3C032000 lui v1,0x2000 (the 0x20000000 bit); its
# target sets 0x24020007 addiu v0,zero,7 (state 7) and 0x240400AF addiu a0,zero,0xAF (yelp sound)
for at, kicked in ((0xA7EC0, 0xA7F58), (0xA80E4, 0xA8198)):
    assert r32(at) == 0x8E020358 and r32(at + 4) == 0x3C032000 and r32(kicked + 4) == 0x24020007 and r32(kicked + 0x10) == 0x240400AF
# the registration: 0x26090358 addiu t1,s0,0x358; a jal (opcode 3) at 0xA7D4C; then j (opcode 2) at 0xA7D54
# with 0x02002021 move a0,s0 in its delay slot
assert r32(0xA7D28) == 0x26090358 and r32(0xA7D4C) >> 26 == 3 and r32(0xA7D54) >> 26 == 2 and r32(0xA7D58) == 0x02002021
# 0xA7D10 lhu v1,0x16(s0) / 0xA7D14 lhu a0,0x18(s0) (start of the registration) -> b 0xA7CE8 ; move a0,s0
w32(0xA7D10, 0x96030016, b(0xA7D10, 0xA7CE8)); w32(0xA7D14, 0x96040018, 0x02002021)
# 0x14400022 / 0x14400029 = bnez v0 to the two kicked handlers (0xA7F58, 0xA8198) -> nop
w32(0xA7ECC, 0x14400022, 0); w32(0xA80F0, 0x14400029, 0)
# 0x2C43008C sltiu v1,v0,0x8C (140 frames) -> 0x2C4300AA (170 frames)
w32(0xA87F8, 0x2C43008C, 0x2C4300AA)
assert not (set(words) & rel), 'relocated word patched'
open(P, 'wb').write(d)
json.dump(dict(mode='ps1', words={hex(k): [hex(a), hex(v)] for k, (a, v) in sorted(words.items())}), open(REP, 'w'), indent=1)
print(f'dog scene: PS1 (no kick), {len(words)} EBOOT words changed')
