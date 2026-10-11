# Building the English version of Rockman DASH (PSP)

This guide explains how to build an English version of the Japanese PSP game **Rockman DASH: Hagane no Boukenshin**
(ULJM05030) from your own copies of that game and of the English PS1 game **Mega Man Legends** (USA). The script,
voice audio, textures and font glyphs come from the PS1 disc. Your original disc images are only read, never modified.

- Sections 1 to 3: what you need, how to build, how to test.
- Section 4: what each build step does.
- Formats, addresses and mechanisms are documented in [RESEARCH.md](RESEARCH.md); this guide points to its sections
  as "RESEARCH §N".
- Third-party tools and their licences: `THIRD_PARTY.md` and `LICENSES/` in the repository root.

No game data is included in the repository, and none may be added to it.

---

## 1. What you need

| Item | Where it goes | Notes |
|---|---|---|
| Mega Man Legends (USA), PS1, `.bin/.cue` | `originalDiskImages/ps1/` | Only Track 1 (data) is read. |
| Rockman DASH (Japan), PSP, `.iso` | `originalDiskImages/psp/` | Game ID ULJM05030, v1.01. The PSN release or a retail UMD dump. |
| Python 3.10 to 3.14 | | `python3 --version` (Windows: `python --version`). Not 3.15 yet: pyeboot has no Windows package for it, so pip would try to compile it. |
| Python packages | | `pip install -r requirements.txt` |
| atracdenc | compiled automatically, or `bin/<platform>/`, or `ATRACDENC=` | Needed for English audio. See below. |
| PPSSPP | | For testing. Version 1.20 was used. |

`research/requirements.txt` lists extra packages that only the optional tools in `research/` need.

### Disc image file names

The file names must match exactly (they are set in `tools/inputs.py`):

- `originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin`
- `originalDiskImages/psp/Rockman Dash - Hagane no Boukenshin (Japan) (PSP) (PSN).iso` (PSN release), and/or
- `originalDiskImages/psp/Rockman Dash - Hagane no Boukenshin (Japan).iso` (retail UMD dump)

SHA-1 of the images the build was verified with (`sha1sum <file>` on Linux, `shasum <file>` on macOS):

```
904489e2e8d06e1c44e60d8925329f9472b2d037  Mega Man Legends (USA) (Track 1).bin          (matches Redump)
8b42aca00d3b37dfbccae53adbce851256b27763  Rockman Dash - Hagane no Boukenshin (Japan) (PSP) (PSN).iso
c69d24a081c065c1eaa9d9828490e55f60ed5ee0  Rockman Dash - Hagane no Boukenshin (Japan).iso (UMD)
```

### Choosing the PSP base image

You can pass a path to the image on the command line (section 2). The image is identified from its contents, not
its name: game ID and version from `PARAM.SFO`, PSN release or retail UMD from `SYSDIR/BOOT.BIN` (blank on the PSN
release). Without a path, the only `.iso` in `originalDiskImages/psp/` is used, or the PSN release if there are
several. The extract step prints what it found and whether the image's CRC32 is a known one:

| CRC32 | Image | Notes |
|---|---|---|
| `C2E6D0B9` | PSN release (316,735,488 bytes) | Known good. `BOOT.BIN` and the firmware-update folder are zero-filled. |
| `78DFD145` | Retail UMD, full size (316,735,488 bytes) | Known good (Redump size). |
| `17F6EDE5` | Retail UMD, one sector short (316,733,440 bytes) | A known underdump: the last, empty sector is missing. Content intact; the build output is unaffected. |

Both releases contain identical game files (the program and every data file, at the same disc positions). They
differ only in `PSP_GAME/SYSDIR/BOOT.BIN` and `SYSDIR/UPDATE/*`, which the build never touches. A build made from a
UMD image therefore keeps the retail disc's firmware update and its `BOOT.BIN`, an unencrypted copy of the original
Japanese program. PSP firmware and PPSSPP start `EBOOT.BIN` (the patched one); a loader that starts `BOOT.BIN`
instead would run the unpatched Japanese game.

If your image differs from these, the build may still work, but the fixed addresses in the tools may not match.
Every patch checks the original instruction first and stops if it differs.

