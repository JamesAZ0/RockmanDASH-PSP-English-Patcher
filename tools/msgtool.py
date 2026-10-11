"""Dialogue (MSG) format library for Mega Man Legends (PS1, 8-bit text) and Rockman DASH (PSP, 16-bit text).

Used by build_text.py (script conversion), build_sysmsg.py (the EBOOT's system messages are stored in the same
encoding), jpdump.py and the analysis / verify tools. The only file it reads is script/opcode_args_exe.json.
Reference: docs/RESEARCH.md §3 (format and control codes), §2 (containers).

Where the text lives. Each game keeps its dialogue in MSG entries inside the DAT/*.BIN containers; both discs have the
same 129 MSG files under the same paths, and their text blocks correspond index for index (JP/US diff: of 3,752
distinct blocks 3,654 exist on both discs, 95 only in Japanese, 3 only in English). An extracted MSG is its entry:
  0x000  entry header, 0x800 bytes: +0 type (0), +4 data size in bytes, +8 sector count (1 for the header + data
         sectors), +0x0C load address (PS1-style RAM address of the text buffer), +0x40 name "..\\PATH\\NAME.MSG"
  0x800  data: a table of u16 offsets (relative to 0x800), one per block, so offset[0] / 2 = number of blocks; then
         the blocks, each ending in the bytes 00 00. Offsets are 16-bit, so the data cannot exceed 0xFFFF bytes.
The layout is the same on both games; only the contents of the blocks differ.

Block encoding.
  PS1: one byte per unit. A byte below 0x84 is a character (code = glyph cell in the US font KAIFONT); 0x86 (newline)
       and 0xED (choice-cursor slot) are also treated as characters. Any other byte from 0x84 up is a control code
       ("op"), followed by a fixed number of argument bytes.
  PSP: one little-endian u16 per unit. A unit below 0x372 is a character (glyph cell in FONT.BIN: digits, Latin,
       kana, symbols, kanji). A control code is the PS1 code + 0x2EE (OP_SHIFT), so 0x84 -> 0x372 and the newline
       0x86 -> 0x374. Its argument bytes follow as single bytes, exactly as on the PS1; an odd number of them is
       padded with one 00 so the next unit stays 16-bit aligned.
The +0x2EE rule and the padding were found by comparing same-index blocks of the two discs and are confirmed by every
block of both games parsing cleanly (tools/checks/verify_msg_args.py, run by every build) and by play.

Argument lengths (ARGS). The first table came from DashEditor (by OmbraRD); it was replaced by lengths read from the
US executable's text engine (ROCK_NEO.EXE, static analysis: research/opcode_args_from_exe.py ->
script/opcode_args_exe.json), which corrected 39 values. The exceptions further down (E2/E4, EC, B9/CE/E9, the
PSP-only A3/AB/92) were each found from the data of the two discs and checked on every occurrence. A wrong length
is not cosmetic: the surplus bytes become text and the missing ones swallow the next op, which broke menus and
event triggers in early test builds; the comments at each exception say what happened.

Tokens. parse() turns a block into a list of
  ('c', code)        a character; the newline is always ('c', 0x86), on both games
  ('op', op, args)   a control code, op as the PS1 number (PSP units have OP_SHIFT removed), args as raw bytes
tokens_to_psp() also accepts ('raw', psp_code): a PSP character code written out as is (no PS1 -> PSP mapping).
Caveat: because the newline token is ('c', 0x86), a PSP character whose own code is 0x0086 cannot be told apart from
a newline in a token list.

PS1 -> PSP character mapping (tokens_to_psp): letters, digits and basic punctuation have the same codes in both
fonts; the tables below (PS1_TO_PSP_CHAR, PS1_TO_PSP_SEQ) cover the symbols, the space and the PSP control layout."""
import struct
# PSP control code = PS1 control code + OP_SHIFT (0x84 -> 0x372). Found by JP/US diff of the same blocks.
OP_SHIFT = 0x2EE
# Argument bytes per op. This literal is the first table, derived from DashEditor; it is emptied and reloaded from
# script/opcode_args_exe.json further down (kept here as the record of where the work started). None = variable.
ARGS = {0x84:2,0x87:2,0x89:1,0x8A:2,0x8B:2,0x8C:6,0x8D:1,0x8E:2,0x8F:4,0x93:2,0x94:0,0x96:2,0x97:None,
        0x99:2,0x9A:2,0x9B:2,0x9C:4,0x9F:0,0xA0:2,0xA1:0,0xA2:0,0xA4:2,0xA5:10,0xA6:2,0xA7:8,0xA9:0,0xAC:2,
        0xAD:6,0xAE:2,0xAF:1,0xB2:0,0xB3:0,0xB4:0,0xB9:3,0xBA:0,0xBF:2,0xC8:0,0xD0:1,0xD1:2,0xD3:0,0xD4:1,
        0xD6:2,0xD7:4,0xDA:2,0xDB:4,0xDD:4,0xE1:2,0xE3:2}
