# Rockman DASH (PSP) English Patcher

An unofficial fan project that turns the Japanese PSP game **Rockman DASH: Hagane no Boukenshin** (ULJM05030) into an
English game, using the script, voice acting and textures of the US PlayStation release, **Mega Man Legends**.

The patcher works from **your own** copies of both games. This repository contains no game data, and the game you
build must not be shared. The project is not affiliated with or endorsed by Capcom.

## What the patcher does

Rockman DASH on the PSP is a port of the 1997 PlayStation game, released only in Japan. The US PlayStation release,
Mega Man Legends, has a complete English script and English voice acting. The patcher reads both disc images and
builds a new PSP disc image in which:

- **Dialogue and menus** use the PS1 English script. Only lines from the US PS1 release are used. Where the PSP
  version has text with no PS1 counterpart (a few PSP-only menu lines, and the HUD Size hint), each line was reviewed
  individually and is recorded in the rule files in `script/`.
- **Voices** are the English voice acting from the PS1 disc, including the cutscene audio, re-encoded in the PSP's own
  audio format.
- **Textures with writing** (weapon labels, the opening prologue, island maps, the mission banner, the title menu) are
  swapped for the US versions.
- **Cutscene subtitles**, which the PSP version added, are shown in English and timed to the English voice acting,
  with an optional dark band behind them.
- With the default **Legends** option, the game also takes the US title screen, and appears in the PSP menu and in
  save files as *Mega Man Legends* with the US logo picture.
- In the PSP's **Wide** screen mode, the HUD is drawn at its correct proportions instead of stretched (switchable in
  the game, see below).
- The face-button icons in the text follow the PSP's layout (Circle to confirm, Cross to cancel).

The game program is patched in place and every original file keeps its position on the disc. The save format is
unchanged. Each build ends with a series of automatic checks; if one fails, the build stops and says why.

## What you need

- **Mega Man Legends (USA)** for the PlayStation, as a `.bin/.cue` image. The patcher reads the `.bin` of Track 1.
- **Rockman DASH: Hagane no Boukenshin (Japan)** for the PSP, as an `.iso`: the PSN release or a retail UMD image.
- About 2 GB of free disk space.

When you pick the files, the patcher compares them with checksums of known good copies and tells you whether they
match. Other copies may still work: every build step checks the data it reads.

## Using the patcher

1. Download the release for your system (Windows, macOS or Linux), unpack it and start the program. The programs are
   not signed: on Windows choose "More info" > "Run anyway" the first time; on macOS right-click the program and
   choose Open (or allow it under System Settings > Privacy & Security).
2. Choose your two disc images:
   - **Mega Man Legends (PS1, USA)**: the `.bin` of Track 1 from a `.bin/.cue` image.
   - **Rockman DASH (PSP, Japan)**: an `.iso` of ULJM05030, retail UMD or PSN release.
3. Pick the options and press **Patch**. When patching is done, choose where to save the English game.

Patching takes a few minutes. Your disc images are only read, never changed.

### Options

| Option | Choices (default first) | What it does |
|---|---|---|
| Localization | Legends, Text and audio, Text only | **Text only**: English text and text-bearing textures, Japanese voices, the game keeps the name Rockman DASH. **Text and audio**: plus all English voices. **Legends**: plus the Mega Man Legends title screen, PSP menu name and icon, save name and picture, and the US signs and artwork. |
| Paprika (the dog) | Fair game, Good dog | **Good dog** removes kicking the dog, as the US PS1 release did. |
| Cutscene subtitles | On, Off | The PSP version's subtitles in voiced scenes. |
| Subtitle language | English, Japanese | |
| Subtitle background | On, Off | A dark band behind the English subtitles. |

**HUD size.** In the game's Wide screen mode the HUD is drawn at its correct proportions instead of stretched; the
3D picture, text, windows and menus are left as they are. To switch this off or on, go to the game's options screen,
highlight Screen with Wide selected, and press Triangle ("HUD Size: Corrected / Default"). The setting lasts until the
game is closed. Building from the command line offers other variants (`--hud=`, see `docs/BUILD.md`).

### Playing

The patched game runs in PPSSPP and on a PSP with custom firmware. It has been played on a PSP Go (ARK-5) with the
default options. Some options have had little play testing; `docs/BUILD.md` section 8 lists what has and has not
been tested, and the known limitations.