### atracdenc

The ATRAC3plus encoder atracdenc is included as source in `src/atracdenc/` (LGPL; the project's one change is
described in `src/atracdenc/MODIFICATIONS.md`). `build.py` looks for the program in this order:

1. the path in the environment variable `ATRACDENC=`;
2. `bin/<platform>/` (release zips carry a compiled copy there);
3. the PATH;
4. otherwise it compiles `src/atracdenc` into `bin/<platform>/` on first use.

Compiling needs cmake (`pip install cmake` works) and a C++ compiler. Linux and macOS also need libsndfile's
development files (`apt install libsndfile1-dev` / `brew install libsndfile`), which the program also needs to run.
Windows needs the Visual Studio Build Tools with the "Desktop development with C++" workload and, in addition, the
individual component "C++ ATL for latest build tools (x86 & x64)": atracdenc's Windows audio code includes
`atlbase.h`, which the workload alone does not install. The ATL must be the one for the compiler in use, not an older
toolset's (for example v141).
Extra cmake arguments can be given in `ATRACDENC_CMAKE_ARGS` (for example `-DCMAKE_PREFIX_PATH=/opt/homebrew`).

### Platforms

`build.py` and the tools are plain Python; external programs are found through `tools/exttools.py`. The build has
been verified on Linux (Ubuntu 22.04, aarch64) and on macOS (Apple Silicon; the packaged patcher was built there and
its result played on a PSP Go). On Windows (x64) the packaged patcher was built and patched a retail UMD image with the default options (see section 8). `--localization=text` does not need atracdenc. No build needs FFmpeg: the PS1 audio is decoded and resampled by
`tools/voice/xa.py` (numpy).

---

## 2. Build

```bash
pip install -r requirements.txt
python build.py mybuild                              # default base image, default options
python build.py mybuild path/to/RockmanDASH.iso      # a specific base image (PSN or UMD, detected)
```

General form: `python build.py <tag> [options] [iso]`. The tag names the output folder.

### Options