# Lowest control code on the PS1 (0x84 CLOSE); anything below is a character.
FIRST_OP = 0x84
# Names for the ops whose meaning is known (used by jpdump.py and the reports); the others print as OPxx.
# WIN (0x8C) arguments: x (u16), y (u16), columns, rows of the text window. AUDIO (0x8F): clip, 0, bank, 0.
NAMES = {0x84:'CLOSE',0x86:'NL',0x87:'CLEAR',0x89:'COLOR',0x8B:'PAUSE',0x8C:'WIN',0x8F:'AUDIO',0x93:'DECOR',0x94:'MOVE_FREE',
         0x96:'SEL',0x97:'MULTI',0x9C:'MSG_IF',0x9F:'NEXT',0xA0:'PAD',0xA4:'WAIT',0xA5:'CAM',0xA9:'END'}

def blocks(msg):
    """Split an extracted MSG (0x800 header + data) into its blocks.
    Returns (blocks, offsets): each block's bytes exactly as stored (callers strip the trailing 00 00), and the
    block offsets from the pointer table."""
    # header +4 = data size; the first table entry is the offset of block 0 = 2 * number of blocks
    size = struct.unpack_from('<I', msg, 4)[0]
    d = msg[0x800:0x800+size]
    n = struct.unpack_from('<H', d, 0)[0] // 2
    p = list(struct.unpack_from(f'<{n}H', d, 0)) + [len(d)]
    return [d[p[i]:p[i+1]] for i in range(n)], p[:n]

def parse(block, wide, pad_args=False):
    """Tokenise a block. wide=True for PSP (u16 units), False for PS1 (bytes). Returns (tokens, ok); ok is True
    when the block was consumed exactly to its end (a wrong argument length usually shows up as ok = False).
    pad_args (PSP only): skip the 00 pad after an odd number of argument bytes. The build always passes True for PSP
    data; False reads the arguments with no padding."""
    t=[]; i=0; sel=0   # sel = MULTI choice count (state+0x72 in the US engine), see CHOICE_* below
    # loop while a whole unit is left (2 bytes on PSP, 1 on PS1); the walrus only sets step
    while i + (step if wide else 1) <= len(block) if (step:=2 if wide else 1) else False:
        v = struct.unpack_from('<H', block, i)[0] if wide else block[i]
        i += step
        op = v - OP_SHIFT if wide else v
        # PS1: 0x86 (newline) and 0xED (cursor slot) are characters; PSP: 0x374 (newline) is too
        is_op = (v >= FIRST_OP + OP_SHIFT) if wide else (v >= FIRST_OP and v not in (0x86, 0xED))
        if wide and v == 0x86 + OP_SHIFT: is_op = False
        if not is_op:
            t.append(('c', 0x86 if (wide and v == 0x86+OP_SHIFT) else v)); continue
        n = ARGS.get(op, 0)
        if wide and op in PSP_ARGS: n = PSP_ARGS[op]
        # argument length: the table, a PSP-specific length if there is one, or one of the two variable cases
        if op == 0xD5:   # branch list: bytes up to and including 0xFF terminator (seen in ST05_00E/F 0x6D)
            j = block.find(b'\xff', i); n = (j - i + 1) if j >= 0 else 2
        elif n is None: n = 1 + sel   # MULTI (0x97/0xE8/0xEA/PSP 0xAB): type byte + one byte per choice
        a = block[i:i+n]; i += n
        # keep the running choice count that the next MULTI needs (see CHOICE_* below)
        if op in CHOICE_ADD or (wide and op in PSP_CHOICE_ADD): sel += 1
        if op in CHOICE_SET and a: sel = a[-1] if wide else a[0]   # PSP stores CE/E9 as 00 nn
        if op in CHOICE_RESET: sel = 0
        if wide and pad_args and n % 2: i += 1
        t.append(('op', op, a))
    return t, i == len(block)

