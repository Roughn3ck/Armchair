#!/usr/bin/env bash
# start_armchair.sh — Linux launcher for Agent In The Armchair
# Starts: mic capture (PipeWire) + dashboard (:8765) + pipeline (foreground).
# Stop: Ctrl+C — all children shut down cleanly.
# Prereqs: ./install_linux.sh completed once; .env present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${HOME}/.local/share/whisper-venv"
PY="${VENV_DIR}/bin/python"

if [ ! -f "${VENV_DIR}/.install-complete" ]; then
    echo "[!] Venv not ready — run ./install_linux.sh first."
    exit 1
fi
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
    echo "[!] No .env in ${SCRIPT_DIR} — copy .env.example and fill keys."
    exit 1
fi

# Platform wiring (platform_config env hooks)
export WHISPER_VENV="${VENV_DIR}"            # whisper_venv_lib globs site-packages (CUDA libs)
export PIPER_BIN="${VENV_DIR}/bin/piper"     # piper CLI from the venv
export AUDIO_FILE="${AUDIO_FILE:-/tmp/armchair_audio.raw}"
export ARMCHAIR_AUDIO_FILE="${AUDIO_FILE}"   # stream_to_file.sh reads this

mkdir -p /tmp/armchair /tmp/armchair_tts \
    "${HOME}/.local/share/armchair/tts" "${HOME}/.local/share/armchair/sessions"

# Bootstrap config if missing (e.g. /tmp cleared by a reboot)
if [ ! -f /tmp/armchair/agent_config.json ]; then
    cat > /tmp/armchair/agent_config.json <<'CFGEOF'
{
  "name": "Muska",
  "voice": "mustka",
  "llm_model": "deepseek-v4.1-flash",
  "persona": "You are {agent_name}, a strategic advisor. Speak only when directly addressed.",
  "tts_engine": "piper",
  "memory_dir": "/mnt/b/OpenClaw/.openclaw/workspace/agricola",
  "llm_provider": "tokenra",
  "timezone": "Australia/Brisbane",
  "tts_reference": "/mnt/b/Github/Armchair/voices/en_GB-alan-medium.wav"
}
CFGEOF
    echo " [INFO] Bootstrapped default agent config (first run or post-reboot)"
fi
if [ ! -f /tmp/armchair/mode.txt ]; then
    echo "talk" > /tmp/armchair/mode.txt
fi

cd "${SCRIPT_DIR}"

pids=()
cleanup() {
    echo ""
    echo "Shutting down..."
    for p in "${pids[@]:-}"; do kill "${p}" 2>/dev/null || true; done
    wait 2>/dev/null || true
    echo "Stopped."
}
trap cleanup EXIT INT TERM

echo "================================================"
echo " ARMCHAIR — LINUX START"
echo " Capture:   ${AUDIO_FILE} (16k mono s16le)"
echo " Dashboard: http://localhost:8765"
echo " Venv:      ${VENV_DIR}"
echo " Ctrl+C to stop"
echo "================================================"

./stream_to_file.sh & pids+=($!)
"${PY}" dashboard_server.py & pids+=($!)
"${PY}" armchair_live.py