| Option | Values (default in bold) | What it does |
|---|---|---|
| `--localization=` | `text`, `audio`, **`legends`** | How much of the US PS1 game goes in. See the table below. |
| `--hud=` | `off`, `center`, `edge`, **`hud-only`** | Corrects the proportions of the HUD, windows and text in the Wide screen mode, where the game stretches its whole 4:3 frame. The game world is not touched. `off`: no change. `center`: everything is narrowed about the screen centre. `edge`: the same for windows and text; HUD pieces at the left or right keep to that screen edge. `hud-only`: the edge rules, but only the HUD is corrected, and only while a game world is drawn; windows, text, subtitles and menus keep the original proportions. |
| `--paprika=` | `good-dog`, **`fair-game`** | The lamp-post scene's dog. `fair-game`: unchanged from the Japanese game (the player can talk to the dog or kick it). `good-dog`: the kick is removed, as in the US PS1 release. |
| `--subtitles=` | **`on`**, `off` | The PSP version's subtitles in voiced scenes. `off` disables them; voices are unaffected. |
| `--subtitle-language=` | **`en`**, `jp` | `en`: English subtitle lines at the timings of the English voice clips. `jp`: the original Japanese subtitles and timings stay. |
| `--subtitle-background=` | **`on`**, `off` | A dark band behind the English subtitles, across the screen (the game's own window box, drawn without its border). |

`--localization` values:

| Value | Result |
|---|---|
| `text` | English text and the text-bearing textures (weapon labels, prologue pages, maps, mission banner, title menu options). Japanese voices, the PSP title screen, and the PSP menu name and save name "Rockman DASH: Hagane no Boukenshin". |
| `audio` | `text`, plus all English audio from the PS1 disc. |
| `legends` | `audio`, plus the PS1 title screen, the PSP menu name and icon and the save name and picture as "Mega Man Legends", and the US name and artwork textures. |

`--localization` never changes the dog scene; that is `--paprika` only.

**HUD toggle in the game.** With every `--hud` value except `off`, the correction can be switched off and on in the
game: on the options screen, with the Screen row highlighted and set to Wide, press Triangle. The help box shows
"HUD Size: Corrected" or "HUD Size: Default". The setting is held in memory only: it is not saved, and the
correction is on again after a restart.

**Graphical patcher.** `python gui.py` is an alternative front end to the same build.

### Output

- `build/test/<tag>/RockmanDASH_EN_<tag>.iso`
- `build/test/<tag>/manifest.json`: the base image used, the options, every dialogue file replaced, any file kept
  Japanese and why, and every data file changed.
- Check reports in the same folder (`audit_eboot.txt`, `verify_sysmsg.txt`).

`build.py` runs the steps of section 4 in order, runs the checks of section 5, and prints the ISO's MD5 at the end.
The log shows a short heading whenever the kind of work changes ("Text", "Audio", "Checking", ...) and ends with
"All checks passed."
Any step or check that fails stops the build. The first build with English audio extracts and encodes all audio,
which takes a few minutes; the results are cached under `build/` for later builds.

Builds are reproducible: the same inputs and options give the same ISO on the same platform. Two things can change
the bytes without being errors: how atracdenc was compiled (the audio files) and the Pillow version (the save picture
and the PSP menu overlay PNGs).
For that reason no expected MD5 is published; the checks of section 5 are what confirms a build.

---

## 3. Testing

### PPSSPP

Load the built ISO and start a new game. Useful things to look at:

| Area | What to check |
|---|---|
| Title screen | Menu options and difficulty names in English. With `legends`: the PS1 logo and background. |
| Opening | The prologue pages are in English. |
| Dialogue | Text fits its boxes, with variable-width letters; choices lead to the matching reply. |
| Button prompts | Plain face-button symbols; the lock-on prompt names L+R. |
| Pause menu and sub-screens | All entries in English; item, part and weapon screens work, including sorting and backing out. |
| Options screen | Columns aligned; each choice shows its help line; the Triangle toggle (section 2). |
| Save / load screen | English text; with `legends`, the "Mega Man Legends" name and picture on new saves. |
| Ruin missions | The mission start and complete banners are in English. |
| Voiced scenes | Voices and subtitles as chosen by the options. |

### Real PSP

The build's `EBOOT.BIN` is a plain, unsigned program. It runs in PPSSPP and on custom firmware; it has been tested
on a PSP Go with ARK-5. Other hardware and firmware are untested (section 8).

Saves keep the game's original identity (ULJM05030), so the PSP treats them as saves of the original game. A save's
name and picture are stored when it is written: saves made by an earlier build or option set keep the old ones
until they are saved over.

---

## 4. The steps in order

`build.py` runs these scripts in this order. Each can also be run on its own, in the same order. The arguments shown
as "internal" are set by `build.py` from the public options.

### 4.1 Plain program: `tools/plain_eboot.py`

The game's program (`PSP_GAME/SYSDIR/EBOOT.BIN`) is encrypted on the disc. The patch tools work on a plain ELF copy,
which this step writes to `decrypted_eboot/ULJM05030_EBOOT.BIN` from your own image. This file is never published.
Sources, in this order:

1. the file already exists (an earlier run, or a PPSSPP dump): it is checked and kept;
2. a retail UMD image: `SYSDIR/BOOT.BIN` is the plain program and is copied;
3. the PSN release: `EBOOT.BIN` is decrypted with the `pyeboot` Python package (in `requirements.txt`).

All three give the same ELF (4,162,891 bytes, SHA-1 `f615a7040cf809be784780eedb02e3f2c5769235`).

**Fallback: dump with PPSSPP.** Only needed if `pyeboot` cannot be installed and you have only the PSN release.

1. In PPSSPP, open Settings → Tools → Developer tools and turn on "Dump decrypted EBOOT.BIN on game boot".
2. Boot the original Japanese ISO up to the title screen, then close it.
3. File → Open Memory Stick, go to `PSP/SYSTEM/DUMP/`, and copy the dumped file (`ULJM05030.BIN` or similar) to
   `decrypted_eboot/ULJM05030_EBOOT.BIN`.
4. Turn the setting off again if you like.

A dump carries a few unused bytes after the ELF; the tools ignore them. See RESEARCH §5.

### 4.2 Extract: `tools/extract.py`

Reads both disc images and writes the English PS1 dialogue files to `extracted/ps1/`, the Japanese PSP ones to
`extracted/psp/`, plus the PSP font and the US executable. It also prints the base image's identification
(section 1). See RESEARCH §2 and §1.4.

For the audio steps, `tools/voice/extract_voice_en.py` (English clips and, for English audio, cutscene streams) and
`tools/voice/jp_clips.py` (Japanese clip list) run here once; their results are kept in `build/voice_en/`.

### 4.3 Script: `tools/build_text.py`

For every text block in every PSP dialogue file, the English PS1 block at the same position is converted to the
PSP's 16-bit format by `tools/msgtool.py`: characters, control codes and their arguments, symbols and button icons.
The character table is `script/ps1_charmap.tbl`; argument lengths come from `script/opcode_args_exe.json`.

- PSP-specific control prompts follow the Japanese PSP text (for example L+R instead of the PS1's R2).
- PSP blocks with no English at the same position are filled according to `script/fill_rules.json`.
- Approved formatting edits to PS1 lines are listed in `script/text_edits.json`; the build stops if an edit does not
  match or is never used.
- Voice commands in the text are rewritten for the chosen audio (internal argument set by `build.py`): with
  Japanese voices, the English text calls the Japanese clips, placed by `tools/voice/voice_map.py`
  (`script/voice_map.json`); with English voices, each clip number is moved to the bank slot that holds the English
  clip.

Output: `build/msg_psp/` and `logs/build_text_report.md`. See RESEARCH §3 and §10.3.

### 4.4 Title menu words: `tools/build_title.py`

The title-menu words are a texture. The PS1 words are re-spaced to fit and written into the PSP texture; the patched
title code (4.8) draws them. Runs for every localization. Output under `build/tex_psp/`. See RESEARCH §8.

### 4.5 Texture swaps: `tools/build_textures.py`

Copies the PS1 textures listed in `script/texture_swaps.json` over their PSP counterparts. Each pair must have the
same size, format and position (checked); only pixel bytes are copied, plus palettes where the rule says so. With
`text` and `audio`, only the text-bearing swaps are applied (weapon labels, prologue pages, maps, mission banner).
With `legends`, the swaps marked `"legends": true` are applied as well (US names and artwork). Output under
`build/tex_psp/`, rebuilt from scratch on every build. See RESEARCH §9.

### 4.6 PS1 title data and save picture (`legends` only): `tools/build_ps1_title.py`, `tools/build_savepic.py`

- `build_ps1_title.py` prepares the PS1 logo, menu-word palettes and title background for the PSP title data.
  Output `build/ps1_title/`. See RESEARCH §8.4.
- `build_savepic.py` makes the save picture, also used as the PSP menu icon, from the PS1 title background and
  logo (scaled with Pillow; no other source). Output `build/pict/savepic.png`. See RESEARCH §14.

### 4.7 Extra font glyphs: `tools/build_font.py`

Copies four glyphs the English script needs from the PS1 font into unused cells of the PSP font, and writes the
letter widths the next step uses. Output `build/font/font.dat` and the font texture under `build/tex_psp/`. See
RESEARCH §4.

### 4.8 Program: text renderer and text buffers: `tools/patch_eboot.py`

Input: the plain program. Output: `build/eboot/ULJM05030_EBOOT_vwf.BIN`. Every patched instruction is checked
against the original first.

- Variable-width text: the draw loop advances by each glyph's measured width instead of a fixed 12 pixels.
  Japanese characters keep 12 pixels. (RESEARCH §4)
- Title menu: the three options are widened for the English words. (RESEARCH §8)
- Text buffers: English text does not fit the Japanese buffers, so three buffers move to a memory area the PSP
  version never uses (`tools/memmap.py`). The packing step rewrites the matching load addresses in the data files.
  (RESEARCH §6)

### 4.9 Program: system messages: `tools/build_sysmsg.py`

Replaces the program's system-message table (save screens, options, pause menu, item, part and weapon names, help
lines) with the matching strings from the PS1 executable. PSP-specific lines, which have no PS1 equivalent, come
from `script/sysmsg_rules.json`. The mission banner's sprite lists are replaced by the PS1's, to match the English
banner texture. Output `build/eboot/ULJM05030_EBOOT_en.BIN` and `logs/sysmsg_report.json`. See RESEARCH §7.

### 4.10 Program: save-screen text: `tools/build_savetext.py`

Writes the English strings the game gives the PSP save utility (save name, difficulty, play time, location names,
Memory Stick errors), from `script/savedata_rules.json`. The save name is "Mega Man Legends" with `legends`,
otherwise "Rockman DASH: Hagane no Boukenshin" (internal argument set by `build.py`). The save identity is never
touched, so saves stay compatible with the unmodified game's save slots. See RESEARCH §7.7.

### 4.11 Program: save picture buffer: `tools/patch_psp_menu.py`

With `legends`, makes the game keep the new save picture in memory after an existing save has been loaded;
otherwise later saves would be written with the loaded save's old picture. No change with `text` or `audio`. See
RESEARCH §14.3.

### 4.12 Program: wide-screen HUD: `tools/patch_wide_hud.py`

Applies the `--hud` choice (internal argument set by `build.py`): new code narrows the HUD, windows and text to 3/4
width while they are drawn in the Wide screen mode, and adds the Triangle toggle on the options screen. With
`--hud=off` nothing is changed. See RESEARCH §13.

### 4.13 Program: dog scene: `tools/patch_ps1_dog.py`

Applies the `--paprika` choice. With `good-dog`, five words in the PSP's native code for the scene are changed to
match the US PS1 release, which removed the kick. The dialogue is the same either way. See RESEARCH §12.

### 4.14 Program: subtitles on or off: `tools/patch_subtitles.py`

With `--subtitles=off`, one instruction makes the subtitle function always take its own "no scene" path. Voices and
subtitle tables are untouched. See RESEARCH §11.4.

`tools/patch_subtitle_box.py` runs next. With `--subtitle-background=on` and English subtitles it adds 24 words of
code so that the game draws window boxes of decoration type 4, which only the subtitle band uses, without their
one-pixel border. One call is retargeted; other windows are unchanged. Report: `subtitle_box.json`. See RESEARCH §11.5.

### 4.15 Program: PS1 title screen: `tools/patch_ps1_title.py`

With `legends`, replaces the PSP title background with the PS1's, sets the palettes for the PS1 menu colours, and
removes the Japanese title voice calls (the English title voices stay). No change with `text` or `audio`. See
RESEARCH §8.4.

### 4.16 PSP menu name: `tools/build_sfo.py`

Sets the game's name in the PSP menu (`PARAM.SFO` `TITLE`) from `script/sfo_rules.json`: "Mega Man Legends" with
`legends`, otherwise "Rockman DASH: Hagane no Boukenshin". Only `TITLE` may change; the game ID, version and
category stay, so the firmware and saves identify the game as before. Output `build/sfo/PARAM.SFO`. See
RESEARCH §7.8.

With `legends`, the packing step also replaces the menu icon `ICON0.PNG` with the save picture and removes the
animated icon `ICON1.PMF`.

For every localization, `tools/build_xmb.py` removes the Japanese tagline from the menu overlay `PIC0.PNG`: rows
0–163 of the 310 × 180 picture are made transparent, which leaves the copyright line (rows 164–173) exactly as it
was; nothing is drawn or added. The packing step puts the result in place and removes the menu music `SND0.AT3`.
The background `PIC1.PNG` is unchanged. `verify_xmb.py` checks all three. See RESEARCH §14.

### 4.17 Subtitles: `tools/build_subtitles.py`

Runs with `--subtitle-language=en`, for every localization. Builds the subtitle scenes from
`script/subtitles_en.csv`: per scene, a new timing table and string table in the program. Lines too long for the
box are split into consecutive lines. With `--subtitle-background=on`, a dark band (the game's window box, decoration
type 4) is added behind the lines (internal argument set by `build.py`). With `--subtitle-language=jp` the step is skipped. See RESEARCH §11.

`script/subtitles.csv` is the review file the English subtitle data was prepared from; the build reads
`subtitles_en.csv`.

### 4.18 English audio (`audio` and `legends`): `tools/voice/`

- `patch_eboot_voice.py` adds the English voice file paths to the program's voice tables, and points the voice
  clips that game code starts directly (the news reports) at their English clips (`script/voice_rules.json`).
- `build_audio.py` converts the PS1 voice clips and cutscene streams to ATRAC3plus `.at3` files
  (`xa.py` decodes the PS1 XA-ADPCM audio and resamples it to 44.1 kHz; `encode_at3.py` runs atracdenc), with headers laid out like the Japanese files. Results are cached.
  Music-only streams are not replaced. Output plan: `build/audio_psp/plan.json`.
- `build_vab.py` handles the few short voice samples that are stored in sound banks rather than `.at3` files
  (`script/vab_voices.json`): each listed sample is replaced by the PS1 English sample, unmodified. Output
  `build/vab_psp/`.

The Japanese voice clip files, which nothing in an English-audio build plays, are dropped from the image and their
space is reused. Kept Japanese on purpose: the PSP credits theme. The PSP menu music (`SND0.AT3`) is removed in every build. See
RESEARCH §10.

### 4.19 Pack the ISO: `tools/pack_inplace.py`

- Copies the original ISO; original files never move, because the game reads its data files by disc position.
- In each data file, splices in the English dialogue, textures, font and sound-bank entries, updates sizes, and
  rewrites the load address of every dialogue file whose buffer moved.
- Updates the program's internal file list (disc position and size of each data file).
- Files that no longer fit in their place go into freed space or after the end of the original image; the
  directory, file list and volume size are updated.
- Folds the data the earlier steps added to the program back into the original two-segment layout
  (`tools/flatten_eboot.py`), which the real PSP loader requires, and writes the program into the image.
- Safety rules: a dialogue file over its buffer limit is kept Japanese and listed in `manifest.json`; a texture is
  never allowed to write into the next entry's header.

Output: the ISO and `manifest.json` in `build/test/<tag>/`. See RESEARCH §15, and §5.5 for the flattening.

---

## 5. Checks

`build.py` runs these after packing (all in `tools/checks/`). Each stops the build on a problem.

| Check | What it confirms |
|---|---|
| `verify_voice_eboot.py` | The program's voice tables resolve every Japanese and English voice id to the expected file. |
| `compare_loaded.py` | The flattened program loads to exactly the same memory as the unflattened one. |
| `audit_eboot.py` | Every changed word and every added byte in the program belongs to a known patch (report: `audit_eboot.txt`). |
| `verify_subtitles.py` | Every English subtitle line reads back from the program (English subtitles only). |
| `verify_savetext.py` | The save-screen strings are in place; the save identity is unchanged. |
| `verify_ps1_title.py` | The title, menu-picture and dog options are as built, or untouched when not chosen. |
| `verify_voice.py` | Every voice command in the built text names a clip that exists. |
| `verify_msg_args.py` | Every dialogue block parses; special control codes carry the same arguments as the Japanese. |
| `verify_headers.py` | Data-file entry headers are unchanged except the allowed fields; untouched entries are identical. |
| `verify_sfo.py` | Only `TITLE` changed in `PARAM.SFO`. |
| `jp_audio_audit.py`, `verify_dropped.py` | Nothing that was dropped is reachable; streams and English clips are present (English audio only). |
| `verify_vab.py` | Sound banks: the listed samples equal the PS1's and everything else the PSP's; or the banks are untouched. |
| `verify_layout.py` | No two files overlap on the disc. |
| `verify_slack.py` | Every disc area a grown file now uses was empty on the original. |
| `verify_sysmsg.py` | Every system-message slot resolves to a proper string (report: `verify_sysmsg.txt`). |

See RESEARCH §15.5.

### Separate checks (not run by `build.py`)

- **HUD emulation check:** `python research/verify_wide_hud.py <tag>`. Runs the new HUD code in a MIPS
  emulator over real frames taken from PPSSPP save states, for both Screen settings, compares every decision with a
  Python model, and confirms the built program holds exactly that code. Needs the `unicorn` and `zstandard`
  packages (`research/requirements.txt`) and save states (`*.ppst`) in `savestates/` and
  `widehudfix_savestates/`. Save states contain game data and are not part of the repository; you need your own.
- **Text-buffer check:** `python research/savestate_check.py` (needs `zstandard`). Reports whether the moved
  text buffers (4.8) are empty in every save state in `savestates/`. The states must be made with the original
  Japanese ISO, in varied places (PPSSPP in-game menu → Save State; files in PPSSPP's `PSP/PPSSPP_STATE/`). Run it
  if you change where the buffers go. See RESEARCH §6.4.

---

## 6. Changing things

After any change, rebuild with `python build.py <newtag>`; the checks must pass.

| To change | Edit |
|---|---|
| A PSP text slot that has no PS1 line at the same position | `script/fill_rules.json` |
| A formatting edit to a PS1 line | `script/text_edits.json` |
| Options-screen, save-screen and other PSP-specific system lines | `script/sysmsg_rules.json`, `script/savedata_rules.json` |
| The PSP menu name | `script/sfo_rules.json` |
| Which PS1 textures replace PSP ones | `script/texture_swaps.json` (add `"legends": true` for a swap that belongs to `legends` only) |
| Subtitle lines and timings | `script/subtitles_en.csv` |
| Voice overrides (streams, clips started by code) | `script/voice_rules.json` |
| Symbol or button mapping, control-code handling | `tools/msgtool.py` |
| Letter spacing, title menu layout | `tools/patch_eboot.py`, `tools/build_title.py` |
| Where the text buffers live | `tools/memmap.py`, then run the text-buffer check (section 5) |

To add a texture swap, find candidates with `research/tex_compare.py` and `tex_review_page.py`, which list
and show the textures that differ between the two discs. A swap needs the same size, format and position on both
sides.

**Project rules.** Only lines from the PS1 English script are used as game text. Text with no PS1 source (a few
PSP-only slots and PSP-specific system lines) and formatting changes are individually reviewed exceptions,
recorded in the rule files in `script/`.

The tools in `research/` re-derive the findings in RESEARCH.md (some need `capstone`); each script's header
says what it does.

---

## 7. Troubleshooting

| Symptom | Cause | What to do |
|---|---|---|
| The build stops because an input is missing | A disc image is not at the expected place or name. | Use the exact names in section 1, or pass the PSP image path on the command line. |
| `unknown option: …` | An option name or form `build.py` does not know. | Run `python build.py` without arguments for the list. Options take the form `--name=value`. |
| The extract step reports an unknown CRC32 | The PSP image is not one of the three known ones. | Compare its SHA-1 with section 1. The build may still work. |
| A patch step stops because an original instruction differs | The program is not ULJM05030 v1.01. | Use a known image. |
| The plain program cannot be made | `pyeboot` is not installed and the image is the PSN release. | Install `pyeboot`, use a UMD image, or dump with PPSSPP (4.1). |
| atracdenc fails to compile | cmake, a C++ compiler, (Linux/macOS) libsndfile's development files or (Windows; the error names `atlbase.h`) the ATL component are missing. | Install them (section 1), pass cmake arguments in `ATRACDENC_CMAKE_ARGS`, or point `ATRACDENC=` at a working program. |
| The ISO's MD5 differs from another machine's | A different platform, compiler or Pillow version. | Not an error if all checks pass. |
| The game runs in Japanese from a UMD-based build | The loader started `BOOT.BIN`, the original program, instead of `EBOOT.BIN`. | Use a loader setting that starts `EBOOT.BIN`, or build from the PSN release (its `BOOT.BIN` is blank). |
| A save still shows the old name or picture | Name and picture are stored in the save when it is written. | Save over it. |
| The game hangs at the first loading screen after you repacked or rebuilt the ISO with another tool | Files moved; the game reads data files by disc position. | Use the ISO exactly as `build.py` wrote it. |
| The game does not start on a PSP | The program is unsigned; only custom firmware runs it, and only a PSP Go with ARK-5 has been tested. | See section 3 and section 8. |

---

## 8. Known limitations and untested areas

**Platforms and tools**

- Built and verified on Linux and macOS (Apple Silicon). Windows (x64): the packaged patcher was built with
  `packaging/build_release.ps1` (Python, CMake, and the Visual Studio Build Tools with the ATL component) and patched a
  retail UMD image with the default options, all checks passing. The command-line build (`python build.py`) has not
  been run on Windows.
- `--hud=center` and `--hud=edge`, `--paprika=good-dog` and the `text` / `audio` localizations have had little or no
  play testing; the default options are the ones played through on a PSP.
- The release workflow (`.github/workflows/release.yml`) builds the patcher on GitHub's runners for Linux (x64,
  arm64), macOS (Apple Silicon, Intel) and Windows (x64), and publishes them on a `v*` tag. It repeats the steps of
  `packaging/build_release.sh` / `.ps1`, which were run by hand, but has not itself been run yet; start it once with
  "Run workflow" before tagging a release. The macOS downloads bundle Homebrew's libsndfile, built for the runner's
  macOS version (15), so they may not start on older macOS.
- Real hardware: tested only on a PSP Go with ARK-5. If a custom firmware refuses the unsigned program, the
  program would need signing; the build has no signing step.

**Features built and checked, but not yet confirmed in play**

- `--hud=hud-only` (the default) has been played on a PSP Go; during the Mission Complete banner and screen
  transitions the HUD briefly returns to stretched (open). `--hud=edge` in its current form and the Triangle toggle:
  confirmed by the emulation check only. Not known: whether 2D markers tied to world positions (lock-on, pickups) are affected, and behaviour on
  real hardware.
- `--subtitles=off` and `--paprika=good-dog` (in its final form): checks pass; no play result recorded.
- English subtitles over Japanese voices (`--localization=text` with `--subtitle-language=en`): the English
  timings are used unchanged. In 47 of 50 scenes the two voice tracks end within about a second of each other.
  Three scenes differ in length and have not been retimed, so their subtitles will not match the Japanese voices.
- The US name and artwork textures of the `legends` set.
- The two in-game sound banks with English voice samples: not heard in play.
- Loading a save of the unmodified Japanese game in an English build, and the reverse: not recorded as tested.

**Other limitations**

- The dog scene: US differences outside the kick itself (lip-sync timings, a second kickable object) are not
  included in `good-dog`.
- Some lines of the English voice track have no subtitle (reference lines that matched nothing in the audio, and a
  few unclear fragments).
- With Japanese voices, the placement of voice clips in blocks where the two scripts differ is automatic and was
  reviewed only where it looked wrong.
- Still Japanese: the control legend of an unused developer screen;
  with `text` and `audio`, the title logo and background. Program text outside the system-message table, the save
  strings and the subtitles has not been surveyed exhaustively.
- The marker used on reviewed non-PS1 lines contains a `*` that has no glyph and shows as a middle dot.
- Wide screen mode still stretches the 3D picture from 4:3; `--hud` corrects only the 2D layers. A true widescreen
  3D view is not implemented.
- The evidence for the text-buffer location comes from save states that do not cover every area (none from the
  Flutter interior, City Hall or the support-car menu). Play there has shown no problem.

See RESEARCH §16 for the full list of open and unverified points.

**Sharing.** Do not distribute a built ISO or any file extracted from the games.

---

## 9. Folder layout

In the repository:

```
README.md, LICENSE, THIRD_PARTY.md, LICENSES/
requirements.txt            Python packages for the build
build.py                    command-line build
gui.py                      graphical patcher
tools/                      build steps and shared modules
tools/checks/               the checks build.py runs after packing
research/                   tools behind the findings and rule files; not run by the build
tools/voice/                audio steps
script/                     rule and data files: *.json, subtitles.csv, subtitles_en.csv, ps1_charmap.tbl
docs/                       BUILD.md (this file), RESEARCH.md
src/atracdenc/              third-party encoder source (LGPL), with MODIFICATIONS.md
.github/workflows/          release.yml
```

Created on your machine and never committed:

```
originalDiskImages/     your PS1 and PSP images (never modified)
decrypted_eboot/        the plain program, made from your PSP image (4.1)
extracted/              output of the extract step (4.2)
build/                  intermediate files, caches and results; build/test/<tag>/ holds the ISO and manifest.json
logs/                   reports written by the build and the research tools
bin/<platform>/         compiled atracdenc
```

Save states for the separate checks (`savestates/`, `widehudfix_savestates/`) are also local only.
