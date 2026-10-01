#!/usr/bin/env bash
# stream_to_file.sh — Linux audio capture for Agent In The Armchair
# PipeWire/Pulse capture of the mic -> 16kHz mono s16le raw file
# Mirrors stream_to_file.bat (same Whisper-optimized format).
# Usage: ./stream_to_file.sh   (Stop: Ctrl+C)
set -euo pipefail

OUTPUT_FILE="${ARMCHAIR_AUDIO_FILE:-/tmp/armchair_audio.raw}"
SOURCE="${ARMCHAIR_CAPTURE_SOURCE:-default}"

echo "================================================"
echo " ARMCHAIR - LINUX AUDIO CAPTURE"
echo "================================================"
echo " Source:  ${SOURCE}"
echo " Writing: ${OUTPUT_FILE}"
echo " Format:  16kHz mono 16-bit PCM (Whisper-optimized)"
echo " Ctrl+C to stop"
echo "================================================"

rm -f "${OUTPUT_FILE}"
exec ffmpeg -y -f pulse -i "${SOURCE}" -ac 1 -ar 16000 -sample_fmt s16 -f s16le "${OUTPUT_FILE}"
