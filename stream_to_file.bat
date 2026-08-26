@echo off
REM stream_to_file.bat - Captures meeting audio + your mic to raw file
REM Meeting audio: CABLE-A Output (VB-Audio Virtual Cable)
REM Microphone: configurable below
REM Both mixed into one 16kHz mono stream
REM
REM Usage: stream_to_file.bat
REM Stop: Ctrl+C

REM ============================================================
REM  CONFIG - edit these for your setup
REM ============================================================
set "OUTPUT_FILE=%~dp0..\armchair_audio.raw"
set "FFMPEG=C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe"
set "CABLE_DEVICE=CABLE-A Output (VB-Audio Virtual Cable A)"
set "MIC_DEVICE=Microphone (Jabra PanaCast 20)"

REM Override via env vars if set
if defined ARMCHAIR_AUDIO_FILE set "OUTPUT_FILE=%ARMCHAIR_AUDIO_FILE%"
if defined FFMPEG_PATH set "FFMPEG=%FFMPEG_PATH%"
if defined ARMCHAIR_CABLE_DEVICE set "CABLE_DEVICE=%ARMCHAIR_CABLE_DEVICE%"
if defined ARMCHAIR_MIC_DEVICE set "MIC_DEVICE=%ARMCHAIR_MIC_DEVICE%"

echo ================================================
echo AGENT IN THE ARMCHAIR - AUDIO CAPTURE
echo ================================================
echo.
echo Capturing from:
echo   Meeting audio: %CABLE_DEVICE%
echo   Your microphone: %MIC_DEVICE%
echo Writing to: %OUTPUT_FILE%
echo Format: 16kHz mono 16-bit PCM (Whisper-optimized)
echo.
echo Press Ctrl+C to stop
echo ================================================
echo.

REM Delete old capture file
if exist "%OUTPUT_FILE%" del "%OUTPUT_FILE%"

"%FFMPEG%" -y ^
  -f dshow -i "audio=%CABLE_DEVICE%" ^
  -f dshow -i "audio=%MIC_DEVICE%" ^
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]" ^
  -map "[a]" ^
  -ac 1 -ar 16000 -sample_fmt s16 -f s16le "%OUTPUT_FILE%"