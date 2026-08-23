@echo off
REM stream_to_file.bat — Captures Teams meeting audio to raw file for WSL Armchair pipeline
REM Teams speaker must be set to "CABLE-A Input (VB-Audio Virtual Cable A)"
REM You hear the meeting via CABLE-A Output "Listen" tab → stereo speakers
REM
REM Usage: stream_to_file.bat
REM Stop: Ctrl+C

echo ================================================
echo AGENT IN THE ARMCHAIR — AUDIO CAPTURE
echo ================================================
echo.
echo Capturing from: CABLE-A Output (VB-Audio Virtual Cable A)
echo Writing to: B:\armchair_audio.raw
echo Format: 16kHz mono 16-bit PCM (Whisper-optimized)
echo.
echo Teams mic: Jabra PanaCast 20 (unchanged)
echo Teams speaker: CABLE-A Input (VB-Audio Virtual Cable A)
echo You hear via: CABLE-A Output ^> Listen ^> stereo speakers
echo.
echo Press Ctrl+C to stop
echo ================================================
echo.

REM Delete old capture file to start fresh
if exist B:\armchair_audio.raw del B:\armchair_audio.raw

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -y -f dshow -i "audio=CABLE-A Output (VB-Audio Virtual Cable A)" -ac 1 -ar 16000 -sample_fmt s16 -f s16le B:\armchair_audio.raw