## Building from source

Python 3.10 to 3.14 is needed. Then:

```
pip install -r requirements.txt
python gui.py                      # the graphical patcher
python build.py mybuild [options]  # the command line; python build.py lists the options
```

English audio needs the ATRAC3plus encoder in `src/atracdenc`, compiled automatically on first use (CMake and a C++
compiler; libsndfile on Linux and macOS; on Windows the Visual Studio Build Tools with the C++ ATL component).
`packaging/build_release.sh` (macOS, Linux) and `packaging/build_release.ps1` (Windows) build the packaged patcher;
`.github/workflows/release.yml` does the same on GitHub for every platform. The build has been run on Linux, macOS
(Apple Silicon) and Windows (x64). `docs/BUILD.md` has the details, every build step and the checks.

## Repository layout

| Path | Contents |
|---|---|
| `gui.py`, `build.py` | the graphical patcher and the command-line build |
| `tools/` | the build steps; `tools/checks/` holds the checks run after every build |
| `script/` | the rules the build applies: which text, textures and audio go where, reviewed exceptions, subtitle timings |
| `research/` | the tools that produced the findings and rule files; not run by the build |
| `docs/BUILD.md` | requirements, the build steps, the checks, troubleshooting, known limitations |
| `docs/RESEARCH.md` | the technical reference: file formats, program layout, addresses, and how each finding was established |
| `src/atracdenc/` | the third-party ATRAC3plus encoder (LGPL), with the project's two small changes |
| `packaging/`, `.github/` | building the packaged patcher |
| `LICENSE`, `LICENSES/`, `THIRD_PARTY.md` | licences, and every third-party part with its source |

## Credits

- **DashEditor** by **_Ombra_** of **SadNES cITy Translations** (https://github.com/OmbraRD/DashEditor), the Mega Man
  Legends translation toolkit. Its research into the game's file formats (containers, dialogue format and control
  codes, font and texture layouts) and its character table were the starting point for these tools. Not included
  or required.
- **atracdenc** by Daniil Cherednik and contributors (https://github.com/dcherednik/atracdenc), with **libgha** and
  **KISS FFT** (Mark Borgerding): the ATRAC3plus encoder for the English audio.
- **libsndfile** (https://github.com/libsndfile/libsndfile): reads audio files for atracdenc on Linux and macOS.
- **pyeboot** by Illidan (https://github.com/Illidanz/pyeboot), a Python interface for **pspdecrypt**
  (https://github.com/John-K/pspdecrypt; decryption code from PPSSPP using **libkirk** by Draan, KL3E/KL4E support by
  artart78) and **sign_np** by Hykem (which credits Proxima, Draan, tpunix and the PRO firmware team): decrypts your own game program when building from the PSN release.
- **pycdlib** by Chris Lalancette and contributors: reads and writes the disc images.
- **NumPy**: decodes and resamples the PS1 audio. **Pillow**: the PSP menu and save pictures. **Capstone**:
  disassembly in one of the build checks.
- **Python**, **Tk** and **PyInstaller**: the packaged patcher.
- **Unicorn Engine** and **python-zstandard**: emulation and save-state reading in the research tools.
- **Whisper** (OpenAI), run with **mlx-whisper**: transcribing the English voice acting for the subtitle timings.
- **PPSSPP**: testing and research.
- **Estil**, author of the GameFAQs *Mega Man Legends* game script
  (https://gamefaqs.gamespot.com/ps/197896-mega-man-legends/faqs/18334): the reference used to check the English
  subtitle transcripts.
- **Redump** (http://redump.org): the checksum of the PS1 disc image.
- **Capcom**: Mega Man Legends and Rockman DASH. All game content belongs to Capcom.

Made (with good intentions) using Claude Opus 5.5.

## Licence

This project's own code, documentation and rule files are under the MIT licence (`LICENSE`). The included atracdenc
source keeps its own licence (LGPL-2.1-or-later, with BSD-licensed parts). The packaged patcher downloads contain
pyeboot and are therefore offered under GPL-3.0-or-later as a whole; their source is this repository. The English
subtitle lines in `script/subtitles_en.csv` are transcriptions of the US game's voice acting and remain Capcom's.
`THIRD_PARTY.md` and `LICENSES/` have the details.
