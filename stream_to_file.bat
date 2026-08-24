@echo off
REM stream_to_file.bat — Captures Teams meeting audio + your mic to raw file
REM Teams speaker: CABLE-A Input (meeting audio you hear)
REM Your mic: Jabra PanaCast 20 (your voice)
REM Both are mixed together into one 16kHz mono stream
REM
REM Usage: stream_to_file.bat
REM Stop: Ctrl+C

echo ================================================
echo AGENT IN THE ARMCHAIR — AUDIO CAPTURE
echo ================================================
echo.
echo Capturing from:
echo   Meeting audio: CABLE-A Output (VB-Audio Virtual Cable A)
echo   Your microphone: Microphone (Jabra PanaCast 20)
echo Writing to: B:\armchair_audio.raw
echo Format: 16kHz mono 16-bit PCM (Whisper-optimized)
echo.
echo Press Ctrl+C to stop
echo ================================================
echo.

REM Delete old capture file to start fresh
if exist B:\armchair_audio.raw del B:\armchair_audio.raw

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -y ^
  -f dshow -i "audio=CABLE-A Output (VB-Audio Virtual Cable A)" ^
  -f dshow -i "audio=Microphone (Jabra PanaCast 20)" ^
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]" ^
  -map "[a]" ^
  -ac 1 -ar 16000 -sample_fmt s16 -f s16le B:\armchair_audio.raw