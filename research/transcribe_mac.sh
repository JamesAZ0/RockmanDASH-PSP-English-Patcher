#!/bin/bash
# Run on the Mac (not the VM), from the rockmanDash folder:  ./research/transcribe_mac.sh [prefix]
#   pass 1 (whole clips):            ./research/transcribe_mac.sh [prefix]
#   pass 2 (cutscene lines, windows): ./research/transcribe_mac.sh --windows
#   pass 3 (word timing for the English subtitles): ./research/transcribe_mac.sh --words
# First run: creates build/.venv-whisper, installs mlx-whisper from PyPI, and downloads the Whisper model
# mlx-community/whisper-large-v3-turbo (~1.6 GB, Hugging Face cache in ~/.cache/huggingface). Later runs reuse both.
set -e
cd "$(dirname "$0")/../.."
[ "$(uname -m)" = arm64 ] || { echo "Needs an Apple Silicon Mac"; exit 1; }
if [ ! -x build/.venv-whisper/bin/python ]; then
  python3 -m venv build/.venv-whisper
  build/.venv-whisper/bin/pip install --quiet --upgrade pip mlx-whisper
fi
if [ "$1" = --windows ]; then build/.venv-whisper/bin/python research/transcribe_windows_mac.py
elif [ "$1" = --words ]; then build/.venv-whisper/bin/python research/transcribe_words_mac.py
else build/.venv-whisper/bin/python research/transcribe_mac.py "$@"; fi