# The control codes of a block without its text: used to compare the flow of a Japanese and an English block.
def skeleton(tokens):
    return [(x[1], x[2]) for x in tokens if x[0]=='op']

import json, os
# Authoritative arg table: derived from the US game's text engine (script/opcode_args_exe.json).
_j = os.path.join(os.path.dirname(__file__), '..', 'script', 'opcode_args_exe.json')
_d = json.load(open(_j))['args']
ARGS.clear()
ARGS.update({int(k,16): (v if isinstance(v,int) else None) for k,v in _d.items()})
# Data-derived corrections (2026-09-29): E2 and E4 are selection ops used only in the pause-screen text STFF_FE.MSG
# (blocks 07 and 24); the US scan-pass handler advances 2, but both discs store 4 argument bytes (e.g. E2 02 24 00 1E,
# E4 02 26 04 31). With 1 the English blocks lost 3 bytes to text, and backing out of the Buster Parts screen broke
# the pause menu (seen in play; docs/RESEARCH.md §3).
ARGS.update({0xE2: 4, 0xE4: 4})
# EC (2026-09-29, found with diagnostic builds): the "Original" custom-sort parts list (STFF_FE block 27, its only
# use) ends with
# EC 00 28 on both discs (PS1: EC 00 28 95; PSP: 0x3DA 00 28 0x383). 0x28 is the Sort menu block Back returns to.
# With 1 byte the 0x28 became a text character and Back fell through to block 0 (the pause menu).
# Found by scanning the Japanese PSP data for non-zero pad bytes after odd-length args (only EC and CE show them).
# CE: PS1 'CE 03' vs PSP 'CE 00 03' - a different byte order, not a longer argument; see PS1_TO_PSP_ARGS below.
ARGS.update({0xEC: 2})
# Lengths that apply only when reading PSP data. The last three were inferred from the PSP data alone (the PSP's
# text engine was not disassembled for them).
PSP_ARGS = {0xB9: 4, 0xCE: 2, 0xE9: 2,   # PSP layouts differ from PS1, see PS1_TO_PSP_ARGS (2026-09-29)
            0x92: 1,   # no handler in US exe; appears only in PSP debug text
            0xA3: 2,   # used as a menu-choice op ("Save") in PSP-added menus
            0xAB: None}  # PSP-only MULTI variant (type byte + one per choice)

