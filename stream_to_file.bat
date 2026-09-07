@echo off
REM stream_to_file.bat - Captures meeting audio from the Voicemeeter B1 bus
REM B1 = your mic + the remote caller (no agent TTS self-hear) per the
REM three-listener matrix (see README "Audio Routing").
REM
REM Usage: stream_to_file.bat
REM Stop: Ctrl+C

REM ============================================================
REM  CONFIG - edit these for your setup
REM ============================================================
set "OUTPUT_FILE=%~dp0..\armchair_audio.raw"
set "FFMPEG=C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe"
set "CAPTURE_DEVICE=Voicemeeter Out B1 (VB-Audio Voicemeeter VAIO)"

REM Override via env vars if set
if defined ARMCHAIR_AUDIO_FILE set "OUTPUT_FILE=%ARMCHAIR_AUDIO_FILE%"
if defined FFMPEG_PATH set "FFMPEG=%FFMPEG_PATH%"
if defined ARMCHAIR_CAPTURE_DEVICE set "CAPTURE_DEVICE=%ARMCHAIR_CAPTURE_DEVICE%"

echo ================================================
echo AGENT IN THE ARMCHAIR - AUDIO CAPTURE
echo ================================================
echo.
echo Capturing from: %CAPTURE_DEVICE%
echo Writing to: %OUTPUT_FILE%
echo Format: 16kHz mono 16-bit PCM (Whisper-optimized)
echo.
echo Press Ctrl+C to stop
echo ================================================
echo.

REM Delete old capture file
if exist "%OUTPUT_FILE%" del "%OUTPUT_FILE%"

"%FFMPEG%" -y ^
  -f dshow -i "audio=%CAPTURE_DEVICE%" ^
  -ac 1 -ar 16000 -sample_fmt s16 -f s16le "%OUTPUT_FILE%"
