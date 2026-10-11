#!/usr/bin/env bash
# Build the packaged patcher on this machine (macOS or Linux): the same steps as .github/workflows/release.yml.
#   bash packaging/build_release.sh        ->  dist/RockmanDASH-PSP-English-Patcher[.app]
# Needs: Python 3.10 to 3.14 with Tk (pyeboot has no ready-made package for 3.15 yet, so pip would compile it), cmake, a C/C++ compiler, make, libsndfile's development files
#   macOS:  xcode-select --install ; brew install cmake libsndfile python-tk
#   Ubuntu: sudo apt install build-essential cmake libsndfile1-dev python3-venv python3-tk
# Python packages go into a virtual environment in build/venv, not into the system's Python.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
for p in python3 cmake make cc; do
  command -v "$p" >/dev/null || { echo "missing: $p (see the top of this script)" >&2; exit 1; }
done
python3 -c 'import tkinter' 2>/dev/null || { echo 'this Python has no Tk (macOS: brew install python-tk)' >&2; exit 1; }

python3 -m venv build/venv
. build/venv/bin/activate
pip install -q -r requirements.txt pyinstaller

TAG="$(python3 -c 'import sys; sys.path.insert(0, "tools"); import exttools; print(exttools.platform_tag())')"
echo "platform: $TAG"
if command -v brew >/dev/null; then export ATRACDENC_CMAKE_ARGS="${ATRACDENC_CMAKE_ARGS:--DCMAKE_PREFIX_PATH=$(brew --prefix)}"; fi
python3 -c 'import sys; sys.path.insert(0, "tools"); import exttools; print(exttools.build_atracdenc())'
pyinstaller --noconfirm packaging/patcher.spec
echo
echo "done: $(ls -d dist/RockmanDASH-PSP-English-Patcher*)"
