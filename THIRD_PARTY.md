# Third-party software, data and licences

What this project uses that it did not write, what for, under which licence, and what that means for the repository
and for the release downloads. Not legal advice.

## 1. Summary

| Part | Licence | Where |
|---|---|---|
| This project's own code, documentation and rule files | MIT (`LICENSE`) | everything except the rows below |
| atracdenc with two small changes, incl. libgha and KISS FFT | LGPL-2.1-or-later; BSD-2-Clause; BSD-3-Clause | source in `src/atracdenc/` (see `MODIFICATIONS.md` there); compiled program in the release downloads |
| `src/atracdenc/at3p_frame.patch` (the frame-size change as a patch) | LGPL-2.1-or-later | repository |
| The release downloads (packaged patcher) as a whole | **GPL-3.0-or-later**, because they contain pyeboot | release downloads only |
| Game content (Capcom) | not licensed, never distributed | not in the repository or the downloads |

The repository contains no game files. `script/` holds the rules the build applies and, in `subtitles_en.csv`, the
English subtitle lines with their timings; those lines are transcriptions of the US game's voice acting and remain
Capcom's. `script/subtitles.csv` holds only scene and timing numbers.

## 2. Included in the repository

| Item | Use | Licence | Notes |
|---|---|---|---|
| **atracdenc** (github.com/dcherednik/atracdenc, commit cb170709f836cb43dc0312455188c791159d81dc) | ATRAC3plus encoder for the English audio | LGPL-2.1-or-later | Two small changes (frame size from the environment variable `AT3P_FRAME`; macOS architecture selectable when compiling), documented and dated in `src/atracdenc/MODIFICATIONS.md`. Licence file kept. |
| **libgha** (github.com/dcherednik/libgha, commit 00a95243254cfb1e43b05888ebc68e9aa401507a) | part of atracdenc | BSD-2-Clause | In `src/atracdenc/src/lib/libgha/`, unchanged. |
| **KISS FFT** | part of libgha | BSD-3-Clause | In `src/atracdenc/src/lib/libgha/src/3rd/kissfft/`, unchanged. |

## 3. Bundled in the release downloads only

| Item | Use | Licence | Source |
|---|---|---|---|
| **Python** and its standard library, **Tk** | running the patcher | PSF-2.0; Tcl/Tk licence (BSD-style) | python.org, tcl.tk |
| **PyInstaller** bootloader | packaging | GPL-2.0-or-later with an exception allowing any licence for the packaged program | pyinstaller.org |
| **pycdlib** | reading and writing disc images | LGPL-2.1-only | github.com/clalancette/pycdlib |
| **NumPy** | decoding the PS1 audio, resampling, sound banks | BSD-3-Clause | numpy.org |
| **Capstone** | disassembly in one of the build's checks (`tools/checks/jp_audio_audit.py`) | BSD-3-Clause | capstone-engine.org |
| **Pillow** | the PSP menu overlay, save picture and menu icon | MIT-CMU (HPND) | python-pillow.org |
| **pyeboot** by Illidan (wraps **pspdecrypt**, GPL-3.0, github.com/John-K/pspdecrypt, and **sign_np** by Hykem; both use libkirk) | decrypting the user's own `EBOOT.BIN` from the PSN release | GPL-3.0 | github.com/Illidanz/pyeboot |
| **atracdenc** (compiled from `src/atracdenc`) | as above | LGPL-2.1-or-later | this repository |
| **libsndfile** (Linux and macOS downloads) | used by atracdenc | LGPL-2.1-or-later | github.com/libsndfile/libsndfile |
| **Microsoft Visual C++ runtime** (Windows download) | the runtime files that come with Python for Windows | Microsoft's redistribution terms for these files | python.org |

Because pyeboot (GPL-3.0) is part of the packaged program, each release download is offered under GPL-3.0-or-later as
a whole; the licence texts of the bundled parts are in `LICENSES/` (and inside the download; the Windows runtime files are
redistributed as they come with Python). The corresponding source is this
repository at the release's tag, plus the upstream sources named above.

## 4. Used when building from source, not included

| Item | Use | Licence |
|---|---|---|
| FFmpeg | only some optional research and review tools (playing or converting audio for review); not used by any build | LGPL-2.1-or-later or GPL, depending on the build the user installs |
| CMake, a C++ compiler, libsndfile | compiling `src/atracdenc` | BSD-3-Clause; various; LGPL-2.1-or-later |
| pycdlib, NumPy, Pillow, Capstone, pyeboot | `requirements.txt` | as in section 3 |
| unicorn | only `research/verify_wide_hud.py` (optional check) | GPL-2.0 |
| zstandard | optional research tools (reading PPSSPP save states) | BSD-3-Clause |
| mlx-whisper and the Whisper large-v3-turbo model | transcription during the subtitle work (`research/transcribe_*`) | MIT |
| PPSSPP | testing; the optional decrypted-EBOOT dump | GPL-2.0-or-later |

`tools/plain_eboot.py` imports pyeboot and `research/verify_wide_hud.py` imports unicorn. Those two scripts may
be used under GPL-3.0-or-later and GPL-2.0 respectively as well as under MIT.

## 5. Research and reference sources

- **DashEditor** by _Ombra_ (SadNES cITy Translations, github.com/OmbraRD/DashEditor). It has no licence and is not
  included or required. Its documentation of the game's formats was the starting point for these tools.
  `script/ps1_charmap.tbl`, the list of which glyph number of the US font is which character, was compiled with
  reference to DashEditor's character table; it contains only that factual mapping (109 single characters).
- **"Mega Man Legends – Game Script (PS)"** by Estil (GameFAQs). Used as a reference to check our own transcripts of
  the English voice acting for names and misheard words. Not included.
  https://gamefaqs.gamespot.com/ps/197896-mega-man-legends/faqs/18334
- **Redump** (redump.org). The SHA-1 of the PS1 disc image (Track 1) that the patcher checks against.

## 6. Game content

The PS1 English script, voices, textures and fonts and the PSP game data are Capcom's. No licence here covers them.
The project publishes tools and rules only; users build from their own copies of both games, and the built ISO must
not be distributed.