# MULTI choice count, from the US text engine (ROCK_NEO.EXE, 2026-09-29; research/multi_choice_count.py).
# MULTI's scan pass (0x80055304) skips 2 + count bytes, count = state+0x72. 0xED is only a 12-px blank (0x8005A858)
# and does NOT count (the first rule here counted 0xED characters and swallowed the op after MULTI in 28 English
# blocks, e.g. the event trigger 9A 0F06 in ST00_02 block 04: the tutorial Reaverbot never dropped).
# The Japanese text, which marks each choice with one circle glyph, parses identically under this rule.
CHOICE_ADD = {0x96, 0xAD, 0xB7, 0xD7, 0xDD}        # +1 (SEL etc.)
CHOICE_SET = {0xCE, 0xE9}                          # count = first arg byte
CHOICE_RESET = {0x87, 0x97, 0xE8, 0xEA, 0xAB, 0x9D, 0xB5, 0xB8, 0xBE, 0xBF, 0xD5, 0xC2, 0xC3, 0xCA, 0xE6}  # count = 0
PSP_CHOICE_ADD = {0xA3}                            # PSP-only save-menu choice

# PS1 character code -> PSP character code, for the codes that differ (everything else keeps its number).
# 0xED: choice-cursor slot. The US draw pass advances 12 px without drawing (ROCK_NEO.EXE 0x8005A858), leaving room
# for the hand cursor; 0x10C is an empty PSP glyph that keeps the default 12 px advance. (The Japanese script puts
# the circle glyph 0xFD there; with it the English "Yes No" showed a stray circle.)
PS1_TO_PSP_CHAR = {0xED: 0x10C,           # choice-cursor slot: US draw pass advances 12 px WITHOUT drawing (ROCK_NEO.EXE 0x8005A858); 0x10C is an empty 12 px PSP glyph (was 0xFD = visible circle, fixed 2026-09-28)
                   0x86: 0x86 + OP_SHIFT}   # newline (PSP 0x0374) - fixed 2026-09-28, was emitted as 0x0086
# Symbol remap (project decision 2026-09-28: use the Japanese font's own glyphs to keep its style).
# The PSP font holds the same symbol set, in the same order, at 0xFD-0x10B:
# CIRCLE TRIANGLE CROSS SQUARE L1 L2 R1 R2 , " . ... HAND + %   (English PS1 codes 0x54-0x62)
for _c in range(0x54, 0x63): PS1_TO_PSP_CHAR[_c] = _c + 0xA9
# alpha, omega, ';', '=' : glyphs copied from the PS1 English font into empty PSP cells (tools/build_font.py)
PS1_TO_PSP_CHAR.update({0x80: 0x10D, 0x81: 0x10E, 0x82: 0x10F, 0x83: 0x1A5})
# English space -> its own empty cell 0x1A6 (5 px in the VWF table). 0x4F stays the Japanese full-width space (12 px):
# the text engine builds menu cursors from 0x4F spaces + the hand glyph, and the key-item grid cursor moved too little
# while 0x4F was 5 px (seen in play, 2026-09-29). Widths: tools/patch_eboot.py.
PS1_TO_PSP_CHAR[0x4F] = 0x1A6
# PSP control layout (project decision 2026-09-28; a formatting change, so it carries no "R*" review marker - see
# build_text.py):
# the PSP has no R2. The Japanese PSP script writes the R2 action as "L button + R button" using the
# plain letters L and R, so the English R2 icon (PS1 0x5B) is written as the three glyphs "L+R".
# L1/L2/R1 (0x58-0x5A) never occur in the English dialogue (research/button_refs.py); L1 and R1 do occur
# in two of the EBOOT's options help lines. 0x20 / 0x26 are the plain letters L / R, 0x10A the font's '+'.
PS1_TO_PSP_SEQ = {0x5B: (0x20, 0x10A, 0x26),   # R2 -> 'L', '+' (JP font), 'R'
                  0x58: (0x20,), 0x5A: (0x26,)}  # L1 -> 'L', R1 -> 'R' (project decision 2026-09-29)

