"""A window box without its border, for the band behind the English subtitles (2026-10-05).
`python build.py <tag> --subtitle-background=on` (the default) passes 'on' to this script when English subtitles are
shown; otherwise 'off'.

How the game draws a window box (read from the code and from the primitives of a real frame, save state 10):
  the DECOR op (PSP code 0x381, two bytes: type, margin) stores the type in the window context (+0x7C) and runs the
  type's set-up function from the table at vaddr 0x251BF4; each frame the type's draw function from the table at
  0x251C18 builds the primitives. Types and (set-up, draw):
    0 (0x432B8, 0x435D4)   1 (0x43D70, 0x43ED0: full-screen dim, a plain quad)   2 (0x4414C, 0x435D4: the ordinary box)
    3 (0x434F0, 0x435D4)   4 (0x4414C, 0x435D4: the same as type 2)   5, 6: none   7 (0x434F0, 0x44468)   8 (0x44230, 0x435D4)
  Type 4 is used by no string in the game data or the program (types found: 0, 1, 2, 3, 7, 8) and has the same style
  byte as type 2 (table at segment 1 + 0xCDF8).
  The box draw function 0x435D4 calls 0x444B8 (at 0x4363C) to allocate six primitives: two flat semi-transparent quads
  for the background (context +0x98, +0x9C) and four shaded quads, one pixel thick, for the border (+0xA0..+0xAC; top
  and left 0xF0F0F0 to 0x808080, right and bottom 0x808080), then fills in their corners and links them.
on: the call at 0x4363C is retargeted to new code at the end of segment 2. It calls 0x444B8 as before and then, only
  when the window's type is 4, sets the length byte (+3) of the four border primitives to 0, which makes each an empty
  list node that the frame walker passes over. tools/build_subtitles.py --box gives the subtitle windows type 4, so
  only they lose the border; every other window is type 0, 1, 2, 3, 7 or 8 and is drawn exactly as before.
  The new code is position-independent (the address of 0x444B8 is formed from its own); the retargeted word is a
  relocated jal and stays one.
off: nothing is changed.
Confirmed in play (PPSSPP, 2026-10-05) and by emulating the draw function on a real frame. Runs after patch_subtitles.py on build/eboot/ULJM05030_EBOOT_en.BIN.
Usage: python3 tools/patch_subtitle_box.py on|off     Report: build/eboot/subtitle_box.json"""
import sys, json, struct
MODE = sys.argv[1] if len(sys.argv) > 1 else 'off'; assert MODE in ('on', 'off')
# BASE: file offset of virtual address 0 (code segment); SITE: the call inside the box draw function; ALLOC: its target
P = 'build/eboot/ULJM05030_EBOOT_en.BIN'; BASE = 0x80; REP = 'build/eboot/subtitle_box.json'
SITE, ALLOC, DRAW, TYPE = 0x4363C, 0x444B8, 0x435D4, 4


def code(origin):
    """the hook, placed at vaddr origin. On entry (as 0x444B8): a0 = s0 = window context, a1 = style."""
    here = origin + 16                                       # the address `bal` leaves in ra
    d = ALLOC - here
    w = [0x27BDFFF0,                                         # addiu sp, sp, -16
         0xAFBF0000,                                         # sw    ra, 0(sp)
         0x04110001,                                         # bal   +1          (ra = origin + 16)
         0x00000000,                                         # nop
         0x3C010000 | (((d + 0x8000) >> 16) & 0xFFFF),       # lui   at, hi(ALLOC - here)
         0x24210000 | (d & 0xFFFF),                          # addiu at, at, lo
         0x03E11821,                                         # addu  v1, ra, at  (= ALLOC, wherever the module is loaded)
         0x0060F809,                                         # jalr  v1
         0x00000000,                                         # nop
         0x9203007C,                                         # lbu   v1, 0x7C(s0)   decoration type
         0x24010000 | TYPE,                                  # addiu at, zero, 4
         0x14610009,                                         # bne   v1, at, done
         0x00000000]                                         # nop
    for off in (0xA0, 0xA4, 0xA8, 0xAC):                     # the four border primitives
        w += [0x8E030000 | off,                              # lw    v1, off(s0)
              0xA0600003]                                    # sb    zero, 3(v1)   length 0 = empty list node
    w += [0x8FBF0000,                                        # done: lw ra, 0(sp)
          0x03E00008,                                        # jr    ra
          0x27BD0010]                                        # addiu sp, sp, 16
    assert len(w) == 24 and (w[11] & 0xFFFF) == len(w) - 3 - 12
    return w


def main():
    if MODE == 'off':
        json.dump(dict(mode='off'), open(REP, 'w')); print('subtitle box border: unchanged'); return
    d = bytearray(open(P, 'rb').read())
    phoff, = struct.unpack_from('<I', d, 0x1C); phnum, = struct.unpack_from('<H', d, 0x2C); assert phnum == 3, 'segment 2 expected (run after build_savetext.py)'
    ph = [list(struct.unpack_from('<8I', d, phoff + 32 * k)) for k in range(phnum)]
    r32 = lambda va: struct.unpack_from('<I', d, BASE + va)[0]; jal = lambda to: 0x0C000000 | (to >> 2)
    # Sony's code relocation table (see patch_wide_hud.py): info 4 = a relocated jal
    o = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()[0x325018:0x325018 + 0x9F3D8]
    rel = {struct.unpack_from('<I', o, k)[0]: struct.unpack_from('<I', o, k + 4)[0] for k in range(0, len(o), 8)}
    # identification: the draw function starts addiu sp,sp,-0x20 and has s0 = a0 (0x43608: move s0,a0) before the call;
    # the call's delay slot loads the style byte; the two tables hold the functions named above for types 2 and 4
    assert (r32(DRAW), r32(0x43608), r32(SITE), r32(SITE + 4)) == (0x27BDFFE0, 0x00808021, jal(ALLOC), 0x90C50000), 'box draw function not as expected'
    assert rel.get(SITE) == 4, 'the call is not a relocated jal'
    assert [r32(0x251BF4 + 4 * t) for t in (2, 4)] == [0x4414C] * 2 and [r32(0x251C18 + 4 * t) for t in (2, 4)] == [DRAW] * 2, 'decoration tables not as expected'
    seg2 = bytearray(d[ph[2][1]:ph[2][1] + ph[2][4]])
    while len(seg2) % 4: seg2 += b'\0'
    origin = ph[2][2] + len(seg2); w = code(origin); seg2 += struct.pack(f'<{len(w)}I', *w)
    struct.pack_into('<I', d, BASE + SITE, jal(origin))
    ph[2][6] |= 1                                            # segment 2 holds code (flags + X)
    # write segment 2 back and the program headers after it, as patch_wide_hud.py does
    while len(seg2) % 16: seg2 += b'\0'
    del d[ph[2][1]:]; d += seg2; ph[2][4] = ph[2][5] = len(seg2)
    while len(d) % 4: d += b'\0'
    new_phoff = len(d)
    for p in ph: d += struct.pack('<8I', *p)
    struct.pack_into('<I', d, 0x1C, new_phoff); open(P, 'wb').write(d)
    json.dump(dict(mode='on', type=TYPE, origin=origin, size=4 * len(w), code=struct.pack(f'<{len(w)}I', *w).hex(),
                   words={hex(SITE): [hex(jal(ALLOC)), hex(jal(origin))]}), open(REP, 'w'), indent=1)
    print(f'subtitle box border: {len(w)} words of code at {origin:#x}, 1 call retargeted (window type {TYPE} only)')


if __name__ == '__main__': main()
