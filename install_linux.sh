#!/usr/bin/env bash
# install_linux.sh — Linux-native setup for Agent In The Armchair
# Creates the whisper venv at ~/.local/share/whisper-venv (the platform_config
# convention: start_armchair.sh exports WHISPER_VENV pointing here).
# System prereqs (present on FishTank Linux): python3, ffmpeg (pulse), PipeWire.
# Idempotent: skips when the install-complete marker exists.
set -euo pipefail

VENV_DIR="${HOME}/.local/share/whisper-venv"
MARKER="${VENV_DIR}/.install-complete"

echo "================================================"
echo " ARMCHAIR — LINUX INSTALL"
echo "================================================"
echo " Venv: ${VENV_DIR}"

if [ -f "${MARKER}" ]; then
    echo " [OK] Already installed (marker present). Delete the marker to force a reinstall."
    exit 0
fi

python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo " [1/4] torch CUDA 12.8 (big download — be patient)..."
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

echo " [2/4] faster-whisper + soundfile + numpy..."
pip install faster-whisper soundfile numpy

echo " [3/4] piper-tts (the piper CLI)..."
pip install piper-tts

echo " [4/4] pyannote-audio (diarization — optional, non-fatal)..."
pip install pyannote-audio || echo " [WARN] pyannote install failed — diarization disabled; pipeline still works."

echo " Verifying..."
python - <<'PYEOF'
import torch
print(f"  torch {torch.__version__} — cuda available: {torch.cuda.is_available()}")
import numpy
import faster_whisper
import soundfile
print("  faster-whisper + soundfile + numpy OK")
PYEOF
"${VENV_DIR}/bin/piper" --help > /dev/null 2>&1 && echo "  piper CLI OK"

touch "${MARKER}"
echo " [OK] Linux environment ready."
echo " Next: ./start_armchair.sh"