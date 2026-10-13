# Rockman DASH (PSP) English build: technical research reference

This document records what was learned, by reverse engineering, about the Japanese PSP game
**Rockman DASH: Hagane no Boukenshin** (ULJM05030, v1.01) and the US PS1 game **Mega Man Legends**,
and how the build scripts in `tools/` use each finding. It is written so that every claim can be
re-checked against the two disc images.

## Contents

1. [Overview and ground rules](#1-overview-and-ground-rules)
2. [Disc layout and data containers](#2-disc-layout-and-data-containers-bin-files-entry-headers-tim-textures)
3. [Dialogue (MSG) format and control codes](#3-dialogue-msg-format-and-control-codes)
4. [Text rendering and the font](#4-text-rendering-and-the-font)
5. [The program (EBOOT)](#5-the-program-eboot-layout-segments-relocations-flattening)
6. [Text buffers and memory moves](#6-text-buffers-and-memory-moves)
7. [System messages, menus, save-screen text, PARAM.SFO](#7-system-messages-menus-save-screen-text-paramsfo)
8. [Title screen](#8-title-screen)
9. [Texture swaps](#9-texture-swaps)
10. [Voices and audio](#10-voices-and-audio)
11. [Subtitles](#11-subtitles)
12. [The dog scene (native stage code)](#12-the-dog-scene-native-stage-code)
13. [The renderer and the wide-screen HUD fix](#13-the-renderer-and-the-wide-screen-hud-fix)
14. [PSP menu and save data](#14-psp-menu-and-save-data-icon-save-picture)
15. [Packing the ISO and the checks](#15-packing-the-iso-and-the-checks)
16. [Open questions and unverified points](#16-open-questions-and-unverified-points)

---

## 1. Overview and ground rules

### 1.1 What the build does

The build takes the user's own two disc images and produces an English PSP ISO:

| Input | Used for |
|---|---|
| Mega Man Legends (USA), PS1, Track 1 (MODE2/2352 `.bin`) | English script, English voice audio, English textures, the US executable `ROCK_NEO.EXE` (system strings, sprite lists, text-engine analysis) |
| Rockman DASH (Japan), PSP ISO, PSN release or retail UMD dump | The base image. It is copied byte for byte and then patched in place. |

Command line (current options):

```
python build.py <tag> [iso] --localization=text|audio|legends --hud=off|center|edge
                            --paprika=good-dog|fair-game --subtitles=on|off
                            --subtitle-language=en|jp
```

| Option | Values (default in bold) | Effect | Section |
|---|---|---|---|
| `--localization` | `text` | English text and text-bearing textures; Japanese voices; PSP title screen; PSP menu name and save name stay "Rockman DASH…" | 3, 7, 9 |
| | `audio` | `text` plus all English audio from the PS1 disc | 10 |
| | **`legends`** | `audio` plus the PS1 title screen, the "Mega Man Legends" menu name / save name / pictures, and the US name-and-artwork textures | 8, 9, 14 |
| `--hud` | `off`, `center`, **`edge`** | HUD, window and text proportions in the Wide screen mode | 13 |
| `--paprika` | `good-dog`, **`fair-game`** | The lamp-post dog scene: US behaviour (no kick) or the Japanese behaviour (talk or kick) | 12 |
| `--subtitles` | **`on`**, `off` | The PSP's voiced-scene subtitles | 11 |
| `--subtitle-language` | **`en`**, `jp` | English subtitles (at English-clip timings) or the original Japanese ones | 11 |

Internally `build.py` maps these to per-tool arguments: `text` = (audio jp, title psp, menu original),
`audio` = (en, psp, original), `legends` = (en, ps1, localized); `--hud=edge` is passed to
`patch_wide_hud.py` as `edges`; `good-dog` is passed to `patch_ps1_dog.py` as `ps1`, `fair-game` as `jp`.

### 1.2 Ground rules of the project

- **Only lines from the PS1 English script may be saved as game text.** Anything else (a translation of a
  PSP-only line, an edited line) needs a project decision. Such lines normally carry the review marker
  `R*` at the start of the displayed text; approved exceptions without the marker are recorded in the rule
  files under `script/`.
- **Formatting changes** (line breaks, box sizes, layout, button names) also need a project decision.
- **The original images are never modified.** Nothing from the game is distributed: textures, glyphs,
  audio and the program are all taken from the user's images at build time.
- **Saves must stay compatible with the unmodified Japanese release** (project decision 2026-09-30).
- Symbols are mapped to the **Japanese font's own glyphs** to keep its style (project decision 2026-09-28).
- Button references follow the **PSP control layout** as the Japanese PSP script writes it
  (project decision 2026-09-28); this is treated as formatting and carries no marker.

### 1.3 Conventions used in this document

- **vaddr / "va"**: a virtual address inside the PSP program (ELF). For the code segment,
  `file offset = vaddr + 0x80`.
- **Segment 1** is the data segment, at vaddr `0x245200`. See §5.3 for the most important pitfall:
  *code immediates that reference data are relative to segment 1's address, not absolute*.
- **PS1 address**: an address of the form `0x80xxxxxx` in the emulated PS1 RAM (§6.1) or in `ROCK_NEO.EXE`.
  In the US executable, `file offset = address − 0x80010000 + 0x800`.
- **Confidence** labels:
  - **confirmed in play**: seen working in the emulator (PPSSPP 1.20) and/or on hardware (PSP Go, custom firmware ARK-5);
  - **confirmed by check**: verified by a script against the disc images or by a build-time check;
  - **inferred**: follows from static analysis or data comparison, not separately tested.
- Hex numbers are written `0x…`; MSG control codes are written with their **PS1** value (`8C`, `97`, …).

### 1.4 Input identification

`tools/inputs.py` identifies the PSP image from its contents, not its name: `PARAM.SFO` `DISC_ID` must be
`ULJM05030`; `SYSDIR/BOOT.BIN` all zero means the PSN release, otherwise a retail UMD.

| CRC32 of the whole image | Image | Size |
|---|---|---|
| `C2E6D0B9` | PSN release | 316,735,488 bytes |
| `78DFD145` | Retail UMD, full size | 316,735,488 bytes |
| `17F6EDE5` | Retail UMD, known underdump (last, empty sector missing) | 316,733,440 bytes |

The PSN release and the UMD hold the same 1,176 files at the same disc positions. `EBOOT.BIN` and every
`DAT` file are byte-identical. They differ only in `SYSDIR/BOOT.BIN` and `SYSDIR/UPDATE/{DATA.BIN, EBOOT.BIN,
PARAM.SFO}`, which are zero-filled on the PSN release (confirmed by check: file-by-file comparison). The
one-sector-short UMD dump needs no special handling because the packer rounds the image end up to 16
sectors (154,656 in both cases).

The PS1 Track 1 SHA-1 `904489e2e8d06e1c44e60d8925329f9472b2d037` matches the Redump image.

---

## 2. Disc layout and data containers (BIN files, entry headers, TIM textures)

### 2.1 The PSP port is a near 1:1 port of the PS1 data

| Fact | Value | How established |
|---|---|---|
| PS1 data files | `CDDATA/DAT/*.BIN`, 205 files | directory listing |
| PSP data files | `PSP_GAME/USRDIR/DAT/*.BIN`, 204 files, same names | directory listing |
| Only PS1 file with no PSP counterpart | `KAIFONT.BIN` (the US English font, §4.3) | directory listing |
| Byte-identical BINs (US PS1 vs JP PSP) | 24 | file comparison |
| Dialogue files | 129 `.MSG` entries on each disc, same paths | container scan |
| Container TIM textures | 1,849 on the PSP, 1,850 on the PS1 | `research/tex_compare.py` |
| PS1 voice audio | `CDDATA/XA/XA18xxE.XA`, 36 files (interleaved XA-ADPCM); `XA37S00E/01E` streams | §10 |
| PSP voice audio | `DAT/at3/xa18mNN/<name>.at3` and `DAT/at3/xa37s00/` | §10 |

STG, HED, IDX, MDT and PBD entries are identical between the discs; most TIMs are identical.

### 2.2 The game reads data files by disc position

**Fact.** The PSP program holds its own table of the `DAT/*.BIN` files and reads each file by the LBA and
size in that table, not through the ISO directory.

| Item | Value |
|---|---|
| Table location | file offset `0x247A54` (vaddr `0x2479D4`) in the plain program |
| Entries | 204, one per `DAT/*.BIN` |
| Entry layout | `u32 LBA, u32 size in bytes, u32 0` (12 bytes) |

**How established (in-game tests).**

| Test | Result | Conclusion |
|---|---|---|
| ISO rebuilt with a generic ISO library (1,175 of 1,176 files moved) | hangs at the first "Now Loading…" | |
| The *unmodified Japanese* game rebuilt the same way | hangs at the same place | the layout itself matters |
| Original image copied, changed BINs overwritten at the same LBA, some grown by 1–5 sectors | gets further, hangs after the first cutscene | grown tails are not read |
| Same, only BINs whose sector count is unchanged | plays | |
| Same as the third, with the table's sizes updated | plays | the table gives the size |
| BINs moved to the end of the image with LBA and size updated in the table | plays | the table gives the position |

Every table entry starts exactly at a file; the program contains no `sce_lbn` raw-sector paths
(confirmed by check). `research/eboot_findings.py` re-finds the table by matching it against the ISO
directory. **Used by:** `tools/pack_inplace.py` (`FT_OFF`, `FT_N`). **Confidence:** confirmed in play.

Files that are opened **by path** and may therefore move freely: `SYSDIR/EBOOT.BIN` (opened by the firmware)
and every `.at3` audio file (the program holds `disc0:/PSP_GAME/USRDIR/DAT/at3/...` path strings, §10.2).
Confirmed in play: the relocated program and relocated audio files work.

### 2.3 Space on the disc

| Item | Value |
|---|---|
| Original image | 154,656 sectors of 2,048 bytes |
| `EBOOT.BIN` | at LBA 80, 4,163,232 bytes; next file at LBA 2128, so its slot is 4,194,304 bytes (31,072 bytes spare) |
| Unused sectors inside the original PSN image | 28,278 (about 55 MB), all zero |
| Largest unused runs | 22.2 MB at LBA 11262 (after `UPDATE/DATA.BIN`), 11.5 MB at LBA 26124 (after `DAT/PICT/emptypic.png`), 4.5 MB at LBA 3941 (after `UPDATE/EBOOT.BIN`) |

The three large runs look like mastering padding. No directory record and no file-table entry points into
them. They are **not used** by the build (project decision 2026-09-30); see §15.2 for where moved files go.

### 2.4 Container (`.BIN`) format

A data file is a sequence of **entries**. Each entry is a 0x800-byte header followed by data padded to a
0x800 boundary. The format is the same on both discs. Layout knowledge comes from DashEditor (a third-party
Mega Man Legends toolkit) and was re-implemented and checked here.

Header fields common to all entry types:

| Offset | Size | Meaning |
|---|---|---|
| +0x00 | u32 | Entry type. Seen: 0 = MSG, 1 = TIM texture, 3 = font (`font.dat`), 5 = VAB sound bank, 10 = palette-only texture twin (§2.6). `0xFFFFFFFF` in the type position marks the end of a file's entry list. |
| +0x04 | u32 | Size in bytes (meaning depends on type, see below) |
| +0x08 | u32 | Sector count (meaning depends on type, see below) |
| +0x0C | u32 | Load address in PS1-style RAM for loadable entries (e.g. `0x80157000` for a stage MSG) |
| +0x40 | 64 bytes | Entry path, NUL-terminated, always starting `..\` (e.g. `..\BG\CHAR\NTITLE2.TIM`) |

The scripts find entries by stepping in 0x800-byte units and testing for `..\` at +0x40.

Per-type details:

| Type | +0x04 size | +0x08 sectors | Other fields |
|---|---|---|---|
| MSG (0) | data bytes | `1 + ceil(size / 0x800)` (header included). Rule verified on all 129 Japanese MSG headers. | +0x0C load address |
| TIM (1) | pixel bytes + palette bytes + 0x20 | **one more** than the entry's on-disc extent (holds for every TIM on both discs) | see §2.5 |
| VAB (5) | VAB header size + body size | `1 + sectors(VAB header) + sectors(body)` (checked on all 6 banks examined) | +0x14 SPU address, +0x18 VAB header size (§10.7) |

Load regions seen in the headers of stage files (from `research/memory_map.py`):

| Entry type | Load address |
|---|---|
| HED | `0x8013E000` |
| MSG (stage dialogue) | `0x80157000` |
| IDX | `0x8015C000` |
| MDT | `0x80164000` |
| EBD | `0x8016C000` |
| STG | `0x80194000` (largest end `0x801B4E28`) |
| SUPPORT: `r3_sup.bin` | `0x801D8000` |
| SUPPORT / SUPPORT2: `STFF_FD.MSG` | `0x801E4000` |
| SUPPORT: EBD | `0x801F2000` |
| SUB_KEY / SUB_WPN: `STFF_FE.MSG` | `0x801F2000` |

Of the 129 MSG entries, 125 load at `0x80157000`, 2 at `0x801E4000` and 2 at `0x801F2000`.

### 2.5 TIM texture entries

| Header offset | Meaning | Example (`NTITLE3U.TIM`, PS1) |
|---|---|---|
| +0x04 | size = pixels + palettes + 0x20 | `0x7A20` = 0x7800 + 0x200 + 0x20 |
| +0x08 | sector field (one more than the extent) | 17 (the entry occupies 16 sectors) |
| +0x10 | CLUT row in VRAM | `0x1F2` |
| +0x14 | colours per palette (16 or 256) | `0x100` |
| +0x18 | number of palettes (CLUTs) | 1 |
| +0x1C | VRAM x | `0x240` |
| +0x20 | VRAM y | `0x100` |
| +0x24 | width in 16-bit units (bytes per row = 2 × this) | `0x60` (192 bytes) |
| +0x28 | height in rows | `0xA0` |
| +0x100… | the palettes, 15-bit colours + bit 15 = semi-transparency flag | |

Pixel data follows the header and is stored in **blocks of 64 × 32 bytes**, block rows first: for each band
of 32 rows, for each 64-byte column strip, 32 rows of 64 bytes. `build_title.py` (`blocks`, `to_idx`,
`from_idx`) and `build_ps1_title.py` (`unswizzle`) implement both directions; the round trip is asserted
against the original data.

> **Pitfall: the size field counts palette bytes that live in the header.**
> The data area after the header holds only `width × height` pixel bytes; the next entry's header follows
> immediately. Copying `size` bytes from a PS1 texture therefore runs into the following header. This was
> done once: the weapon-screen texture `SUB02` (size `0x8120` = `0x8000` pixels + `0x120`) overwrote the
> first `0x120` bytes of the following `STFF_FE.MSG` header with the PS1's size and sector count, and the
> weapon screen hung on "Now Loading…". The texture builders now write pixel bytes only, the packer asserts
> that no replacement reaches a following header, and `verify_headers.py` compares every header with the
> original. **Confidence:** confirmed in play (failure and fix).

### 2.6 Palette-only twins (type 10)

Some textures have a second entry with the **same name**, type 10, a header with palettes and **no data**
(`GAUGE01.TIM` has one in each of the four BINs that carry it). It is used to reload the palettes. The packer
gives it the swapped palettes too and never writes pixels into it. Restricting data writes to "type 1 only"
would be wrong because the font is type 3; the rule is "not type 10". **Confidence:** confirmed by check
(read back from the built image) and in play (banner colours).

---

## 3. Dialogue (MSG) format and control codes

### 3.1 File structure

An MSG entry's data is:

1. a table of `u16` offsets, one per **block** (the first offset divided by 2 is the number of blocks);
2. the blocks. In built files each block ends with a `0x0000` terminator.

Block numbers are the indices into this table and are written in hex in this document (block `0xDC`).
`tools/msgtool.py`: `blocks()` splits a file, `build_msg()` rebuilds one (offsets, size field at +4, sector
count at +8) and refuses data above `0xFFFF` bytes because the offsets are 16-bit.

### 3.2 PS1 (8-bit) versus PSP (16-bit) encoding

| | PS1 (US) | PSP (JP) |
|---|---|---|
| Unit | 1 byte | `u16`, little-endian |
| Characters | `< 0x84` | `< 0x372` (the renderer's glyph test is `sltiu …, 0x372`) |
| Control codes | `0x84 … 0xED` | **PS1 code + `0x2EE`** (so `0x372 …`) |
| Newline | `0x86` (a glyph code, not an op) | `0x0374` (= `0x86 + 0x2EE`) |
| Arguments | bytes | the same bytes, unchanged; **an odd number of argument bytes is followed by one `0x00` pad byte** |

**How established.** By comparing aligned Japanese PS1/PSP data and by parsing every block: with the rules
below all 17,821 Japanese PSP blocks and all 17,594 US PS1 blocks parse cleanly to their end.
**Confidence:** confirmed by check (`verify_msg_args.py` step 2) and in play.

Block alignment between the discs is **index for index**: of 3,752 unique blocks, 3,654 have text on both
sides, 95 have Japanese text only and 3 English only (§3.7).

### 3.3 Argument lengths

The argument length of each control code was derived from the **US executable's text engine**
(`research/opcode_args_from_exe.py`, result in `script/opcode_args_exe.json`).

How: `ROCK_NEO.EXE` runs the text engine at `0x80053CD4`. Bytes `0x84–0xED` dispatch through two handler
tables indexed by `byte × 4`:

| Table | Address | Pass | Text pointer field |
|---|---|---|---|
| A | `0x8008A91C` | draw pass | state + `0x6C` |
| B | `0x8008AAC4` | scan pass | state + `0x14` |

For each handler, the constant added to the text pointer before it is stored back is `1 + argument bytes`.
Handlers that push a return address or loop were resolved by hand (listed as `MANUAL` in the tool). This
corrected 39 values of an earlier table taken from DashEditor.

Argument bytes per code (PS1 values, from `script/opcode_args_exe.json`):

| Bytes | Codes |
|---|---|
| 0 | 91 94 95 98 9F A1 A2 A8 A9 B2 B3 B4 BA BD C0 C1 C5 C6 C7 C8 CB CC CF D2 D3 D9 DC DF E0 ED |
| 1 | 89 8D 90 A3 AF B0 B1 BC C4 C9 CE D0 D1 D8 E2\* E4\* E6 E7 E9 EC\* |
| 2 | 84 87 8A 8B 8E 93 96 99 9A 9B 9D A0 A4 AC AE B6 B7 BF C2 CD D5\*\* D6 DA DE E1 E3 E5 |
| 3 | B9 C3 |
| 4 | 8F 9C A6 B5 BB D4 D7 DB DD EB |
| 6 | 8C AD B8 BE |
| 8 | A7 CA |
| 10 | A5 |
| variable | 97 E8 EA (choice menus, §3.5) |

\* overridden from the data, see §3.4. \*\* `D5` is parsed as a branch list: bytes up to and including a
`0xFF` terminator (seen in `ST05_00E`/`F` block `0x6D`).

Codes with known meaning:

| Code | Name | Arguments / meaning |
|---|---|---|
| 84 | CLOSE | closes the window; also ends a system string |
| 86 | NL | newline (a character code, not an op) |
| 87 | CLEAR | clears the page; resets the choice count |
| 89 | COLOR | 1 byte: colour number |
| 8A | (unnamed) | 2 bytes; every subtitle string starts `8A 00 00` and ends `8A 01 00` |
| 8B | PAUSE | 2 bytes |
| 8C | WIN | 6 bytes: `u16 x, u16 y, u8 columns, u8 rows` (e.g. `48 00 DE 00 0F 01` = x 72, y 222, 15 columns, 1 row) |
| 8F | AUDIO | 4 bytes: `clip, 0, bank, 0` (§10) |
| 90 / 91 | call / return | 90 pushes a return address (1 byte); 91 pops it. 91 ends a system string. |
| 93 | DECOR | 2 bytes; window decoration; the review marker is inserted right after the first DECOR |
| 95 | (end) | ends a system or subtitle string |
| 96 | SEL | 2 bytes; one choice; adds 1 to the choice count |
| 97 | MULTI | choice menu, variable (§3.5) |
| 99 | (unnamed) | 2 bytes; seen in menu flow with a block number (e.g. `99 02 26` in the Sort menu) |
| 9A | (event) | 2 bytes; starts a stage event (e.g. `9A 0F 06` starts event `0x0F`) |
| 9C | MSG_IF | 4 bytes |
| 9F | NEXT | page break (wait for button) |
| A0 | PAD | 2 bytes: `u16` pixels of horizontal padding |
| A4 | WAIT | 2 bytes |
| A5 | CAM | 10 bytes |
| A9 | END | end of block |
| AD | (option row) | adds 1 to the choice count; see §7.3 for its PSP form |
| AF | (row start) | 1 byte; the engine's x position restarts here (used by the options layout, §7.3) |
| B9 | (choice jump) | "if choice *a* was picked, go to block *bc*" (§3.4) |
| BF | JUMP | 2 bytes |
| CE, E9 | (set choice count) | 1 byte: the count (§3.4) |
| ED | (cursor slot) | PS1 only: advances 12 px without drawing (§3.6) |

### 3.4 Codes whose stored arguments differ from the handler-derived length or from the PS1 layout

These were all found from the **data**, and each was a real bug before it was found.

| Code | Rule | Evidence | Symptom before the fix (confirmed in play) |
|---|---|---|---|
| E2, E4 | 4 argument bytes on both discs (the US scan-pass handler advances only 2) | `E2 02 24 00 1E` (block `0x07`) and `E4 02 26 04 31` (block `0x24`) of `STFF_FE.MSG`, their only uses; the Japanese PSP data shows `u16 op`, 4 bytes, then the `95` end op | Backing out of the Buster Parts screen broke the menu: 3 argument bytes became text |
| EC | 2 argument bytes | `EC 00 28 95` on PS1 and `EC 00 28` + end op on PSP, block `0x27` of `STFF_FE.MSG` (the "Original" custom-sort list), its only use. `0x28` is the Sort-menu block that Back returns to. | Sort → Original → Back fell through to block 0 (the pause menu) |
| B9 | PS1 `a b c` → PSP `a 00 b c` (4 bytes) | every aligned PS1/PSP occurrence (141) | Choice replies jumped to the wrong block |
| CE, E9 | PS1 `n` → PSP `00 n` (2 bytes) | every aligned occurrence (CE 8, E9 3) | Wrong choice count (name entry in `ST08_03`/`04`) |
| A3 | PSP-only use: 2 argument bytes; marks a choice (adds to the choice count) | Japanese PSP data | see §3.8 |
| AB | PSP-only MULTI variant (type byte + one byte per choice) | Japanese PSP data | see §3.8 |
| 92 | PSP: 1 argument byte | no handler in the US executable; appears only in PSP debug text | none |

**Detection method that generalises:** in the Japanese PSP data an odd-length argument is followed by a pad
byte that must be zero. A non-zero "pad" means the code really has one more argument byte. A full scan with
the final table finds none (`verify_msg_args.py` step 1). The first version of this scan stopped at each
block's first MULTI and so missed B9/CE/E9; the scan must cover whole blocks.

**Used by:** `tools/msgtool.py` (`ARGS.update`, `PSP_ARGS`, `PS1_TO_PSP_ARGS`). **Confidence:** confirmed in
play for E2/E4, EC, B9/CE/E9; confirmed by check for all (step 3: every English block using
E2/E4/EC/B9/CE/E9 has exactly the Japanese block's arguments).

### 3.5 Choice menus (MULTI) and the choice count

MULTI (`97`, also `E8`, `EA`, and PSP `AB`) takes **a type byte plus one byte per choice**. The number of
choices is engine state, not something visible in the op itself.

From the US executable (`research/multi_choice_count.py`): the MULTI scan-pass handler at
`0x80055304` advances by `2 + count`, where `count` is the byte at state + `0x72`.

| Effect on the count | Codes |
|---|---|
| +1 | `96` SEL (handler `0x80054BE0`), `AD`, `B7`, `D7`, `DD`; on the PSP also `A3` |
| = first argument byte (PSP: the last of its two bytes) | `CE`, `E9` |
| = 0 | `87` CLEAR, MULTI itself (`97`, `E8`, `EA`, `AB`), `9D`, `B5`, `B8`, `BE`, `BF`, `D5`, `C2`, `C3`, `CA`, `E6` |

> **Pitfall: do not count cursor-slot glyphs.** An earlier rule sized MULTI as "1 + number of `ED`
> characters". English choices are sometimes written with more `ED` slots than choices
> (`{ED}Yes{ED}{ED}No`), so the parser swallowed the op after MULTI. In `ST00_02` block `0x04` that op was
> `9A 0F 06`, the event that drops the tutorial Reaverbot; it never dropped. 28 PS1 blocks were affected.
> The Japanese text marks each choice with exactly one circle glyph, so it parses identically under both
> rules, which makes it an independent check of the engine-derived rule.

**Confidence:** confirmed in play (Reaverbot drop, Flutter travel prompts in `ST03_06` blocks `0x17`/`0x20`).

### 3.6 Characters and symbol mapping

English PS1 character codes are used unchanged as PSP glyph codes for digits and Latin letters (the PSP font
has Latin capitals from `0x15` and lower case from `0x30`). The exceptions (`msgtool.PS1_TO_PSP_CHAR`,
`PS1_TO_PSP_SEQ`):

| PS1 code | Meaning | PSP code(s) | Reason |
|---|---|---|---|
| `0x54–0x62` | ○ △ × □ L1 L2 R1 R2 `,` `"` `.` `…` hand `+` `%` | `0xFD–0x10B` (PS1 + `0xA9`) | The Japanese font holds the same symbol set in the same order. Without the map these codes land on hiragana. |
| `0x4F` | space | `0x1A6` | A separate empty cell with a 5-px advance. `0x4F` must stay 12 px (§4.4). |
| `0x80–0x83` | α Ω `;` `=` | `0x10D`, `0x10E`, `0x10F`, `0x1A5` | Glyphs copied from the US font into empty cells (§4.3) |
| `0x86` | newline | `0x0374` | |
| `0xED` | choice-cursor slot | `0x10C` | In the US game `ED` is not a glyph: its draw-pass handler (`0x8005A858`) advances x by 12 px without drawing. `0x10C` is an empty PSP glyph with the default 12-px advance. Mapping it to the circle `0xFD` (as the Japanese text does) showed a stray circle before "No". |
| `0x5B` | R2 icon | `0x20`, `0x10A`, `0x26` = `L`, `+`, `R` | PSP control layout (below) |
| `0x58`, `0x5A` | L1, R1 icons | `0x20` (`L`), `0x26` (`R`) | PSP control layout; used only in two system strings |

**PSP control layout** (project decision 2026-09-28): the PSP has no R2. The Japanese PSP script writes the
R2 action as "hold L and press R" with the plain letters. In the English script only R2 occurs (15 blocks,
5 distinct lines; L1, L2 and R1 never occur in dialogue), and it is written as the three glyphs `L+R` with no
other word changed. `research/button_refs.py` lists the affected blocks.

**Confirm and cancel** (2026-10-06, under the same decision): on three screens the US text names the PS1 buttons,
cross to confirm and triangle to cancel, while the PSP uses circle to confirm and cross to cancel and the Japanese
PSP text of the same blocks says so: name entry at the TV station minigames (`st08_03.msg` blocks `1C`, `24`), name
entry in `st05_00.msg` / `st05_fe.msg` block `02`, and the donation amount in `st06_01.msg` / `st06_04.msg` block
`72` (11 blocks in all). `script/text_edits.json` (`confirm-cancel-buttons`) swaps only the two icons. Found by
comparing the face-button icons of every English block with the Japanese block at the same position; no other block
differs (the circles that only the Japanese text has are its choice cursors). The minigame's own instructions
(triangle and square to kick, circle to walk) are the same in both.

**Face-button colours** (project decision 2026-09-29): the US script wraps each face-button icon as
`COLOR n`, icon, `COLOR 00` with n = 02 (circle), 03 (triangle), 04 (cross), 05 (square), the PlayStation pad
colours. The Japanese PSP text uses `COLOR 05` for all of them. `msgtool.psp_button_colors` rewrites the
leading COLOR to 05.

The character table for text that the project itself encodes (rule files, the marker) is
`script/ps1_charmap.tbl`: which glyph number of the US font is which character (109 entries, compiled with reference to
DashEditor's table). The bulk of the script does not go through it: PS1 blocks are converted from their
original bytes.

### 3.7 Japanese-only blocks

95 blocks have Japanese text where the same-index English block is empty. `script/fill_rules.json` lists the
decision for each; `build_text.py` reports `copy 274, authored 69, copy_marked 7, ps1_layout 2, unhandled 0`
(counts are block slots across all files that contain the block).

| Rule kind | Meaning | Marker |
|---|---|---|
| `copy` | The English line exists at the same block number in a sibling file: Japanese `st03_ff.msg` blocks `0x33–0xB9` ↔ English `ST03_00/st03_00.msg`; Japanese `st03_00.msg` blocks `0xBA–0xD1` ↔ English `ST03_03/st03_ff.msg` | none |
| `copy_marked` | English line from another slot that does not match exactly (`st03_ff.msg` block `0x54`; `ST13_00.MSG` block `0x26`, whose English is one slot earlier) | `R*` |
| `authored` | No English source: PSP-only UI lines, debug text, a few NPC lines. A translation, by project decision. | `R*` |
| `ps1_layout` | PSP-only block rebuilt from verbatim PS1 text with a layout change (the pause-menu redraw copy, §7.4) | none |

The `*` of the marker has no glyph in the font; it is written as PSP code `0x0010` and shows as a middle dot.

### 3.8 PSP-only choice ops in the Data save menu

The PSP's Data menu (block `0xDC` of `ST03_00` and the same block in 29 other stage files) marks the **Save**
choice with `A3` instead of SEL `96`, and ends with `AB` instead of MULTI `97`, with the same arguments. The
English PS1 block has `96`/`97`, and with those the PSP's Save handler is never reached: choosing Save opened
the Load screen (confirmed in play). `build_text.py` `psp_choice_ops()` gives the k-th English SEL / MULTI the
Japanese `A3` / `AB` wherever the Japanese block has it (60 ops in 30 blocks; arguments and counts asserted
equal). Checked by `verify_msg_args.py` step 4.

### 3.9 Approved edits to PS1 lines

`script/text_edits.json`, applied by `build_text.py` `apply_edits`. Two operations: `replace` (a character
run) and `drop_page` (a whole page, up to and including its NEXT + CLEAR). Every edit must match and every
rule must be used, or the build stops. Current content: one edit (project decision 2026-09-30) in Data's save
help, block `0xE6` of `st03_00.msg` / `st03_ff.msg` (7 copies): "Memory card" becomes "Memory Stick" and the
page about save blocks is removed.

### 3.10 Voice ops in the text

The AUDIO op carries a PS1 `(clip, bank)` pair that means something different on the PSP. `build_text.py`
rewrites these ops according to the audio mode; see §10.3 and §10.4.

---

### 3.11 The name field (op `0xCC`)

`0xCC` shows a name entered on a name-entry screen: the TV station minigames (`st08_02.msg` 0C, 0D, 0F, 10, 11;
`st08_03.msg` 1C, 21, 24, 25) and the same kind of screens in `st05_00.msg` 02 and `st05_fe.msg` 02–05 (14 blocks).
The PS1 writes it as `CC` followed by three `0x4F` cells. Every Japanese PSP block writes `CC`, a `0x0000` unit and
three `0x4F` cells. Converted in the PS1 form (and with the cells turned into the English space `0x1A6`), the PSP
showed a stray "0" after the name on the "Is the name … acceptable?" line and shifted the 2nd and 3rd rows of the
high-score boards (seen in play, 2026-10-12). `msgtool.tokens_to_psp` now writes the PSP form (`NAME_FIELD`): the
`0x0000` unit is added and the three cells stay `0x4F`. Whether the `0x0000` unit is an argument of `CC` or a
cell of its own was not established; the build copies the Japanese layout exactly.
**Confidence:** confirmed in play (test81, 2026-10-13: no stray character after the name, high-score rows aligned);
layout identical to the Japanese blocks (checked byte for byte).

## 4. Text rendering and the font

### 4.1 Font storage

The font is the entry `..\bg\char\font.dat` in `FONT.BIN` (type 3, 0x800 header + 0x8000 bytes). Decoder:
`tools/psp_font.py`.

| Fact | Value |
|---|---|
| Content | two 256 × 256 pages at 2 bits per pixel sharing one 4-bpp texture |
| Bit layout per byte | page A: bits 0–1 (left pixel) and 4–5 (right pixel); page B: bits 2–3 and 6–7 |
| Storage order | blocks of 128 × 32 pixels (64 bytes per block row) |
| Cell size | 12 × 12 pixels, 21 cells per row |
| Glyph lookup | code `c < 0x1BA` → page A, else page B with `c − 0x1BA`; `u = (c mod 21) × 12`, `v = (c div 21) × 12` |
| Page A cells | 441 (`0x000–0x1B8`) |

Block layout from DashEditor; glyph lookup from the renderer code. The font re-encodes to identical bytes
(asserted in `build_font.py`). **Confidence:** confirmed by check and in play.

Code ranges of the Japanese font (from `tools/jptable.py`, built from speaker-name anchors and checked on
21 names): digits `0x00–0x09`; punctuation `0x0A–0x13`; Latin capitals from `0x15`, lower case from `0x30`;
`0x4F` full-width space; hiragana from `0x54`; katakana from `0xA8`; symbols `0xFD–0x10B`; kanji from
`0x111`. Codes with `c mod 21 = 20` are unused in the kana ranges.

Empty cells: `0x4F`, `0x10C–0x10F`, `0x1A5–0x1B7`, `0x36E–0x371`. Kanji codes are not in JIS order; 323 of
them were identified by matching rendered glyphs against a reference font and checking in context (three are
still tentative: `0x11B`, `0x144`, `0x284`). This table is only used to read Japanese text during analysis.

The PS1 `FONT.BIN` is the Japanese-style font too (identical to the PSP font apart from 8 kanji cells).

### 4.2 The draw loop and the variable-width patch

| Fact | Value |
|---|---|
| Draw loop | vaddr `0x3C810`; glyph test `sltiu …, 0x372` at `0x3C814` |
| How a glyph is drawn | a 12 × 12 sprite |
| The only horizontal advance | `addiu a0, a0, 0xC` at `0x3C98C` (x is the `u16` at state + `0x10`; the text pointer is at state + `0x14`) |

Every character therefore advances 12 px. English line breaks and window sizes assume the narrow US font, so
unpatched English text is cut off at the window edge (confirmed in play).

**Patch (`tools/patch_eboot.py`).** The six instructions at `0x3C980–0x3C994` are replaced by a
position-independent trampoline (`lui / bal / ori / addu / jalr / nop`) to new code; it returns to `0x3C998`.
No absolute address is used, so no relocation is needed. The new code computes

```
x += rbx[c] + 1 − lb[next]
```

where, for each glyph, `lb` is the first inked column and `rbx` the last inked column plus a 1-px gap
(capped at 12). Codes outside the table, and all kana and kanji, keep `lb 0, rbx 11` (advance 12).

| Item | Value |
|---|---|
| New code | vaddr `0x226920` |
| Width table | vaddr `0x226980`, one byte per code: `(lb << 4) | rbx`, default `0x0B` |
| Table length | `0x1A7` entries (codes `0x000–0x1A6`) |
| Codes measured from the font | `0x00–0x53`, `0xFD–0x10B`, `0x10D`, `0x10E`, `0x10F`, `0x1A5` |
| English space `0x1A6` | fixed: `lb 0, rbx 4` (5 px) |

**Where the new code lives.** `0x22691C–0x226BB0` is a block of floating-point maths helpers that nothing
calls. It was verified dead by whole-program reachability: entry points are every `jal`/`j` target, every
data word that looks like a text address, and every `lui` + `addiu`/`ori` pair; none reaches the block, and it
contains no relocation entries (`research/eboot_findings.py`). `patch_eboot.py` asserts both.

> **Pitfall: small leaf functions look like dead code.** A first choice of location (`0x4E7E8` / `0x4E998`)
> looked like one unreferenced function but was several small leaf functions, some of them called (for
> example `jal 0x4E794` from `0x3BD0`). The game crashed while loading the title screen. A dead-code check
> must treat every call target in the whole program as an entry point.

**Confidence:** confirmed in play.

### 4.3 Glyphs added to the font

The US English font exists only on the PS1 disc: `CDDATA/DAT/KAIFONT.BIN`, entry `..\bg\char\kaifont.dat`,
same storage format, with cells laid out by text code. `tools/build_font.py` copies four glyphs into PSP
cells that are empty and that no Japanese MSG block or system string uses:

| Glyph | PS1 cell | PSP cell |
|---|---|---|
| α | `0x80` | `0x10D` |
| Ω | `0x81` | `0x10E` |
| `;` | `0x82` | `0x10F` |
| `=` | `0x83` | `0x1A5` |

104 font bytes change. α and Ω are needed by 11 item names in the system-message table.
**Confidence:** confirmed in play.

### 4.4 Why `0x4F` must stay 12 px

> **Pitfall.** `0x4F` is the Japanese full-width space, and the text engine itself writes `0x4F` spaces and
> the hand glyph `0x109` into its own buffers to position menu cursors (about 19 `li 0x4F` sites and many
> `li 0x109` sites in `0x3D384–0x448A0`). When the width table gave `0x4F` 5 px, the Special Items grid
> cursor moved too little per column, and Japanese strings that use `0x4F` for layout were compressed.

Fix: the English space is its own cell `0x1A6` (5 px) and `0x4F` keeps the default 12 px.
**Confidence:** confirmed in play.

---

## 5. The program (EBOOT): layout, segments, relocations, flattening

### 5.1 Obtaining the plain program

`SYSDIR/EBOOT.BIN` is encrypted (`~PSP`) and identical on both releases. `tools/plain_eboot.py` writes
`decrypted_eboot/ULJM05030_EBOOT.BIN` from the user's own image, in this order:

1. the file already exists (an earlier run, or an emulator dump): it is checked and kept;
2. a retail UMD image: `SYSDIR/BOOT.BIN` is the plain program and is copied;
3. the PSN release (`BOOT.BIN` is zero-filled): `EBOOT.BIN` is decrypted with the `pyeboot` Python package.

All three give the same ELF: 4,162,891 bytes, SHA-1 `f615a7040cf809be784780eedb02e3f2c5769235` (confirmed by
check). An emulator dump is 4,163,232 bytes, the same size as the encrypted file: the same ELF plus 341 bytes
after the ELF end that nothing uses. The script computes the ELF end from the section headers before hashing.

### 5.2 ELF layout

The program is a relocatable PSP module (PRX-style ELF) with two loadable segments.

| Item | Value |
|---|---|
| Program headers | at file `0x34`, 2 `PT_LOAD` |
| Segment 0 (code + read-only data) | file offset `0x80`, vaddr `0`, file size `0x245200` |
| `.text` | vaddr `0x40` (file `0xC0`), ends at vaddr `0x230BE0` |
| Segment 1 (`.data` + `.bss`) | file offset `0x245280`, vaddr `0x245200`; `.data` is 915,132 bytes; `.bss` follows (about 4.4 MB, memory only) |
| First free vaddr after `.bss`, 0x40-aligned | `0x756AC0` |
| Section-header table | file `0x324AB8`, 34 sections |
| `.rel.text` | file `0x325018`, size `0x9F3D8` (8-byte entries) |
| `.rel.data` | file `0x3CF6D0`, size `0x1E6F0` |
| Module load address in PPSSPP | `0x08804000` (module base; add a vaddr to get a RAM address) |

### 5.3 Relocations

Relocation sections have type `0x700000A0`. Each entry is `u32 offset, u32 info`:

| `info` bits | Meaning |
|---|---|
| 0–7 | type: 2 = `R_MIPS_32`, 4 = `R_MIPS_26`, 5 = `R_MIPS_HI16`, 6 = `R_MIPS_LO16` |
| 8–15 | **offset base**: index of the segment the `offset` is relative to |
| 16–23 | **address base**: index of the segment whose address is added to the stored value |

The loader adds `module base + address-base segment's vaddr` to the stored value (word, jump target, or
HI16/LO16 pair). `tools/checks/compare_loaded.py` implements exactly this and is the reference loader used
by the checks.

> **Pitfall: data references are relative to segment 1.**
> A code sequence such as `lui v0, 0x50` / `lw a0, 0x800(v0)` does **not** address vaddr `0x500800`. Its
> immediates carry relocations with address base 1 (for example, the entries at `0x2474` and `0x2484` have
> `info` `0x10005` and `0x10006`), so the real address is `0x245200 + 0x500800 = 0x745A00`. The same applies
> to pointers stored in `.data`: the stored word is segment-relative. Two consequences met in practice:
> - "no references found" results for `.data` addresses are meaningless unless the segment base is applied;
> - new code that wants the same variable must use segment 1's address plus the immediate. A first version
>   of the title-screen patch used the bare immediate and pointed at the wrong ordering table; it was caught
>   by a check that compares the new code's computed addresses with the original code's relocated ones.

In this document, addresses written "segment 1 + `0x…`" are in this relative form; plain "va `0x…`" values are
absolute vaddrs. Example: the emulated PS1 RAM is at segment 1 + `0x2D2900` = va `0x517B00` (§6.1).

A second, practical consequence: **patched words must not carry a relocation** unless the patch keeps the
relocation valid. Every patch script either asserts that none of its words is relocated, or (for retargeted
`jal`s and pointers) keeps the existing entry and changes only the target.

### 5.4 Added data: segment 2 and segment 3

English system strings, sprite lists, subtitles and so on do not fit in the original data, so the build adds
data after `.bss`. While the program is being assembled it is kept as extra segments:

| Segment | vaddr | Created by | Content |
|---|---|---|---|
| 2 | `0x756AC0` | `build_sysmsg.py` | English system messages and banner sprite lists (§7); later steps append to it: save-screen strings that do not fit in place (`build_savetext.py`), subtitle tables and strings (`build_subtitles.py`), title-background primitive templates (`patch_ps1_title.py`), wide-HUD code and state (`patch_wide_hud.py`; this sets the segment's execute flag) |
| 3 | after segment 2, 0x40-aligned | `tools/voice/patch_eboot_voice.py` | English voice path arrays and path strings (§10.4) |

Mechanics shared by these steps:

- The segment's bytes are appended to the file, and the program-header table is rewritten at the end of the
  file (`e_phoff`, `e_phnum` updated). Each later step cuts the file at segment 2's offset, appends the grown
  segment and rewrites the headers.
- A pointer slot in `.data` is **retargeted** by changing its existing `R_MIPS_32` entry's address base
  (bits 16–23) from 1 or 0 to 2 (or 3) and storing the new segment-relative offset in the slot.
- New pointers *inside* the added data need new relocation entries. These go into a new relocation section
  (a copy of `.rel.data`'s section header pointing at the new entries), with the section-header table
  rewritten at the end of the file.
- New **code** in segment 2 is written position-independent (`bal` to get the PC), so it needs no relocation.

### 5.5 Flattening to Sony's two-segment layout

**Finding.** The emulator loads a program with 3 or 4 `PT_LOAD` segments without complaint. Real hardware
(PSP Go, ARK-5) does not:

| Program | Result on hardware |
|---|---|
| 3 segments | boots, then crashes at the title screen |
| 4 segments + an extra relocation section | refused with error `80020148` (unsupported PRX type) |
| the same content flattened to 2 segments, **unsigned** | works |

The crash and the error were caused by the extra segments alone. Signing the program was tried and turned out
to be irrelevant: a signed 4-segment program was still refused, and the unsigned flattened one runs. There is
no signing step in the build.

**What `tools/flatten_eboot.py` does** (run by `pack_inplace.py` on every build):

- Segment 1's file image becomes `.data` + `.bss` as file zeros + the extra segments **at their own
  addresses** (extra segment vaddr − segment 1 vaddr = its offset in segment 1). No address changes.
- Relocations whose offset base or address base is 2 or 3 are rebased to segment 1: the offset and the stored
  word get `(extra segment vaddr − 0x245200)` added. Only `R_MIPS_32` entries may refer to the extra segments
  (asserted).
- Entries of the extra relocation sections are appended to `.rel.data`.
- The file is rebuilt compactly in Sony's order: header and segment 0 unchanged, the new segment 1 at Sony's
  `.data` offset `0x245280`, then the non-loaded sections and the 34-entry section-header table in their
  original order and alignment; program headers back at `0x34`.

Checks:

- With no extra segments the output is **Sony's plain program byte for byte**.
- `compare_loaded.py` loads the program before and after flattening and requires identical memory
  (run on every build).
- `audit_eboot.py` loads Sony's program and the built one and accounts for every changed word against the
  list of known patches, and for every added byte after `.bss` against a relocated pointer that reaches it.
  Anything unaccounted or unreferenced stops the build.

Cost: the program file grows to about 8.6 MB (the `.bss` zeros) and no longer fits its 4 MB slot, so it is
moved (§15.2). **Confidence:** confirmed in play on hardware and in the emulator.

---

## 6. Text buffers and memory moves

### 6.1 The PS1 RAM array

The PSP port keeps the PS1's 2 MB of RAM as one array inside its own data:

```
native vaddr = 0x517B00 + (ps1_address − 0x80000000)        (0x517B00 = segment 1 + 0x2D2900)
```

**How established.** By matching `lui`/`addiu` constants in the code against the load addresses in the
container headers (MSG `0x157000`, IDX `0x15C000`, EBD `0x16C000`, …), and confirmed with a save state: the
Apple Market state holds the Japanese `ST04_00.MSG` exactly at PS1 address `0x80157000`. Other variables
follow right after `0x80200000`, so the array cannot simply be enlarged. **Confidence:** confirmed by check.

Code builds a PS1 address `p` as the segment-relative constant `0x2D2900 + (p − 0x80000000)` with a
`lui` / `addiu` (or load/store offset) pair, using the usual `%hi`/`%lo` split with a sign-extended low half.
Example: `0x80157000` is `lui a1, 0x43` / `addiu a1, a1, -0x6700` (`0x429900`).
`tools/memmap.py` has `rel_const()` and `hi_lo()`.

### 6.2 Why the buffers must move

PSP text is 16 bits per character, so the English script is roughly twice the size of the PS1 data and
larger than the Japanese text it replaces.

| Text | File(s) | Japanese address | Space there | Largest English file |
|---|---|---|---|---|
| Stage dialogue (all 125 stage MSGs) | every stage BIN | `0x80157000` | `0x4C00` = 19,456 bytes (to the event-flag bit arrays at `0x8015BC00` / `0x8015BD00`; the IDX loads at `0x8015C000`) | 35,756 bytes (33 files are over the limit: 22,462–35,756 bytes) |
| Support car | `SUPPORT` / `SUPPORT2` `STFF_FD.MSG` | `0x801E4000` | less than needed: other support data follows in the same region (two figures were recorded, see §16) | 47,548 bytes |
| Pause and sub-screens | `SUB_KEY` / `SUB_WPN` `STFF_FE.MSG` (identical, 248 blocks; Japanese size `0x5370`) | `0x801F2000` | about 21.4 KB (code uses `0x801F7098` onward) | 23,716 bytes |

The largest Japanese stage MSG is 18,714 bytes. The stage limit is `0x4C00`, not `0x5000`: code at `0xD8F0`,
`0xE5A0`, `0x1072C` and `0xE5E8` uses bit arrays at `0x8015BC00` / `0x8015BD00` (most likely event flags;
inferred).

### 6.3 Where the code builds each buffer address

Found by `research/msg_base_refs.py`: take every `R_MIPS_LO16` relocation whose instruction carries the
address's `%lo`, trace the base register back through straight-line code and branch sources to its
definitions, and accept the site only if **every** definition is `lui reg, %hi`. Then check that those `lui`
instructions have no other LO16 users.

| Buffer | LO16 sites | `lui` sites | Notes |
|---|---|---|---|
| Stage `0x80157000` | 1 (`0x3C1F4`) | 1 (`0x3C1E4`) | In a wrapper that calls the text opener `0x3C00C`; the opener takes the MSG base as an argument. |
| Support `0x801E4000` | 24 | 24 | All in the support module, `0x4FAC8–0x52D78` |
| Pause `0x801F2000` | 54 | 38 | 53 / 37 are patched. The pair `0x1CC9C` / `0x1CCAC` is **excluded**: it passes `0x801F2000` to the EBD handler (`0x1CCBC`) for `SUPPORT.EBD`, which still loads there. |

No code points *inside* any of the three text ranges; only the bases are referenced. The full site lists are
`SITES` in `tools/memmap.py`.

> **Pitfall: pairing HI16/LO16 entries by their order in the relocation table is not reliable.** A first
> list made that way mis-assigned 7 sites. The register dataflow method above is the one to use.

### 6.4 Where the buffers go

| Buffer | Old address | New address | Limit |
|---|---|---|---|
| Stage | `0x80157000` | `0x80060000` | `0x10000` |
| Support | `0x801E4000` | `0x80070000` | `0x10000` |
| Pause | `0x801F2000` | `0x80080000` | `0x8000` |

The destination is the **PS1 program area, `0x80040100–0x800D9B00`** (about 614 KB). On the PS1 the executable
lived there; the PSP runs native code and never uses this part of the array.

Evidence that it is free:

- **Static:** no code references (LO16 dataflow over `0x80030000–0x800DA000`; the first referenced address
  is `0x800D9B00`); no relocated data pointers. 199 raw `.data` words fall in that numeric range but are
  packed coordinate data, not pointers.
- **Run time:** all zero in six emulator save states of the *original Japanese game* (pause menu, Apple
  Market, junk shop, ruins, boss fight, cutscene). `research/savestate_check.py` checks every moved
  range against RAM used in any state and lists the spans that are empty in all of them.

> **Pitfall: "no code references" does not mean free.** The first destination was the block
> `0x801B4E28–0x801D8000`, which no BIN loads into and no code references directly. The save states show that
> `0x801B8000–0x801C5B00` (54 KB, different content in every state) is live working memory. Stage and support
> text placed there crashed the game as soon as a town's text loaded; pause text placed above it
> (`0x801C8000` / `0x801CB000`) happened to survive. Only save states from real play settled it.

Save-state format (PPSSPP 1.20), as used by the tool: a `0xB0`-byte header (`u32` version, `u32` compression
= 2 for zstd, `u32` compressed size, `u32` raw size, …), then zstd data. In the raw state the PSP RAM
(`0x08000000`) starts at +`0x48`; PS1 address `p` is at raw offset `0x804048 + 0x517B00 + (p − 0x80000000)`.

**What the build changes:**

- `patch_eboot.py`: only the immediates of the `lui`/LO16 pairs (each asserted against the original value).
- `pack_inplace.py`: the load address (+0x0C) in the header of **every** MSG that loads at an old address,
  whether or not its text changed; an MSG over its buffer limit is kept Japanese and listed in the manifest
  (none is, currently).
- `verify_headers.py` allows exactly these address changes.

**Confidence:** confirmed in play (long play in town areas, shops, ruins, support car); the save-state check
covers six situations. Flutter interior, City Hall and the support-car menu were not among the states (§16).

### 6.5 Saves and the moved buffers

Whether a save file contains raw PS1-style RAM that overlaps the moved buffers was raised as a risk. Loading
saves made by earlier builds works (confirmed in play). The explicit cross-load test between the unmodified
Japanese game and the English build is still listed in §16.

---

## 7. System messages, menus, save-screen text, PARAM.SFO

### 7.1 The system-message table

| | PSP (JP) | PS1 (US) |
|---|---|---|
| Table | 248 relocated pointers at `.data` va `0x25451C` | 242 pointers at `0x8008CACC` in `ROCK_NEO.EXE` |
| Strings | MSG-format 16-bit strings at va `0x25205C–0x254520` (9,412 bytes) | 8-bit strings at `0x8008AF48–0x8008CACC` |
| End of a string | first `91`, `95` or `84` op | same |

**Entries 0–241 correspond one to one, in the same order**; 242–247 are PSP additions. The table is used by
the text engine from about 50 code sites (index from script arguments or callers).
Map: `research/system_strings.py`.

| Entries | Content |
|---|---|
| 0–1 | an unused developer screen (§7.5) |
| 2–36 | save / load screens |
| 37–49 | options |
| 50 | pause menu |
| 51–195 | item, part and weapon names |
| 196–208 | containers and vending machine |
| 209–216 | area names |
| 217–226 | "found" and pause-help lines |
| 227–233 | building names |
| 234–241 | trap, reset and clear-time lines |
| 242–247 | PSP additions: screen-size option help, analog-stick variants, the "delete save data" hint |

**Space.** The English strings in 16-bit form need about 12.5 KB against 9,412 bytes available, and verified
dead code is only about 1.1 KB. They are therefore placed in the added data (segment 2, §5.4), and each
translated slot's relocation is retargeted (project decision 2026-09-29). The Japanese strings stay where
they are, because other tables (for example at va `0x254E3C`) point into them.

`tools/build_sysmsg.py`: converts each PS1 string with `msgtool`, stores one copy per distinct PS1 pointer,
and reports `247 entries English, 1 kept Japanese`. `verify_sysmsg.py` reads all 248 slots back the way the
loader will and requires each string to reach an end op. **Confidence:** confirmed in play (pause menu, item
and part lists, options, reset screen, containers, vending machine).

### 7.2 PSP-specific lines

`script/sysmsg_rules.json` holds the lines where the PSP repurposed an option slot or added one (project
decisions 2026-09-29; no marker). Three rule kinds:

| Kind | Meaning |
|---|---|
| `ps1` | use that PS1 entry verbatim (245 and 246 use PS1 41 and 42) |
| `lines` | help-box text built on the slot's Japanese string: its ops up to DECOR and after the text are kept; one `PAD 6` per line |
| `layout_runs` | every op of the Japanese string is kept and its text runs are replaced in order; an optional `window` replaces the WIN geometry |

Slots covered: 38 (option labels), 41/42 (Free Look with the analog stick), 43/44 (Camera), 47/48 (Lock-On),
49 and 242 (Screen), 243/244 (Turn), 245/246, 247 (delete-save hint). Terms: "Analog Stick"; "Directional
button" in help lines; "D-Pad" on the option toggles.

### 7.3 The options screen

- The PSP options screen has six rows: Turn, Free Look, Camera, Map, Lock-On, Screen. It has no Sound or
  Close row.
- The PSP option-row op `AD` carries **8 argument bytes** (the US value is 6). The parser treats the last two
  as a following pseudo-op and the bytes round-trip unchanged. Bytes 5–6 are the help-line slots for choice
  value 0 / 1 (Turn: `0x27` / `0x28` = entries 39 / 40); bytes 7–8 are the alternate help slots (Turn:
  `0xF3` / `0xF4` = 243 / 244; Free Look: `0xF5` / `0xF6` = 245 / 246). This fixes which help line belongs to
  which choice: value 0 → the first slot (Lock-On value 0 = Manual → 47; Screen value 0 = Wide → 242).
  Inferred from data; the resulting screen is confirmed in play.
- **Column alignment.** With proportional letters the Japanese spacing no longer lines up, so slot 38 uses a
  `{COL n}` marker that `build_sysmsg.py` resolves into a PAD op. It tracks x as the engine does (reset at
  `AF`, plus each PAD, plus `rbx + 1` per glyph minus the next glyph's `lb`, from the width table of §4.2)
  and asserts each pad is at least 4 px and each row at most 253 px (the Japanese Camera row ends at 252).
  Labels start at 24 px, the first choice at 105, the second at 162. All non-PAD ops equal the Japanese.

**Confidence:** confirmed in play.

### 7.4 The pause menu has two copies

- The interactive menu is system string 50 (PS1 English, a 12-column box at x `0x58`).
- A **redraw copy** in `STFF_FE.MSG` block `0x00` is shown after returning from a sub-screen. On the PSP it
  is a PSP-only block with an 8-column box at x `0x70`.

The redraw copy is rebuilt from the verbatim PS1 labels with the PS1 box geometry (`ps1_layout` rule, WIN
arguments `58 00 50 00 0C 06`; project decision 2026-09-29). **Confidence:** confirmed in play.

Other in-program text of the same family: menu, item and weapon names are MSG-format strings in `.data`
(joined by op `91`), all reached through the table above.

### 7.5 What stays Japanese in the table

Entry 1, the control legend of a leftover developer screen (project decision 2026-09-29: leave it). The only
code that reads slot 1 is the init function `0x4AFB0`, state 0 of a screen module whose state table is at
`.data` va `0x2614FC` (the entry before it is the pause module, `0x47440…`). The data right after it holds
ASCII debug labels (weapon and appearance names). The screen is not reachable in normal play (inferred).

### 7.6 The mission banner

"MISSION START" / "MISSION COMPLETE" is drawn from the texture `GAUGE01` using **lists of 16-byte sprite
records**:

- fields, in order: screen x, screen y, texture u, v, CLUT (`0x3E76` on the PS1), width, height, end flag,
  padding;
- the last record of a list has `0xFFFF` in the `u16` at record offset 12 (this is how the build finds the
  end); the exact width of each field was not written down (§16);
- each list has a 4-byte zero header word before its records.

| | START | COMPLETE |
|---|---|---|
| PSP pointer slot (`.data` va) | `0x2625C8` | `0x2625D0` |
| PSP list (stored segment-relative value) | va `0x261694` (`0x1C494`), 2 records | va `0x2616C4` (`0x1C4C4`), 3 records |
| PS1 pointer pair `(ptr, 0xD0000)` | `0x8008ECE0` | `0x8008ECE8` |
| PS1 list | `0x8008DD6C`, 3 records | `0x8008DDAC`, 6 records |

The textures differ only in rows 208–247 and in **palette 6** (the banner gradient). Word cells: PSP
(katakana) at u 0 (64 px), u 69 (86 px), u 164 (57 px); PS1 English MISSION u 88 (92 px), START u 186 (70 px),
COMPLETE u 2 (110 px, packed as a 16-row top part and an 8-row bottom part at u 112 / v 232). The English
words are 20–45 % wider and laid out differently, so they cannot be painted into the Japanese cells, and the
9 records needed do not fit in place.

`build_sysmsg.py` copies the two PS1 lists verbatim into segment 2 and retargets the two pointers (original
values asserted). The texture and palettes come from the swap list (§9). The PS1 screen positions are used as
they are (y 44; the PSP had moved COMPLETE to y 64). **Confidence:** confirmed in play.

### 7.7 Save-screen text (the PSP save utility)

The strings the game hands to the PSP save utility are **UTF-8** in `.rodata` (va `0x23CE1C–0x23DD8C`), reached
through `R_MIPS_32` pointers in `.data`.

| Pointer slots | Content |
|---|---|
| `0x263344–0x2633EC` | difficulty names (`0x263350`, `0x263354`), "Play Time" (`0x263358`), the save title (`0x26335C`), "Game Data" (`0x263360`), "Rockman" (`0x263364`) and "DASH" (`0x263368`), 28 location names including placeholders (3 pointers are shared), "New Data" (`0x2633EC`) |
| `0x250704`, `0x250708` | two Memory Stick Duo error messages (no stick; not enough space, 360 KB) |

Code `0x4F1C0–0x4F318` fills the utility's parameter block: title (+`0x00`) from slot `0x26335C`, save-data
title (+`0x80`) from `0x263360`, detail (+`0x100`) from a `sprintf` of play time / difficulty / location,
parental level (+`0x500`). The same function builds "Rockman" + "®" + "DASH" into a stack buffer that nothing
reads afterwards; the "DASH" string is also used by code at `0x94A00` and is left unchanged.

`tools/build_savetext.py` (rules: `script/savedata_rules.json`, 37 strings keyed by slot):

- writes each English string over the Japanese one when it fits in that string's space (up to the next
  string; zero-filled);
- otherwise appends it to segment 2 and retargets the slot's relocation. Currently only the save title
  "Rockman DASH: Hagane no Boukenshin" (34 bytes; 25 available) is moved.
- Area names come from the PS1 system strings 209–216 and the PS1 script where they exist; the rest are
  approved translations (project decision 2026-09-30).
- With the `legends` localization the save title is "Mega Man Legends" (rule field `en_ps1_save`), which
  fits in place.

**Play-time format.** The detail string's format is at va `0x23DE18`: `"%s %d:%d:%d%d\n%s\n%s\n"` (label,
hours, minutes, seconds tens, seconds ones, location, difficulty; `sprintf` is `0x22899C`). Minutes are not
padded, so the original shows times like `0:7:34`. It is changed in place to `%02d` for the minutes (project
decision 2026-09-30). It fits: 25 bytes in the 26 before the next string. The same `sprintf` formats the save
name with `%04d`, so zero-padded widths are supported.

**Save identity is untouched** and asserted: the strings `ULJM05030`, `%04d` and `DATA.BIN` are byte-identical
and at the same addresses, and the code that builds the utility parameters (key, sizes) is not modified.
`verify_savetext.py` reads every string back through its slot from the loaded program.
**Confidence:** confirmed in play (save screens, details, loading older saves).

### 7.8 PARAM.SFO

`tools/build_sfo.py` changes only `TITLE` (asserted), inside its fixed 128-byte slot, so the file keeps its
size and is written in place. `DISC_ID`, version and category are unchanged.

| Localization | `TITLE` |
|---|---|
| `text`, `audio` | Rockman DASH: Hagane no Boukenshin (project decision 2026-09-30) |
| `legends` | Mega Man Legends (project decision 2026-10-01) |

`verify_sfo.py` requires every other byte of the file to be identical to the original.

---

### Weapon development screen: level labels

The enhancement list prints each attribute's level through a text op whose handler (0x412C0–0x41338) copies 7 units
from one of three templates in `.data`: segment 1 + 0xFB6C ("level" + digit; the digit glyph is stored into unit 3 by
`sh a0, 6(a3)` at 0x41308), + 0xFB7A ("level max"), + 0xFB88 ("cannot be enhanced"). They are raw glyph codes, not
MSG strings, so the system-message table does not cover them. The US PS1 executable has the same three 7-byte
templates at file offsets 0x887DC ("Level n", digit in byte 6), 0x887E4 ("Max Lvl") and 0x887EC ("N/A").
`tools/build_sysmsg.py` copies those (codes mapped as for dialogue) and moves the digit store to unit 6
(`sh a0, 12(a3)`). Found from save states of the screen; not yet confirmed in play.

## 8. Title screen

All title-screen data is in `DEMO_DAT.BIN`.

### 8.1 Textures

| Entry | Disc | Format | Content |
|---|---|---|---|
| `..\BG\CHAR\NTITLE.TIM` | PSP | 8 bpp, 256 × 160, 1 CLUT, VRAM (`0x140`, `0x100`), CLUT row `0x1F0` | Japanese logo |
| `..\BG\CHAR\NTITLEU.TIM` | PS1 | 8 bpp, 256 × 256, same VRAM place and CLUT row | Mega Man Legends logo |
| `..\BG\CHAR\NTITLE2.TIM` | PSP | 4 bpp, 256 × 64, 8 CLUTs, size `0x2120` | PRESS START BUTTON, the copyright line, the three menu words (row at y 32) and the three difficulty words (row at y 48), in Japanese |
| `..\BG\CHAR\NTITLE5U.TIM` | PS1 | 4 bpp, 256 × 96, 9 CLUTs | The English set: PRESS START BUTTON, two copyright lines, NEW GAME, CONTINUE, OPTION, EASY, NORMAL, HARD |
| `..\BG\CHAR\NTITLE3U.TIM` | PS1 only | 8 bpp, 192 × 160, VRAM (`0x240`, `0x100`), CLUT row `0x1F2` | title background |

Colours are palettes, not separate images: one set of word pixels is drawn with different CLUTs.
PSP `NTITLE2`: CLUT 0 white/blue (unselected, and PRESS START / copyright), CLUT 1 yellow (selected), CLUTs
2–7 for the difficulty words. PSP word pixels use a 13-step gradient (indices 1–13) plus outline indices
14/15; the PS1 word art uses a 7-step gradient (indices 1–7) plus shadow indices 8/9.

### 8.2 Menu code

The title sprites are PS1-style `POLY_FT4` primitives (code `0x2C`, 9 words after the tag): x/y at +8/+0xA
and so on; u/v at +0xC/+0xD, +0x14/+0x15, +0x1C/+0x1D, +0x24/+0x25; CLUT at +0xE; texture page at +0x16.
The PSP helper functions match the PS1 library calls:

| PSP function | PS1 library equivalent |
|---|---|
| `0x216518` | `GetTPage` |
| `0x216554` | `GetClut` |
| `0x21647C` | `AddPrim` |
| `0x2165C0` | `SetDrawMode` |

**Main options: function `0x26BC`** (argument = selected index). Three stacked 80 × 16 quads:

| Item | Original value |
|---|---|
| Screen x, shared by all three | `0x78` to `0xC8` (registers set at `0x277C`, `0x2780`) |
| Screen y | `0xA4–0xB4`, `0xB4–0xC4`, `0xC4–0xD4` |
| Texture v | `0xC0–0xD0` for all three (texture rows 32–47) |
| Texture u cells | 0–`0x50`, `0x50`–`0xA0`, `0xA0`–`0xF0` |
| CLUT | selected: CLUT x `0x10` (palette 1); others: 0 (palette 0) |

**Difficulty:** the same function from `0x2A3C`. One 80 × 16 quad at x `0x78–0xC8`, y `0xD4–0xE4`, v
`0xD0–0xE0` (row 48); u is chosen by the difficulty value from 80-px cells: 0–80 hard, 80–160 normal,
160–240 easy. Palettes: selected `2d + 3`, unselected `2d + 2`.

PRESS START and the copyright line use palette 0 (CLUT argument set at `0x253C` and `0x25F8`).

### 8.3 English menu words (all localizations)

Project decision 2026-09-29: keep the PSP layout; use the PS1 letters.

All three options share one screen width and their u cells sit side by side in one 256-px row, so the widest
cell possible without a neighbour's art showing is 86 px. The PS1 words at their own spacing are 102 px wide
(NEW GAME, CONTINUE). `tools/build_title.py` therefore re-spaces the PS1 letters to 1-px gaps (3-px word
space) without changing any letter:

| Word | Source rectangle in `NTITLE5U` (x0–x1, y0) | Width after re-spacing | Placed at u |
|---|---|---|---|
| NEW GAME | 3–104, 42 | 86 | 0 |
| CONTINUE | 115–216, 42 | 83 | 86 |
| OPTION | 3–75, 58 | 66 | 179 (centred in cell 169–255) |
| EASY | 84–131, 58 | 48 | centred in 160–240 |
| NORMAL | 139–210, 58 | 72 | centred in 80–160 |
| HARD | 3–50, 74 | 48 | centred in 0–80 |

Rows 0–31 of the texture are the PSP original. PS1 indices are remapped onto the PSP scheme
(1–7 → 1, 3, 5, 7, 9, 11, 13; 8 → 14; 9 → 15) so the PSP palettes apply.

`patch_eboot.py` `TITLE` widens the quads with seven immediates (each asserted):

| vaddr | Change | Meaning |
|---|---|---|
| `0x277C` | `0x78` → `0x75` | screen x left |
| `0x2780` | `0xC8` → `0xCB` | screen x right |
| `0x278C` | `0x50` → `0x56` | u: option 1 right / option 2 left |
| `0x2860` | `0xA0` → `0xAC` | u: option 2 right |
| `0x2920`, `0x2944` | `0xA0` → `0xA9` | u: option 3 left |
| `0x2928` | `0xF0` → `0xFF` | u: option 3 right |

Cell 3 overlaps cell 2's blank last three columns. The difficulty words fit their 80-px cells, so they are a
texture-only change. **Confidence:** confirmed in play.

### 8.4 PS1 title screen (`--localization=legends`)

Project decision 2026-10-01. Texture side: `tools/build_ps1_title.py`; program side:
`tools/patch_ps1_title.py`.

**Logo.** Both games draw only the top 160 rows of the logo texture with one FT4 (UV 0,0–255,160; PS1 code in
function `0x80013FB8`, PSP function `0x2248`); the rows below are overwritten in VRAM by the menu-word
texture. The first 160 rows are the first `0xA000` stored bytes (five rows of 64 × 32-byte blocks; asserted to
be a block prefix), so the PS1 logo's pixels and 256-colour CLUT fit the PSP entry exactly.

**Background.** PS1 code `0x800140BC–0x80014358` draws:

1. two FT4 quads from `NTITLE3U` texels 0–160 over y 0–`0xA0`, the right one mirrored;
2. a subtractive gouraud quad (fade) over y `0x90–0xA0`, with a draw-mode primitive;
3. a gouraud gradient from black to (`C0`, `FF`, `E0`) over y `0xA2–0xF0`.

The PSP draws instead: flat white over y 0–`0xA2`, a gradient to (`10`, `80`, `E0`) down to `0xB4`, flat blue
to `0xEF` (code `0x2370–0x248C` inside `0x2248`).

The PSP background code is replaced. The five PS1 primitives are stored as constant templates in segment 2
(the values the library calls would produce: texture page `0xD9`, CLUT `0x7C80`, draw-mode word
`0xE10000C0`). A short loop (entry at `0x2370`, loop at `0x240C`) copies each into the primitive buffer and
calls `AddPrim` with the same ordering-table slots as the PS1 (`0x8C`, `0x88`). Everything is reached
PC-relative; the ordering-table pointer is at segment 1 + `0x500800` (§5.3). The old code's relocated words
(`0x2374`, `0x23B0`/`B4`, `0x23F4`, `0x2404`/`08`, `0x2474`, `0x2484`/`88`) are left as they are and never
executed (`0x2374` sits in the `bal` delay slot and is a harmless `lui`).

`NTITLE3U` has no PSP counterpart. Its PS1 entry is inserted verbatim after `NTITLE2` (16 sectors), so
`DEMO_DAT` grows.

**Menu colours.** PS1 menu code `0x8001456C`: unselected options use palette 1 (mint) and the selected option
palette 2 (orange) (`0x800145C8`: CLUT x `0x10`, changed to `0x20` only for the selected option); difficulty
selected `2d + 3`, unselected `2d + 4`. The PSP word art keeps its indices, and its palettes are rewritten
with the PS1 colours on the mapped indices:

| PSP palette | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| takes PS1 palette | 1 | 2 | 4 | 3 | 6 | 5 | 8 | 7 | (the PSP's old palette 0) |

A ninth palette is added for PRESS START and the copyright line (header CLUT count 8 → 9, size `0x2120` →
`0x2140`, as `NTITLE5U` has; the sector count is unchanged) and the two CLUT arguments at `0x253C` / `0x25F8`
change from 0 to `0x80`.

**Japanese title calls.** Title code `0x1990–0x1A78`: when the title's 300-frame counter starts it queues
sounds `0x1C7 + 4k` / `0x1C8 + 4k` (sound queue function `0x7728`), and at 240 it queues `0x1C9 + 4k` /
`0x1CA + 4k`; `k` cycles 0–2 each time the title is shown. These are six stereo voice pairs in the title
sound bank's program 6 (inferred from the bank, §10.7). The same samples are on the US disc but the US code
never queues them. Two branches are pointed past the queue calls: `0x19A4` → `0x1A78` and `0x19AC` → `0x1A14`
(the variant counter still advances). The three English title voices (program 2) are unaffected.

`verify_ps1_title.py` checks the textures, every changed word, the templates, and that the new code's
PC-relative addresses resolve to the templates, to `AddPrim` and to the ordering-table pointer the original
relocated code reads. **Confidence:** confirmed in play (logo, background, colours, no Japanese call).

---

## 9. Texture swaps

### 9.1 Survey

`research/tex_compare.py` pairs every container TIM on both discs per BIN: first by name (the US disc
often adds a `U` or `E` before `.TIM`, or renames the file), then by "same BIN, same position, same header
format". Result: 1,650 identical, 189 differing, 10 PSP-only by name. Most of the 189 differ only in bytes
after the image; 21 distinct textures differ in pixels.

> **Pitfall: match by position as well as by name.** The opening prologue pages (`OPMOJI1–4`) and the island
> maps (`MAP_A1…B3`) first looked PSP-only. The US disc has them under different names (`OPENG0–3`,
> `MAP_*E`) at the same positions in the same BINs with the same formats.

### 9.2 Mechanism

`script/texture_swaps.json` lists the swaps; `tools/build_textures.py` writes, per PSP BIN containing the
entry, `build/tex_psp/<BIN>/<entry>.pix` (PS1 pixel bytes, `width × height` only, §2.5) and, when palettes
are to be copied, `.hdr` (header bytes `0x100–0x800`). It asserts equal sizes and identical header bytes
`0x0C–0x2C` (format and VRAM position). `pack_inplace.py` writes them into the entry (§15.1).

`clut` values: `false` keeps the PSP palettes; `true` copies the PS1 palettes; `"auto"` copies the PS1's 15
colour bits but keeps the PSP's bit 15, and writes a palette only where colours really differ. The reason for
`auto`: in the artwork textures the two discs differ in **bit 15 (the semi-transparency flag)** of most
colours.

A swap with `"name"` applies to every PSP entry with that file name, each taken from the same data file on
the US disc (some names have two or three pixel variants there).

### 9.3 The swaps

Always applied (text-bearing):

| PSP entry | PS1 entry | Palettes | What |
|---|---|---|---|
| `SUB02.TIM` | `SUB02U.TIM` | PS1 | Weapon-screen labels. Only palette 4 differs; with the PSP palette the English labels would be green. |
| `OPMOJI1–4.TIM` | `OPENG0–3.TIM` | PSP | The four opening prologue pages (in `ST01`). The English text uses indices 10–15, which the PSP palette colours as the same pale gradient. |
| `MAP_A1`, `A2`, `B1`, `B2`, `B3` | `MAP_*E` | identical | Island maps with English labels |
| `GAUGE01.TIM` | `GAUGE01u.TIM` | PS1 | Mission banner (§7.6); in `DEMO_DAT`, `EXIT_MAP`, `EXIT_SUP`, `GAUGE`, each with a type-10 twin |

Only with `--localization=legends` (US names and artwork; project decision 2026-10-01):

| Entry | What |
|---|---|
| `intvh20.TIM` (`ST08`) | TV-station monitors: station name and phone number |
| `st7_410.TIM` (`ST08_00`, `00B`, `00C`) | TV-station exterior signs |
| `SCKO00.TIM`, `GAITOU.TIM` | vending machine artwork |
| `EM6400.TIM` | TV reporter |
| `INLIV00.TIM` | room interior props |
| `EM0000.TIM` | Servbot faces and props |
| `TRUNK.TIM`, `KABUTO.TIM`, `ST02BG02.TIM` | trunk scene, comic cover, Flutter map lettering |

Not swapped on purpose: `SUB01` (key-item screen; identical pixels on both discs), `ST15BG02` (publisher
logo), the credits `STAFF00–09` (the PSP credits its own staff), and with `text` / `audio` the Japanese logo.

**Confidence:** weapon labels, prologue, maps, banner and monitors confirmed in play; the legends-only
artwork set is confirmed by check only (§16).

---

## 10. Voices and audio

### 10.1 PS1 audio layout (US disc)

| Fact | Value |
|---|---|
| Voice banks | `/CDDATA/XA/XA1806E … XA1880E`, 36 files. **Bank number = position in name order** (0–35). |
| Voice format | mono 18.9 kHz XA-ADPCM (coding byte `0x04`), up to 32 channels per file, several clips per channel |
| Clip boundary | each clip ends with a sector whose submode has the EOF bit (`0x80`); audio sectors have submode bit `0x04`; the channel number is byte 17 and the submode byte 18 of the raw 2,352-byte sector |
| **Clip number used by the AUDIO op** | **the clip's rank by first sector within its bank** (not the channel number) |
| Voice clips | 691, about 2,314 s in total |
| Cutscene streams | `XA37S00E`, `XA37S01E`: stereo 37.8 kHz, 8 channels, voice mixed with music; 69 clips, about 4,988 s |

The clip-number rule was established by transcribing all 691 clips (speech-to-text) and comparing each
transcript with the text that follows the AUDIO op naming it: 630 of the 646 ops followed by text match; the
16 misses are grunts, barks and one misheard place name. **Confidence:** confirmed by check, and in play
(the right lines are spoken).

`tools/voice/extract_voice_en.py` writes each clip's raw sectors to a `.xa` file in
`build/voice_en/` with `index.csv` / `index_streams.csv`. Stream clips are named `s00_…` / `s01_…` and ranked
the same way.

**Decoding without other programs (`tools/voice/xa.py`, 2026-10-05).** Until then FFmpeg decoded and resampled the
PS1 audio; now the project does both itself with numpy.

- *Sector:* 12 sync bytes, 4 header bytes, the 8-byte XA subheader, then 18 sound groups of 128 bytes. Coding byte
  (offset 19): bit 0 stereo, bit 2 18.9 kHz (else 37.8 kHz), bits 4–5 zero for 4-bit samples. A sector holds 4032
  samples (2016 per channel in stereo), so a clip's length follows from its sector count.
- *Sound group:* 8 sound units of 28 samples. Bytes 4–11 are the units' parameters (low 4 bits range, high 4 bits
  filter). Byte 16 + i + 4j carries sample j of unit 2i (low nibble) and of unit 2i + 1 (high nibble). Mono plays
  units 0–7 in turn; stereo has the even units left and the odd units right.
- *Sample:* `s = (nibble << (12 − range)) + ((K0·s1 + K1·s2 + 32) >> 6)`, limited to 16 bits; (K0, K1) by filter:
  (0, 0), (60, 0), (115, −52), (98, −55), (122, −60).
- *Check:* all 760 clips (691 voice, 69 stream) decode to exactly the samples FFmpeg 9.0.2 produced.
- *Speed:* each sample needs the two before it. Every channel is cut into pieces of 1152 units; all pieces of all
  clips are stepped side by side, later pieces from a guessed state, and a second pass recomputes each piece's start
  from the true end of the piece before until two samples in a row agree with the first pass (from there the first
  pass is exact). About 20 s for the whole disc on the test machine.
- *Resampling:* 18.9 / 37.8 kHz to 44.1 kHz is 7/3 or 7/6: a Kaiser-windowed sinc (32 input samples wide, pass band
  0.96 of the input's half rate) evaluated at the 7 output positions of each block of 3 or 6 input samples, as a
  matrix product. Output lengths equal FFmpeg's; the samples agree with FFmpeg's resampler to about 46–63 dB.

### 10.2 PSP audio layout and lookup

Files: `/PSP_GAME/USRDIR/DAT/at3/xa18mBB/<name>.at3` (voice clips, folder named by the Japanese bank number in
hex) and `/at3/xa37s00/` (cutscene streams). The files have names (`or_00a.at3`, `rn00.at3`, …), not numbers.

Lookup in the program:

| Item | Location |
|---|---|
| Sound id | `type << 28 | bank << 16 | clip` |
| Play functions | `0xACA0` ("play") and `0xADAC` ("play2"); the only code that reads the tables below |
| Per-type table | segment 1 + `0xA938` (va `0x24FB38`) |
| Per-bank table | va `0x24FA64` (segment 1 + `0xA864`), **53 slots**, each a pointer to the bank's first path pointer, 0 = unused |
| Flat path-pointer table | va `0x24ECE0`, 865 pointers; path strings from va `0x2319B0` (`disc0:/PSP_GAME/USRDIR/DAT/at3/…`) |
| Checks made by the code | only null checks, no bounds |

Slots used by the Japanese game: `0x00, 0x03, 0x05, 0x06, 0x08, 0x0A, 0x0B, 0x0C, 0x19, 0x1C, 0x1D, 0x30,
0x31, 0x32, 0x33, 0x34` (16). Slots `0x33` and `0x34` are the two cutscene-stream lists (the PS1's `s00` and
`s01`); stream ids are type 2 (`0x2000xxxx` / `0x2001xxxx`), and the type-2 table at segment 1 + `0xA930` is
the address of slot `0x33` of the same table (`0xA864 + 4 × 0x33`). 37 slots are free.

How sounds are started (static analysis of the whole program, `tools/checks/jp_audio_audit.py`):

- Every `.at3` is opened by a path from these tables. No path is built at run time (the only `.at3` strings
  are the table paths; leftover PS1 XA path strings name files that do not exist on the PSP).
- play / play2 are called only directly: 62 `jal` sites, no function pointers.
- A site's sound id is a constant (`lui`/`ori`), or comes from the MSG AUDIO op (handler at `0x3D0D4`), or
  from one of two id tables: `0x92710` → va `0x2816CC` (credits streams, index 1–6 from a byte table) and
  `0xBDC38` → va `0x28D98C` (news-report voice ids, §10.5).
- The program's own MSG-format strings (system messages, subtitles) contain no AUDIO op.
- **Bank 6 is special:** clips `0x12–0x2E` of bank 6 also start the TV-news subtitle scenes (a jump table at
  `0xAD08` leads to the subtitle function `0x449D0`, §11).

### 10.3 Why English text with Japanese audio needs remapping

The AUDIO op (`8F`: `clip, 0, bank, 0`) uses different numbering on the two games. Copied unchanged, an
English op either names a bank slot that is empty on the PSP, or names the wrong Japanese clip.

> **Pitfall: a voice op naming a missing clip hangs the text box.** No voice starts, and the text engine
> waits for it forever (an empty, stuck box; in cutscenes the game stops). A save state showed the script
> pointer sitting just after the AUDIO op. The wrong-clip case plays an unrelated Japanese line and shows
> that line's subtitle.

Scale (blocks with voice: 834): the English script has 1,655 AUDIO ops, the Japanese 1,343. The ops are
identical in 6 blocks, same count but different ids in 455, different counts in 293, Japanese-only in 33,
English-only in 47.

**`--localization=text` (Japanese voices).** `build_text.py`, in its Japanese-voice mode, removes the English
ops and places the Japanese block's ops in the English text (`tools/voice/voice_map.py` `place_jp`):

| Case | Rule | Blocks |
|---|---|---|
| same count | Japanese op k takes English op k's place | 461 |
| different counts | each Japanese clip is matched, in order, to the anchor nearest **in time**. Anchors: the English ops' positions, page starts, sentence ends. A Japanese op's position = length of the Japanese clips before it / all of them; an anchor's = English clips before it plus the part of its own clip up to the anchor by characters. | 293 |
| Japanese only | the same, on character positions | 33 |
| English only | the English ops are removed | 47 |

All 1,343 Japanese ops are placed. Matching by time follows the voice better than character fractions
because a spoken line takes about as long in both languages. `verify_voice.py` requires every op to name an
existing clip. **Confidence:** confirmed in play that the stuck boxes are gone; the placement of individual
clips in the 293 time-matched blocks was not all reviewed (§16).

### 10.4 English voices (`--localization=audio` / `legends`)

**Text side.** `build_text.py`, in its English-voice mode, keeps the English ops and changes only the bank byte: PS1 bank `b` →
free PSP slot `SLOTS[b]`, the first 36 free slots in order: 1, 2, 4, 7, 9, 13–24, 26, 27, 30–46 (decimal).
Slot 6 is never used. The clip number is unchanged.

**Files.** A new folder `/PSP_GAME/USRDIR/DAT/at3/xaen/` holds the 691 clips as `eBB_CC.at3` (PS1 bank, clip
number; decimal). The folder name sorts after every sibling, so only one directory record and one path-table
entry are appended (§15.3).

**Program side** (`tools/voice/patch_eboot_voice.py`): segment 3 holds, per English bank, an array of path
pointers followed by the path strings (`disc0:/PSP_GAME/USRDIR/DAT/at3/xaen/eBB_CC.at3`). Each of the 36
bank-table slots (zero in the original, asserted) gets its array's address. Relocations added: 36 for the
slots plus 691 for the path pointers = 727 `R_MIPS_32`. `verify_voice_eboot.py` loads the program like the
loader and resolves every Japanese and English id to its path.

**Cutscene streams.** The PSP's stream path n in slot `0x33` is the PS1 `s00` clip of rank n, and in slot
`0x34` the `s01` clip of rank n (66 of 69 durations agree within 1 s). `tools/voice/build_audio.py` replaces,
by path, every stream that has a subtitle scene (§11) plus three other voiced ones (`s00` rank 30, the
prologue narration; `s01` rank 0, the opening; `s01` rank 29, a launch line). Music-only streams stay.

One exception (`script/voice_rules.json` `stream_overrides`): scene A15 (the lake boat repair). The US disc's
`s00` rank 15 is the **Japanese** track (it matches the PSP's `bsr.at3`, correlation 0.99); the English dub
is rank 18. The PSP also has `bsr2.at3`, a variant of the same scene; the single English version goes over
both. Confirmed by ear.

**Japanese voice clips dropped.** With English voices nothing can play the files in `at3/xa18m*` (see the
audit below), so `pack_inplace.py --drop-jp-voice` removes them (846 files, 54.1 MB) and reuses their sectors
(§15.2). The folders stay, each with only its `.` and `..` records.

**Audit of the Japanese audio** (`jp_audio_audit.py`), 795 voice-clip paths and 69 streams:

| Count | Status |
|---|---|
| 553 clips | every line that uses them is voiced in English: replaced |
| 13 clips | the PS1 English line has no voice: silent in English, as on the PS1 |
| 224 clips | never played, not even by the Japanese game (no script or code reference) |
| 5 clips | started by code, not text: the City Hall news reports (§10.5) |
| 49 streams | replaced by English |
| 18 streams | kept; they match their PS1 counterparts to codec noise (no language content) |
| 2 streams | kept by decision: `cd00long.at3` and `cd00.at3`, the PSP's re-edited credits theme (project decision 2026-09-30) |

`PSP_GAME/SND0.AT3`, the PSP menu music (PSP-only), is removed from every build (project decision 2026-10-05, §14). `verify_dropped.py` checks that nothing
dropped is reachable and that `xa37s00` (71 files) and `xaen` (691) are complete.

**Confidence:** English voices and cutscenes confirmed in play, including on hardware.

### 10.5 Voices started by code: the news reports

Five bank-6 clips are started by game code:

| Scene | Japanese id | File | Selected by | English clip (PS1 bank 11) |
|---|---|---|---|---|
| C01 | `0x60012` | `rn00.at3` | table va `0x28D98C` index 0 | `b11_c04_0` |
| C02 | `0x60013` | `rn01.at3` | index 1 | `b11_c05_0` |
| C04 | `0x60015` | `rn03.at3` | index 2 | `b11_c06_0` |
| C03 | `0x60014` | `rn02.at3` | index 3 | `b11_c07_0` |
| C00 | `0x6002E` | `rm.at3` | constant: `lui`/`ori` pair at `0xBD664` / `0xBD674` | `b11_c10_0` |

The table index comes from story flags `0x623–0x625`; the constant is used with flag `0x626`. `rn04` / `rn05`
(scenes C05 / C06) are not reachable from the PSP code.

Mechanism: the code's ids are left alone. The **bank-6 path-array entries** of these five clips are pointed
at the English path strings in segment 3 (their relocation is retargeted). Because the ids stay in bank 6, the
game's own trigger still starts subtitle scenes C00–C04, which carry English text (§11).

> **Pitfall:** a first version changed the ids themselves to English bank ids. The reports played in English,
> but the subtitle trigger depends on the bank-6 id, so the subtitles stopped.

The English clips were matched to scenes by content. **Confidence:** confirmed by check
(`verify_voice_eboot.py` resolves all five); in play, see §16.

### 10.6 The `.at3` container and encoder settings

Japanese voice and stream files are RIFF/WAVE with `WAVE_FORMAT_EXTENSIBLE` ATRAC3plus, 44.1 kHz, 744-byte
frames (voice mono, streams stereo). A few music files (the opening and credits streams) are plain ATRAC3
(format tag `0x270`, stereo, block 384), so the player handles both.

`tools/voice/encode_at3.py` writes the header in the Japanese layout:

| Chunk | Content |
|---|---|
| `fmt ` (52 bytes) | tag `0xFFFE`, channels, 44100, byte rate `frame × 44100 / 2048`, block align = frame size, bits 0, `cbSize` 34, 2048 samples per block, channel mask 1 or 3, ATRAC3plus GUID `bfaa23e958cb7144a119fffa01e4ce62`, version 1, 2 codec-config bytes (`0x20 | channels << 2 | high bits of (frame/8 − 1)`, then the low byte), 8 zero bytes |
| `fact` | `u32` end sample, `u32` sample offset |
| `data` | raw frames |

For a mono 744-byte file the `fmt ` chunk comes out byte-identical to a Japanese clip's.

**The `fact` rule.** In all 447 Japanese ATRAC3plus files the offset is 2048 and
`frames × 2048 − (end + offset) ≥ 396`. The PSP skips `offset + 368` samples and needs
`end + offset + 368 ≤ frames × 2048`.

> **Pitfall:** a file that breaks this rule never starts, and the text box waits on it (§10.3). The encoder
> used here delays its output by 4,464 samples and drops the delayed tail, so writing "end = number of
> samples, offset 4096" put the end about 2,400 samples past the data. Confirmed in play: the clip did not
> play and the box hung.

Now: offset 2048; end sample = samples + 2048 (4464 − 2048 − 368), so the whole clip plays after 46 ms of
extra lead-in; the input is padded with silence so that at least 400 samples are spare (asserted per file).

**Encoder.** atracdenc; its source is included in `src/atracdenc` with one change: the ATRAC3plus frame size
is read from the environment variable `AT3P_FRAME` instead of the hard-coded 2048. The reason is the bit
rate: frame size sets it.

| Material | Frame size | Reason |
|---|---|---|
| Voice clips (mono) | 744 | Same as the Japanese. The source is 18.9 kHz, so nothing lies above 9.4 kHz. Measured SNR against the source: 376 → 14.5 dB, 560 → 19.4 dB, 744 → about 32–34 dB. |
| Cutscene streams (stereo) | 1864 | The encoder low-passes by bit rate (below). 1864 is the lowest rate as bright as Sony's Japanese streams. |

Measured low-pass of the encoder on a stream: 744 cuts above about 5–6 kHz; 1120 about 9–10 kHz; 1488 about
12 kHz; 1864 flat to 15 kHz (−3 dB at 16 kHz); 2048 flat to about 17 kHz. Sony's 744-byte Japanese streams
keep content to about 15–16 kHz, and the PS1 source has content to about 17 kHz. Only standard ATRAC3plus
frame sizes are used (376, 560, 744, 936, 1120, 1488, 1864, 2048).

Quality check of all encoded files (`research/audio_check.py`, decoding as the PSP plays them): voice
clips SNR 26–38 dB, no added pops (8 clips have clicks in the PS1 source itself); streams at 1864: 30–33 dB,
no artefacts above the detector threshold. The largest stream is the opening, about 12.6 MB (the largest
Japanese stream is 5.1 MB).

### 10.7 Voice samples inside sound banks (VAB)

A few short voices are not `.at3` files but SPU samples in VAB sound banks inside container BINs. Full survey
of the PS1 BINs against the PSP:

| BIN | PSP entry | PS1 English entry | Voice samples (VAG numbers) | What |
|---|---|---|---|---|
| `DEMO_DAT` | `e_title.vab` | `ee_title.vab` | 9, 10, 11 (program 2, keys 60–62) | title screen and title-menu voices |
| `BS16VAB1` | `t_lb01b.vab` | `et_lb01b.vab` | 17–26 (program 1, keys 60–69) | in-game voice samples |
| `ST1A_02B` | `t_lb02b.vab` | `et_lb02b.vab` | 15–28 (program 1, keys 60–73) | in-game voice samples |

(All under `..\sound\moto\se\vab\`.) Every other byte of each bank is identical between the discs apart from
size fields. `common.vab` is identical.

Container VAB entry (type 5): +4 size = VAB header + body; +8 sectors = 1 + sectors(header) + sectors(body);
+`0x14` SPU address (`0x28000` for all three); +`0x18` VAB header size. The data is the VAB header (`pBAV`,
programs, tones, the VAG size table in units of 8 bytes), **zero padding to the next sector**, then the VAGs
back to back. Each voice VAG is a zero block, data blocks (flag 4 on the first, 1 on the last), then a
`00 07 77…` block.

> **Pitfall:** the VAG body starts at `entry + 0x800 + (VAB header size rounded up to a sector)`, not right
> after the header. Slicing without the padding misaligns every sample by 2,016 bytes and produces false
> differences.

Tones: in the two in-game banks the PS1 and PSP tone records have the same pitch (one differs in volume:
`BS16VAB1` VAG 18, 127 against 117). In the title bank the PS1 English samples play at 44.1 kHz (tone centre =
key, fine 0) while the Japanese PSP samples have centre key + 6, fine 57 (about 30.4 kHz).

`tools/voice/build_vab.py` (rules in `script/vab_voices.json`): each listed VAG is the PS1 English VAG
**verbatim**, with the PS1 English bank's tone record for it; everything else in the bank stays PSP. No
resampling or re-encoding (project decision 2026-09-30). The title bank's body grows by 27,600 bytes (157 →
170 sectors); its SPU end becomes `0x7A4D0`, exactly the PS1 English bank's, so the sound-memory footprint is
one the PS1 game itself used. The two in-game banks shrink (76 → 71 and 78 → 73 sectors).
`verify_vab.py` checks the result; with Japanese voices it checks the banks are untouched.

**Confidence:** title voices confirmed in play; the two in-game banks confirmed by check (§16).

---

## 11. Subtitles

### 11.1 What they are

The PSP version adds bottom-of-screen subtitles for voiced scenes: cutscene streams, the TV news reports and
one radio call. On the PS1 these scenes are voice only: a search of every PS1 dialogue block and of the US
executable finds no text for them (the single exception is a three-line radio call that also exists as PS1
dialogue). The Japanese text is in the program's `.data`, in the game's own font codes (not Shift-JIS or
UTF-8, which is why a plain string search does not find it).

### 11.2 Data structures

One function starts every subtitle scene: **`0x449D0(scene, set)`**.

| Set | String-table master array | Timing-table master array | Slots | Scenes |
|---|---|---|---|---|
| 0 ("A") | va `0x2607E8` | va `0x260878` | 36 | A nn = slot nn = PS1 stream `s00` rank nn |
| 1 ("B") | va `0x260908` | va `0x260998` | 36 | slots 0 and 1 hold no subtitles; **B nn = slot nn + 2** (va `0x260910` / `0x2609A0` + 4 × nn) = PS1 stream `s01` rank nn + 2 |
| 2 ("C") | va `0x260A28` | va `0x260A48` | 8 | the news reports |

Each master slot is a relocated pointer.

- A **string table** is a zero-terminated array of pointers to strings.
- A **timing table** is a list of `(start frame, duration)` `u16` pairs ended by `0xFFFF 0xFFFF`. Frames are at
  **30 per second**, measured from the start of the clip.
- A **string** is MSG-format (PSP 16-bit): `8A 00 00`, `8C` WIN (x `0x10` or `0x16`, y `0xDC`, 30 columns,
  1 row), leading `0x4F` full-width spaces for centring, the text, `8A 01 00`, `95`, `0x0000`. In PSP codes:
  `0x378 0x0000`, `0x37A` + 6 bytes, text, `0x378 0x0001`, `0x383`, `0x0000`.
- Japanese lines are centred on x = 160. The box has no frame.
- Two slots share another scene's tables in the original: A18 with A15, and B27 with B26.

Original content: 736 lines in 53 scenes (A 501, B 197, C 38).

### 11.3 English subtitles

Project decisions (2026-09-30): English lines timed to the English voice, broken at English sentence
boundaries; two-row boxes allowed; English subtitles for the news reports too.

**Where the words come from.** There is no PS1 text, so the words are those of the PS1 English voice track.
The dub was transcribed with word timings (speech-to-text on the user's own disc), then lined up against a
published transcript of the PS1 script used as a spelling and wording reference (it is not part of this
repository), and reviewed by ear where the two disagreed. The spoken dub is the authority. The result is
`script/subtitles_en.csv` (made by `research/subtitle_align.py`, with review columns that survive
regeneration). No `#` glyph exists in the font; the dub says "number", which is what is written.

**Build (`tools/build_subtitles.py`).** For every scene with English lines:

- a new timing table, string table and strings are appended to segment 2;
- the two master slots are retargeted (existing relocations, address base → segment 2);
- one new relocation is added per string pointer;
- every slot that shares the scene's original tables gets the same English tables.

| Layout constant | Value |
|---|---|
| WIN | x 16, 30 columns; 1 row at y `0xDC`, or 2 rows at y `0xD0` |
| Row width limit | 288 px, measured with the width table of §4.2 |
| Centring | on x = 160, with `0x4F` (12 px) and `0x1A6` (5 px) spaces in front of each row |
| Row break | newline code `0x374` |
| Start / duration | `round(seconds × 30)`; minimum duration 15 frames |
| A line too long for two rows | split into consecutive lines; the time is shared by width |

Result: 580 lines in 50 scenes (309 on two rows); with the shared slots, 600 lines in 52 slots.
`verify_subtitles.py` reads every scene back from the loaded program (text, timing, window, order) and
confirms that scenes without English lines keep their original tables. Scenes left Japanese: C05 and C06
(unreachable).

Brightness: the English strings use the Japanese strings' exact ops, the same font texture and palette.
Latin letters use the font's three shades in about the same proportions as kana and have about the same ink
per glyph (51 against 52 px); kanji are denser (94 px), which is why English can look lighter next to them.

**Confidence:** confirmed in play (cutscenes, two-row lines, timing against the English voice).

### 11.4 Options

- **`--subtitles=off`** (`tools/patch_subtitles.py`): one word. In `0x449D0` the test for a negative scene
  number, `bltz s1, 0x44A5C` at `0x44A38`, becomes `b 0x44A5C`, so every call takes the function's own
  "no scene" path (no tables, returns −1). Tables, voices and scenes are untouched; the word is not
  relocated.
- **`--subtitle-language=jp`**: `build_subtitles.py` is skipped; the original tables stay.
- **`--subtitle-language=en` with `--localization=text`** (English subtitles over Japanese voices): the
  English timings are used unchanged. Per scene, the Japanese and English subtitle tracks end within about
  1 s of each other in 47 of 50 scenes (the same cutscene animation; the dub was made to fit). Three scenes
  differ in length (Japanese / English end, seconds): A32 23.1 / 10.0, B08 100.7 / 69.9, A05 52.8 / 46.8.
  These have not been retimed (§16).

---

### 11.5 The band behind the subtitles (`--subtitle-background=on`, the default)

The subtitle strings carry no DECOR op (PS1 code 0x93, PSP 0x381), which is why the game draws no window box behind
them. With the option, `tools/build_subtitles.py --box` inserts `DECOR 04 04` after the WIN op, moves the window to
x 0 (its 30 columns of 12 px then run past the right edge, so the box spans the screen) and gives it one extra row,
and `tools/patch_subtitle_box.py` makes the game draw decoration type 4 without its border.

**How a window box is drawn.** DECOR takes two bytes, type and margin. The type is stored in the window context
(+0x7C) and indexes two tables of functions:

| Type | Set-up (table at vaddr `0x251BF4`) | Draw, every frame (table at `0x251C18`) | Notes |
|---|---|---|---|
| 0 | `0x432B8` | `0x435D4` | box that opens and closes in steps |
| 1 | `0x43D70` | `0x43ED0` | dims the whole screen: one plain quad, colour stepped to 0x80 |
| 2 | `0x4414C` | `0x435D4` | the ordinary box (help boxes, most windows) |
| 3 | `0x434F0` | `0x435D4` | |
| 4 | `0x4414C` | `0x435D4` | identical to type 2; **used by no string in the game data or the program** |
| 5, 6 | none | none | |
| 7 | `0x434F0` | `0x44468` | |
| 8 | `0x44230` | `0x435D4` | |

A style byte per type sits at segment 1 + `0xCDF8` (`00 FF 01 00 01 …`; types 2 and 4 are equal). Types found in
strings: 0, 1, 2, 3, 7, 8.

The set-up of types 2 and 4 (`0x4414C`; US PS1 `0x8005B85C`) takes the margin m and sets the box corners (context
+0x88…+0x96) to (x − m, y − m) and (x + 12·columns + m, y + 12·rows + m). The draw function `0x435D4` calls
`0x444B8` (at `0x4363C`) to allocate six primitives, then fills in their corners and links them into the window
layer:

- two flat semi-transparent quads (GP0 `0x2A`), the background (context +0x98, +0x9C);
- four shaded quads (GP0 `0x38`), one pixel thick, the border (+0xA0…+0xAC): top and left `0xF0F0F0` to
  `0x808080`, right and bottom `0x808080`.

Seen in the primitives of a real frame (save state 10, the options screen) and read from the code.

**Removing the border for the subtitles only.** The call at `0x4363C` (a relocated `jal`) is retargeted to 24 words
of position-independent code at the end of segment 2. It calls `0x444B8` and then, when the window's type is 4, sets
the length byte (+3) of the four border primitives to 0; such a primitive is an empty list node that the frame
walker passes over. Windows of every other type are drawn as before. No table entry is added: a new type 5 or 6
would need new data relocations, type 4 needs none.

With x 0 and m 4 the box's left and right edges are off-screen, and the extra row takes the bottom edge below the
screen (248 > 240), so the band reaches the bottom of the picture.

**Confidence:** emulated (the draw function run on the help-box context of save state 10: type 2 unchanged with and
without the new code; type 4 keeps the two background quads and loses the four border quads) and confirmed in play
(PPSSPP, 2026-10-05).

## 12. The dog scene (native stage code)

### 12.1 The scene and the regional difference

After the first visit to City Hall, Tron is stuck on a lamp post while the dog Paprika growls at her. In the
Japanese game the player can either **talk** to the dog (it then leaves) or **kick** it (it yelps and runs).
The US PS1 release removed the kick. The dialogue is the same in both games: `ST05_00.MSG` block `0x04`
(talk) and block `0x0E` (yelp) exist in both, so the difference is code only.

`--paprika=fair-game` (default) leaves the Japanese behaviour. `--paprika=good-dog` applies the US change.

### 12.2 Where the US change was found

By diffing the Japanese and US **PS1** stage programs: entry `..\PROGBIN\R3_ST05.BIN` in `ST05.BIN`, a PS1
R3000 overlay loaded at `0x80100000`. With immediates and addresses normalised the two are 99.5 % alike. In
the dog object:

| Japanese PS1 overlay | US |
|---|---|
| kick-target registration (`0x80117B44–B94`, calling `0x800340D0`, hit flags at object + `0x358`) | deleted |
| two "kicked" tests (`0x80117E5C`, `0x80117F7C`): `+0x358 & 0x20000000` → yelp sound `0xAF`, state 7 | deleted |
| wait after the talk scene: `0x8C` frames | `0xAA` frames (the English lines are longer) |

Dog state table at `0x80131C24`: state 3 = talk scene (block `0x04`), state 4 = wait then leave, state 7 =
kicked. When the player talks to the dog it goes to state 3, or straight to state 4 if flag `0x640` is set.

### 12.3 What actually runs

> **Pitfall: the PSP does not execute the PS1 overlays.** The `PROGBIN\R3_STxx.BIN` entries are still on the
> PSP disc (and the PSP's `R3_ST05` is the Japanese code), but the program contains **native ports** of the
> stage code. Patching the overlay changed nothing: the dog could still be kicked (confirmed in play). Any
> finding made in a PS1 overlay has to be located again in the PSP program before it is relied on.

The native dog code is at `0xA7D10–0xA87F8` in the program. It was identified by the same constants: hit
flags at +`0x358`, the `0x20000000` test, yelp sound `0xAF`, state 7, flag `0x640`, sounds `0x16F` / `0x171`,
and the `0x8C` wait.

### 12.4 The patch (`tools/patch_ps1_dog.py`)

Five words, none relocated (asserted), each checked against the original:

| vaddr | Original | Patched | Effect |
|---|---|---|---|
| `0xA7D10` | `lhu v1, 0x16(s0)` | `b 0xA7CE8` | skip the kick-target registration (`jal 0x20C2C` with `s0 + 0x358`), as the existing jump after it does |
| `0xA7D14` | `lhu a0, 0x18(s0)` | `move a0, s0` | delay slot of the branch |
| `0xA7ECC` | `bnez v0, kicked` | `nop` | first "kicked" test never taken |
| `0xA80F0` | `bnez v0, kicked` | `nop` | second "kicked" test never taken |
| `0xA87F8` | `sltiu v1, v0, 0x8C` | `sltiu v1, v0, 0xAA` | wait after the talk scene, as the US |

`verify_ps1_title.py` checks the words against the report, and that `R3_ST05` is the untouched original.
**Confidence:** confirmed by check; see §16 for play status.

Not included: other US/Japanese differences in the same overlay (lip-sync timings for the English lines, and
a second kickable object removed in the US, just before the drink-machine code).

---

## 13. The renderer and the wide-screen HUD fix

### 13.1 How a frame reaches the screen

The game renders its PS1-style 320 × 240 frame, **3D and 2D together**, into one offscreen image and then
pastes that image onto the 480 × 272 screen.

| Fact | Value |
|---|---|
| Screen setting flag | va `0x39FF50` (segment 1 + `0x15AD50`): 0 = Wide, 1 = Original. Written by `0x2172A8`. |
| Paste function | `0x217600–0x21781C`; reads the flag and a table at va `0x324030` of 8-byte rows (x, y, w, h) |
| Table rows | row 0 = (0, 0, 480, 272) for Wide; row 1 = (58, 0, 364, 272) for Original |
| Paste primitive | a through-mode sprite: texture u 1…`0x1FF`, v 1…`0x1DF` of the offscreen buffer (set up by `0x223BA0(0, 0x200, 0x200, 0x400)`), drawn to the table rectangle via `0x2227E0` / `0x2223D4` |
| A second mode flag | va `0x39FF4C`, with branches using 320 × 238 (TV output; inferred) |

So Wide stretches the whole 4:3 frame to 16:9 (the picture is 1.32 times too wide), and Original pillarboxes
it at x 58–422. The flag was found by diffing the RAM of two save states taken at the same spot in the two
modes. The program contains no floating-point scale constants (1.5, 480.0, …).

> **Pitfall: there is no separate HUD layer at the paste.** A first prototype assumed the 3D world was drawn
> separately at full width and only the 2D layer was pasted; it cut the paste into strips to push HUD parts
> to the screen edges. That cuts the whole picture into strips with black gaps (confirmed in play). The
> assumption came from comparing a dark scene near the screen centre, where both mappings nearly coincide.

### 13.2 The primitive list

The frame is drawn by a native **DrawOTag at `0x216F0C`**, which walks one PS1-style primitive list.

| Fact | Value |
|---|---|
| Walk loop | `0x216F80`: next = tag & `0xFFFFFF`; length byte at +3; primitive code byte at +7 |
| Pointer rebuild | the 24-bit tag is turned back into a pointer with two base words at segment 1 + `0x509668` and + `0x509678` |
| Dispatch | by code through a table at segment 1 + `0xDEE20` (polygons, lines, sprites); `E1`, `E3`, `E4`, `E5`, `E6` handled inline |
| Handlers | polygons `0x217F20`, lines `0x217C70`, sprites and tiles `0x2185E8`, clip `E3` `0x217960`, special `0x2189E4` / `0x218C28` |
| End of list | the paste, `0x217530` |
| Draw offset | segment 1 + `0x15AD58` (`u16` x), added to every primitive's coordinates |
| **x conversion** | **every handler converts x positions and widths with one function, `0x217214`** (`x × 2`: `sll v0, a0, 1; jr ra; seh v0, v0`); y uses `0x217220` |

The offscreen image has about 1.6 pixels per PS1 unit horizontally (hence the ×2 and the 512-wide buffer).

**The top-level ordering table** is 8 slots inside the structure whose address is stored at segment 1 +
`0x500800`, at offsets +`0x70` … +`0x8C`, walked from +`0x8C` down:

| Slot | Content (seen in save states) |
|---|---|
| +`0x8C`, +`0x88`, +`0x84` | backdrops (the title background uses them) |
| +`0x80` | **the 3D world** (a large depth-sorted sub-table is spliced in here) |
| +`0x7C` | **windows and text** (window boxes, glyph sprites, clip `E3`, mode `E1`) |
| +`0x78` | **HUD** (minimap, gauges) |
| +`0x74` | front |

2D and 3D are therefore cleanly separated: everything after the walker passes the +`0x7C` slot node is 2D.

Clip rectangle `E3`: the first word holds x and y, the second **width and height** (not a second corner).

### 13.3 The fix (`tools/patch_wide_hud.py`)

Goal (project decision 2026-10-01): in Wide, draw HUD, windows and text at correct proportions without
touching the game world. The exact factor is (272/240) / (480/320) = 0.756; the patch uses 3/4.

Because of the single x-conversion function, no primitive has to be rewritten: while a 2D primitive is being
drawn, the conversion returns `x × 1.5` instead of `x × 2`, and a **bias** added to the draw offset places the
result.

What is changed in the program: **24 existing `jal` instructions are retargeted** (their relocation entries
stay valid; each is asserted to be the expected relocated `jal`) to new position-independent code appended to
segment 2 (334 words including 8 state words; no relocation added).

| Retargeted call | Site(s) | New behaviour |
|---|---|---|
| DrawOTag's call of `0x2172E0` (start) | `0x216F58` | call the original, reset state, look at the first primitive |
| its call of `0x2212D8` after each primitive | `0x217018` | look ahead to the next real primitive and decide: zone, squeeze or not, bias; then tail-call the original |
| its call of `0x217530` (the paste) | `0x217198` | squeeze off, bias removed from the draw offset, then the original |
| the handlers' calls of `0x217214` | 20 sites, `0x217D34` … `0x218B4C` and `0x217A08` (the `E3` width) | `x × 1.5` while squeezing, else `x × 2` |
| the `E3` left-edge call | `0x2179F0` | `(x + bias) × 1.5` while squeezing (clip positions do not use the draw offset) |

Decision rules for the next primitive:

1. The zone is 0 until the walker passes the +`0x7C` node (1 = windows/text), then 2 at +`0x78` (HUD), 3 at
   +`0x74`. Zone 0 is never squeezed.
2. Nothing is squeezed unless the Screen flag is 0 (Wide).
3. A primitive or clip rectangle **300 or more units wide** is left alone (fades, full-screen backdrops).
4. Otherwise squeeze, with bias **53**: `0.75 × (x + 53.3) = 160 + 0.75 × (x − 160)`, a squeeze about the
   screen centre.
5. With `--hud=edge`, in the HUD zone only:
   - a piece wholly left of x 80 keeps to the left edge (bias 0); a piece wholly right of x 240 keeps to the
     right edge (bias 107); everything else is centred, so banners and the title's PRESS START line stay in
     one piece;
   - only while the world slot has primitives: menus, which draw no world, are centred as a whole;
   - one look over the HUD slot when it starts: if its middle pieces are joined exactly to pieces in both
     edge bands (an unbroken layer of tiles, as cutscene overlays are: 352 semi-transparent 32 × 32 tiles in
     one state), nothing in the HUD slot is squeezed that frame.
6. The bias is re-applied after an `E5` (draw-offset) primitive.

`--hud=center` uses rules 1–4 and the tile rule; `--hud=off` changes nothing.

An earlier per-piece rule (left / centre / right by thirds of the screen) tore banners, menus and overlays
apart; the band rules above came from save states of those cases.

**Check.** `research/verify_wide_hud.py` (a separate command; needs the `unicorn` emulator package and
save states) runs the new code in a MIPS emulator over the real primitive lists in 13 save states, both
variants and both Screen settings, and compares every primitive's squeeze/bias decision and the draw offset
with a Python model. In Original mode nothing is squeezed; the world slot is never squeezed.

**Confidence:** the layout was confirmed in play in the emulator for the first `edge` version, whose problems
(title, cutscene overlays, mission banner, item menu) led to the rules above; the reworked rules are confirmed
by the emulation check. See §16 for what is still unknown.

---

### Variant `hudonly` (`--hud=hud-only`, project decision 2026-10-02)

Squeezed text is harder to read (a 12-unit glyph gets about 13.5 screen pixels instead of 18, at a non-integer ratio),
most of all on real hardware. This variant applies the `edges` rules to the HUD slot (+0x78) only, and only while the
world slot has primitives; the windows-and-text slot (+0x7C), the front slot (+0x74) and whole-screen menus are left
at the game's own proportions. In code it is the `edges` routine plus six instructions at the start of the decision
(`tools/patch_wide_hud.py`, `FLAGS`: bit 0 = edge anchoring, bit 1 = HUD slot only); `center` and `edges` assemble to
the same words as before. Checked by emulation on the 13 save states; not yet confirmed in play. Known consequence:
text-like art that the game draws in the HUD slot (the title's PRESS START line, mission banners) is still corrected.

### HUD slot: runs of covered columns (2026-10-02, replaces the per-piece band rule)

Play showed two faults of deciding piece by piece: a boss life bar longer than the right band was centred while its
icon stayed at the right edge, and on the weapon development screen the stat panel and the frame around the weapon
preview were pulled apart. Since then the HUD slot is looked over once per frame (`prescan`) to mark which 8-unit
columns of the 320-unit width its pieces cover (40 bits, pieces 300 or more units wide excluded). Pieces that touch or
overlap in x form a run of set bits, and every piece takes the decision of its run:

| Run | Result |
|---|---|
| covers all 40 columns (tiled cutscene overlay) | not squeezed |
| no world primitive this frame (menus) | squeezed, centred |
| starts left of x 80 and ends at or before x 240 | "left" |
| ends right of x 240 and starts at or right of x 80 | "right" |
| anything else (mission banners, the title's PRESS START line) | squeezed, centred |
| left or right, and more than 160 units wide | not squeezed: a panel framing world-drawn content (the weapon preview is a 3D view, which is never squeezed, so its frame must not be either) |
| left or right otherwise | bias 0 / 107 with edge anchoring (`edges`, `hudonly`), centred without (`center`) |

y is ignored, so two objects that share columns count as one run. Established from 21 save states (in-game HUD, boss
fights with short and long bars, banners, title, cutscene overlay, item and pause menus, weapon development) and
checked by emulation on all of them; the boss-bar and development-screen results are not yet confirmed in play.

### Switching the fix off and on in the options screen (project decision 2026-10-02)

Present with every `--hud` variant except `off`. On the options screen, with the Screen row highlighted and set to
Wide, Triangle switches the adjustment off or on; the help box shows a second row, "(triangle) HUD Size: Corrected" or
"... Default" (label in text colour 3, the light green of the weapon development labels; first wording was "HUD Adjustment: On / Off") (new text, approved; there is no PS1 equivalent).

Facts used (static analysis, then a save state of the options screen; the routine was run in an emulator on that
state; not yet confirmed in play):

| Fact | Where |
|---|---|
| The Screen setting is one byte: 0 = Wide, 1 = Original | segment 1 + 0x2D2618 (system struct 0x2D25C0 + 0x58); registered at 0x698, read by 0x2190C0, result stored in the renderer's flag (segment 1 + 0x15AD50) at 0x2172A8 |
| The options screen is run by the text engine's selection handler | 0x3ED60–0x3F0C0; `s0` = window context; newly pressed pad bits at +0xBA, held at +0xB8, PS1 layout (0x10 up, 0x40 down, 0x80 left, 0x20 right, 0x2000 circle, 0x1000 triangle) |
| Option variables are reached through a pointer table | segment 1 + 0xFBA8; entries 2–7 = the six option bytes (+0x54, 55, 57, 59, 56, 58) |
| The handler shows the highlighted choice's help text every frame | `jal 0x3C00C` at 0x3EE18 (relocated), a1 = string from the system-message table (segment 1 + 0xF31C) |
| Help text of Screen = Wide | system message 242; its window op already allows 2 rows |

`tools/patch_wide_hud.py` retargets that one call to a routine (`opt`) in the HUD-fix block: if a1 is entry 242's
string and Triangle is newly pressed, it flips a state word (`HUDOFF`), clears the pad bit and plays menu sound 0x82
through 0x7728 (what the handler itself does when a choice changes); it then passes one of two copies of the string,
each with the extra row, on to 0x3C00C. The squeeze decision tests `HUDOFF` next to the Wide test. The word lives in
the program's memory only: the adjustment is on again after a restart and nothing in the save data changes. Whether
the struct at 0x2D25C0 is written to the save file, and whether it has a byte the original game never reads, was not
established; persistence is therefore not implemented.

## 14. PSP menu and save data (icon, save picture)

### 14.1 The files

| File | Original content |
|---|---|
| `PSP_GAME/ICON0.PNG` | 144 × 80 menu icon; **byte-identical to `DAT/PICT/savepic.png`** |
| `PSP_GAME/ICON1.PMF` | 26 s animated icon (144 × 80 video of the Japanese logo, no audio stream) |
| `PSP_GAME/PIC1.PNG` | 480 × 272 menu background, no text |
| `PSP_GAME/PIC0.PNG` | 310 × 180 overlay with a Japanese tagline and the copyright line |
| `PSP_GAME/SND0.AT3` | menu preview sound |
| `USRDIR/DAT/PICT/savepic.png` | 144 × 80 RGB, 26,087 bytes (13 sectors): the picture stored with each save |
| `USRDIR/DAT/PICT/emptypic.png` | the "new data" picture (already reads "New Data" in English) |

### 14.2 What `--localization=legends` changes

| Item | `text` / `audio` | `legends` |
|---|---|---|
| Menu name (`PARAM.SFO` `TITLE`, §7.8) | Rockman DASH: Hagane no Boukenshin | Mega Man Legends |
| Save name (slot `0x26335C`, §7.7) | Rockman DASH: Hagane no Boukenshin | Mega Man Legends |
| `savepic.png` and `ICON0.PNG` | original | new picture (below), written in place |
| `ICON1.PMF` | original | removed: its directory record is taken out and its sectors zeroed (not reused), so the menu shows the still icon |

Unchanged in both: `PIC1.PNG` and the save identity.

**In every build (2026-10-05):** `PIC0.PNG` loses its Japanese tagline and `SND0.AT3` is removed.
`PIC0.PNG` holds the tagline in rows 130–158, its drop shadow fading out by row 165 (opacity at most 52/255 in
row 160, 13 in row 163, 5 in row 164), and the copyright line in rows 164–173. `tools/build_xmb.py` makes rows
0–163 transparent and keeps the rest pixel for pixel; nothing is drawn. It edits only the known file (SHA-1
`073fba44f134a8e15dce7f113505ec2bb501a100`, identical in the PSN and UMD images) and must fit the original's
sectors (13,228 → about 2.7 KB). `SND0.AT3` (101,804 bytes) is removed like `ICON1.PMF`: directory record taken
out, sectors zeroed. No replacement picture or music is added (decision: no artwork is added to the package).
Not yet seen on a PSP's menu.

**The new picture** (`tools/build_savepic.py`) is made only from PS1 disc textures, decoded with their own
palettes; nothing is drawn or generated: the PS1 title background as the PS1 draws it (`NTITLE3U` texels
0–160, the same mirrored, with the subtractive fade over the bottom 16 rows; 320 × 160) scaled to 160 × 80
with the middle 144 columns kept, and the PS1 logo cropped to its drawn pixels, scaled to 132 px wide and
centred (Lanczos). Limits: it must fit the original's sectors (≤ 26,624 bytes) and the game's 30,000-byte
buffer. It is about 22.4 KB; its exact bytes depend on the imaging library version.

### 14.3 The save-picture buffer

| Fact | Value |
|---|---|
| Picture buffer | segment 1 + `0x111D48`, 30,000 bytes (`0x7530`); `savepic.png` is read into it once at start (`0x4F728`) |
| Save setup | `0x4F698`: hands that buffer to the save utility as the save's ICON0 |
| Load setup | function `0x4F370`: hands the **same** buffer to the utility as the place to load the chosen save's ICON0 into (parameter block +`0x584` buffer, +`0x588` size) |
| Spare buffer | segment 1 + `0x119278` (= `0x111D48 + 0x7530`), 30,000 bytes, set up by the same code as the ICON1 load buffer (+`0x594` / +`0x598`); saves have no ICON1, so it is unused |

> **Pitfall:** after any save has been loaded, the picture buffer holds *that save's* picture, and every later
> save writes it back. In the original game all pictures are identical, so it never shows. With a new
> picture, loading a save made by an older build brings the old picture back for all saves made afterwards
> (confirmed in play).

Fix (`tools/patch_psp_menu.py`, `legends` only): the load setup uses the spare buffer instead. Three words,
none relocated:

| vaddr | Original | Patched |
|---|---|---|
| `0x4F464` | `sw v0, 0x584(s2)` | `nop` |
| `0x4F47C` | `sw v1, 0x594(s2)` | `sw v1, 0x584(s2)` (`v1` already holds the spare buffer's address) |
| `0x4F480` | `sw a1, 0x598(s2)` | `nop` |

The size at +`0x588` is still set at `0x4F48C`. A save's picture and name are stored in the save when it is
written, so saves from earlier builds keep the old picture until saved over.
**Confidence:** confirmed in play (new saves and overwrites carry the new picture; old saves still load).

---

## 15. Packing the ISO and the checks

### 15.1 Principle: copy the image, patch in place

`tools/pack_inplace.py` copies the original image byte for byte and then changes only what it must. No file
moves unless it no longer fits (§2.2 explains why).

Inside each `DAT/*.BIN` it walks the entries and applies, by entry path:

| Source | Action |
|---|---|
| `build/msg_psp/<BIN>/<path>` | replaces an MSG entry (header size/sector fields from the new file; entries after it shift); the load address is set to the moved buffer's (§6.4) |
| `build/tex_psp/<BIN>/<path>.pix` | writes pixel bytes into a non-type-10 entry; asserts the data does not reach a following header |
| `…​.hdr` | writes header bytes `0x100–0x800` (palettes), also into a type-10 twin |
| `<dir>/<BIN>/<path>.head` (title option) | replaces the whole 0x800-byte entry header (type, name and sector field must be unchanged) |
| `<dir>/<BIN>/<path>.insert` (title option) | inserts whole entries right after this entry, before the next header |
| `build/vab_psp/<BIN>/<path>` (English audio) | replaces a VAB entry as a whole (the old entry must end at a header or at the `0xFFFFFFFF` terminator) |

Then: the BIN's directory record (length, and LBA if moved; both byte orders) and its entry in the program's
file table (§2.2) are updated.

Other in-place writes: `PARAM.SFO` (same size), `savepic.png` and `ICON0.PNG` (within their own sectors;
directory size updated), `.at3` files by path.

### 15.2 Files that no longer fit

A file that outgrows the space before the next file is given a new place by a small allocator (`Alloc`):

- every slot a file leaves is zeroed, merged with neighbouring free slots and offered for reuse (best fit);
- with English audio, the dropped Japanese voice files' sectors are freed first, together with the all-zero
  gap up to the next extent of any kind, so each folder becomes one large free block;
- only what does not fit a freed slot goes after the original image end (16-sector aligned), and the volume
  size in the primary volume descriptor (sector 16, +80 / +84) is updated.

The flattened program (about 8.6 MB) never fits its 4 MB slot and is always moved; its `SYSDIR` directory
record gets the new LBA and size. The original image's own unused runs (§2.3) are not used.
`manifest.json` records every replaced, moved, inserted and dropped item.

**Confidence:** relocation of BINs, of audio files and of the program confirmed in play (emulator and
hardware).

### 15.3 Adding a directory

The English voice folder `at3/xaen` is the only new directory. To avoid renumbering anything it must sort
after every sibling and its parent must be the last parent in the path table (both asserted). Then: its
record is appended to the parent's extent; one entry is appended to each of the four path tables (L, optional
L, M, optional M); the path-table size in the volume descriptor is updated. Directory and file records copy
the layout of existing ones (including the system-use area). `verify_layout.py` checks the result.

### 15.4 Order of the program patches

All program patches work on `build/eboot/ULJM05030_EBOOT_en.BIN` in this order (`build.py`):

1. `patch_eboot.py`: variable-width text, title-menu immediates, moved text buffers (same size as the input)
2. `build_sysmsg.py`: creates segment 2 (system messages, banner lists)
3. `build_savetext.py`, `patch_psp_menu.py`, `patch_wide_hud.py`, `patch_ps1_dog.py`, `patch_subtitles.py`,
   `patch_ps1_title.py`: each appends to segment 2 if needed and patches code words
4. `build_subtitles.py`: appends to segment 2 and adds a relocation section
5. `tools/voice/patch_eboot_voice.py`: adds segment 3 and its relocation section (must run after every step
   that grows segment 2)
6. `pack_inplace.py`: file-table updates, then flattening (§5.5)

Every patch asserts the original instruction or value first and stops if it differs, so a different game
version cannot be patched silently.

### 15.5 The checks

Run by `build.py` after packing; each stops the build on a problem.

| Check | What it proves |
|---|---|
| `verify_voice_eboot.py` | the loaded program resolves every Japanese and English voice id, and the five news ids, to the expected path |
| `compare_loaded.py` | the flattened program loads to exactly the same memory as the unflattened one |
| `audit_eboot.py` | every changed word belongs to a known patch; every added byte is reached by a relocated pointer (or is declared code/templates); lists file bytes nothing refers to |
| `verify_subtitles.py` | every English subtitle line read back (text, timing, window); other scenes untouched |
| `verify_savetext.py` | every save-screen string through its slot; save identity strings unchanged at the same addresses |
| `verify_ps1_title.py` | title, menu-picture and dog options as built, or untouched; `R3_ST05` original |
| `verify_voice.py` | every AUDIO op in the built text names an existing clip for the audio mode |
| `verify_msg_args.py` | no non-zero pad in the Japanese data; every block parses; special ops (E2 E4 EC B9 CE E9, A3 AB) match the Japanese |
| `verify_headers.py` | every container entry header unchanged except the allowed fields; untouched entries' data identical |
| `verify_sfo.py` | only `TITLE` changed in `PARAM.SFO` |
| `jp_audio_audit.py` + `verify_dropped.py` (English audio) | nothing dropped is reachable; streams and English clips present |
| `verify_vab.py` | sound banks: listed VAGs equal the PS1's, everything else the PSP's; or untouched |
| `verify_layout.py` | no two extents overlap; everything lies inside the volume |
| `verify_slack.py` | every byte written past an in-place file's original end was zero on the original image |
| `verify_sysmsg.py` | all 248 system-message slots resolve to strings that end properly |

Separate commands (need extra packages and save states): `savestate_check.py` (§6.4) and
`verify_wide_hud.py` (§13.3).

**Reproducibility.** The same inputs and tool versions give a byte-identical ISO; a build in an empty folder
from the published files alone reproduced the reference image. Two things can change the bytes without being
errors: how atracdenc was compiled (the encoded audio; a Mac and a Linux build differed in 724 of 740 files,
2026-10-05) and the imaging library version (the save picture and menu overlay PNGs).

---

## 16. Open questions and unverified points

### 16.1 Not yet confirmed in play

| Item | Status |
|---|---|
| US name/artwork textures of the `legends` set (TV-station signs, vending machines, reporter, room props, Servbot faces, trunk, comic, Flutter map) | built and header-checked; not seen in play. The Servbot-face texture was not viewed before swapping. |
| `--paprika=good-dog` in its final form (native code patch) | checks pass; no play result recorded |
| `--subtitles=off` | checks pass; no play result recorded |
| English subtitles over Japanese voices (`--localization=text`) | built; not seen in play. Scenes A32, B08 and A05 differ in length between the two voice tracks and probably need retiming. |
| The reworked `--hud=edge` rules | emulation check only. Unknown: whether 2D markers tied to world positions (lock-on, pickups, damage numbers) sit in the HUD slot and shift; what exactly was wrong with boss text boxes in the first version (a state with the text showing is needed); behaviour on hardware, where the new code runs from the added data area. |
| News reports with English audio **and** English subtitles | resolved by check; no play result recorded for the final mechanism |
| The two in-game sound banks (`BS16VAB1`, `ST1A_02B`) | which scenes use them was not identified; not heard in play |
| Long streams at 1864-byte frames (the 12.6 MB opening) and the replacement of the plain-ATRAC3 opening stream by an ATRAC3plus file | cutscenes work in play; this specific file is not recorded as checked |
| The longer save title on hardware | fits the utility's 128-byte field; display not recorded as checked |
| Loading a save from the unmodified Japanese game in the English build, and the reverse | not recorded as tested. Open point: whether a save contains raw PS1-style RAM overlapping the moved text buffers (`0x80060000–0x80088000`). |
| Text-buffer destination in the Flutter interior, City Hall and the support-car menu | no save state from these places; play there shows no problem |
| The save-state evidence | the six original-game states were later replaced by other states; `savestate_check.py` needs fresh states of the original game to be re-run |
| Windows build | written for, not run; macOS builds and patches (2026-10-05); output bytes differ between platforms |
| Hardware other than a PSP Go with ARK-5 | untested. If a firmware refuses the unsigned program, it would need signing. |

### 16.2 Inferred, not verified against code

- PSP-only argument lengths `92` (1), `A3` (2) and the `AB` MULTI variant come from the data, not from the
  PSP text engine. The data parses cleanly and the Save menu works in play.
- The meaning of the option-row op `AD`'s extra bytes (§7.3) is read from the data.
- `0x8015BC00` / `0x8015BD00` being event-flag bit arrays.
- The developer screen behind system string 1 being unreachable.
- The six title-call sound pairs being program 6 of the title bank (they were identified by listening to that
  program's samples; the mapping from the queued sound numbers `0x1C7…` to the program was not traced).
- VAB tone fine-tune units (1/128 semitone assumed) only mattered for a resampling path that is no longer
  used.
- Slot +`0x74` of the ordering table ("front") has not been seen in use.
- The widths of the fields in the banner sprite records (§7.6); the lists are copied verbatim, so the build
  does not depend on them.
- Type-2 sound ids resolving through bank-table slots `0x33` / `0x34` follows from the table addresses
  (`0xA930 = 0xA864 + 4 × 0x33`); it was not traced in the play function.
- Header field +`0x0C` of TIM entries (compared, never interpreted) and the meaning of entry types other than
  0, 1, 3, 5 and 10.

### 16.3 Conflicts between the sources

Where the sources disagreed, the scripts' current code was preferred. These are the disagreements found:

| Topic | Values | Used here |
|---|---|---|
| Set-1 ("B") subtitle master arrays | `0x260910` / `0x2609A0` in the review tooling; `0x260908` / `0x260998` with "B nn = slot nn + 2" in the build and checks | the latter (both describe the same slots) |
| News subtitle set | "no timing table" in an early note; timing master at `0x260A48` in the build | has timing tables |
| Second PRESS START / copyright palette word | `0x25E8` in one note; `0x25F8` in `patch_ps1_title.py` | `0x25F8` |
| Difficulty quad code | "from `0x2A3C`" in the notes; "`0x2AEC`" in `build_title.py`'s header | `0x2A3C` as the start; `0x2AEC` is probably the u selection inside it |
| English `STFF_FE.MSG` size | 23,716 and 23,756 bytes | 23,716 (the more frequent figure); both are under the `0x8000` limit |
| Space for support text at `0x801E4000` | "about 38.5 KB (code uses `0x801ED6C0` onward)" and "27,914 bytes (other data from `0x801EE000`)" | neither; both are below the 47,548 needed, so the conclusion is the same |
| Size added by flattening | "about 5.4 MB" in `flatten_eboot.py`'s header; the built file is about 8.6 MB against 4.16 MB, and `.bss` is about 4.4 MB | about 4.4 MB |
| Number of Japanese voice folders / clips | "16 voice folders" in one note, but two of the 16 used bank slots are the stream lists (14 voice banks), and an early list names 13; clip counts of 917 (early), 864/865 table paths (795 voice + 69 streams), and 846 files dropped from `at3/xa18m*` | 795 referenced voice-clip paths, 846 files on disc. The difference (files not in the path table) was not examined. |
| Streams replaced by English | 47, 48 and 49 at different times | 49 (the latest audit) |
| When `patch_ps1_dog.py` runs | "after `patch_ps1_title.py`" in its header; `build.py` runs it before | `build.py`'s order (the two patches touch different words, so the order does not matter) |
| Relocation count | one note says 102,839 relocations in total; `.rel.text` + `.rel.data` at the sizes the scripts use hold 97,113 entries | not stated in the text; the program may have further relocation sections |
| `script/opcode_args_exe.json` note | says `ED` "converts to PSP char `0x00FD`" | `0x10C` (`msgtool.py`) |

### 16.4 Known gaps

- The `*` of the review marker has no glyph and shows as a middle dot.
- Program text outside the system-message table, the save-screen strings and the subtitles has not been
  surveyed exhaustively; a sweep of every live MSG-format and UTF-8 string found only the developer legend
  (kept), the unreachable news scenes C05/C06 and an unused leftover save title.
- `PIC0.PNG`: the Japanese tagline is removed in every build (§14); the result has not been seen on a PSP's menu yet.
- Three kanji codes in the analysis table are tentative (`0x11B`, `0x144`, `0x284`); they affect only the
  reading of Japanese text during analysis.
- 65 lines of the reference transcript matched nothing in the English voice track and have no subtitle (most
  are not in the dub); 7 heard fragments were dropped as unclear.
- In the Japanese-voice build, the placement of clips in the 293 time-matched blocks is automatic and was
  reviewed only where it looked wrong.