FACE_BUTTONS = range(0x54, 0x58)       # PS1 circle, triangle, cross, square icons
PSP_BUTTON_COLOR = b'\x05'              # the Japanese PSP text wraps every face-button icon in COLOR 05
def psp_button_colors(t):
    """PS1 English colours the face buttons like a PlayStation pad (COLOR 02 circle red, 03 triangle green, 04 cross
    blue, 05 square pink). The PSP has no coloured buttons and its own text uses COLOR 05 for all of them
    (project decision 2026-09-29): COLOR n, icon, COLOR 00  ->  COLOR 05, icon, COLOR 00.
    COLOR is op 0x89 with one argument byte."""
    t = list(t)
    for k in range(1, len(t) - 1):
        if (t[k][0] == 'c' and t[k][1] in FACE_BUTTONS and t[k-1][0] == 'op' and t[k-1][1] == 0x89
                and t[k+1][0] == 'op' and t[k+1][1] == 0x89 and t[k+1][2] == b'\x00'):
            t[k-1] = ('op', 0x89, PSP_BUTTON_COLOR)
    return t

# Ops whose PSP argument layout is not "PS1 bytes + trailing pad" (2026-09-29; found by scanning the Japanese data for
# non-zero pad bytes, then checked against every aligned PS1/PSP occurrence: B9 141, CE 8, E9 3, all consistent):
#   B9 (after a choice menu: "choice a -> jump to block"): PS1  a b c   -> PSP  a 00 b c
#   CE / E9 (set the choice count):                           PS1  n       -> PSP  00 n
# Before this fix the English wrote B9 as a b c 00 and CE as n 00 (57 B9 in 11 shipped stage files, 4 CE in ST08_03/04).
PS1_TO_PSP_ARGS = {0xB9: lambda a: a[:1] + b'\0' + a[1:], 0xCE: lambda a: b'\0' + a, 0xE9: lambda a: b'\0' + a}

def tokens_to_psp(t):
    """Encode a token list to PSP bytes. Char tokens: ('c', ps1_code) or ('raw', psp_code).
    Ops get OP_SHIFT added; their arguments are copied, re-laid for B9/CE/E9, and padded to an even length."""
    t = psp_button_colors(t)
    out = bytearray()
    for x in t:
        if x[0] == 'c':
            for _v in PS1_TO_PSP_SEQ.get(x[1], (PS1_TO_PSP_CHAR.get(x[1], x[1]),)):
                out += struct.pack('<H', _v)
        elif x[0] == 'raw':
            out += struct.pack('<H', x[1])
        else:
            # re-lay B9/CE/E9 only when the arguments still have the PS1 length (ops taken from a Japanese PSP block are
            # already in the PSP layout)
            a = PS1_TO_PSP_ARGS[x[1]](x[2]) if x[1] in PS1_TO_PSP_ARGS and len(x[2]) == ARGS.get(x[1]) else x[2]
            out += struct.pack('<H', x[1] + OP_SHIFT) + a
            if len(a) % 2: out += b'\0'
    return bytes(out)

def ps1_block_to_psp(block):
    """Convert one English PS1 block (without 0000 terminator) to PSP 16-bit form."""
    t, ok = parse(block, False)
    if not ok: raise ValueError('PS1 block did not parse cleanly')
    return tokens_to_psp(t)

def build_msg(header, blocks_bytes):
    """Rebuild a MSG file: 0x800 header (size field patched) + u16 pointer table + blocks each ending 0000.
    header: the original entry's header (the Japanese file's), which carries the name and the load address.
    The sector count at +8 is 1 + ceil(size / 0x800); the rule holds for all 129 Japanese MSG headers."""
    n = len(blocks_bytes); tbl = bytearray(); body = bytearray(); off = n*2
    for b in blocks_bytes:
        tbl += struct.pack('<H', off + len(body)); body += b + b'\0\0'
    data = bytes(tbl + body)
    if len(data) > 0xFFFF: raise ValueError('MSG too large for u16 pointers')
    h = bytearray(header[:0x800]); struct.pack_into('<I', h, 4, len(data))
    struct.pack_into('<I', h, 8, 1 + (len(data) + 0x7FF) // 0x800)   # sector count incl. header
    pad = (-len(data)) % 0x800
    return bytes(h) + data + b'\0'*pad
