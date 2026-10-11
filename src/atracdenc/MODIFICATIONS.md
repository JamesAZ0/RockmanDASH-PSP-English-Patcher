# atracdenc, as included in the Rockman DASH PSP English project

This folder is a copy of **atracdenc** by Daniil Cherednik and contributors
(https://github.com/dcherednik/atracdenc), commit `cb170709f836cb43dc0312455188c791159d81dc`, with its submodule
**libgha** (https://github.com/dcherednik/libgha, commit `00a95243254cfb1e43b05888ebc68e9aa401507a`) copied into `src/lib/libgha/`.

Licences (unchanged, see the files): atracdenc is **GNU LGPL 2.1 or later** (`LICENSE`); libgha is BSD-2-Clause
(`src/lib/libgha/LICENSE`) and includes KISS FFT (`src/lib/libgha/src/3rd/kissfft/COPYING`). The project's MIT
licence does **not** apply to this folder.

## Changes made by this project

- 2026-09-29, `src/atrac/at3p/at3p.cpp`: the ATRAC3plus encoder takes its frame size from the environment variable
  `AT3P_FRAME` when it is set (default unchanged: 2048). Two lines: `#include <cstdlib>` and the `BitStream(out, …)`
  initialiser. The same change as a patch: `at3p_frame.patch` in this folder.
- 2026-10-02, `CMakeLists.txt`: on macOS the universal (arm64 + x86_64) build is only the default; an architecture
  given with `-DCMAKE_OSX_ARCHITECTURES=` is kept. One line (`if(APPLE AND NOT CMAKE_OSX_ARCHITECTURES)`). Reason:
  a universal build cannot link against a single-architecture libsndfile such as Homebrew's.
- 2026-10-01: copied here without `.git`, `.github`, `.gitmodules`, `build/` and `debian/`. No other file changed by the copying.

## Building

```
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target atracdenc --config Release
```

Linux and macOS need libsndfile (development files); Windows uses Media Foundation and needs nothing extra.
The project's `build.py` does this itself when no `atracdenc` is found (see docs/BUILD.md, section 1).
