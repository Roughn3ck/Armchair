@echo off
REM setup_audio.bat - Configure Windows audio routing for Agent In The Armchair
REM Run this BEFORE starting your call app (Teams, Zoom, Signal, Meet...) + Armchair pipeline
REM
REM This is a GUIDE - it walks you through the manual Windows settings.
REM No audio device changes are automated (safer than scripting nircmd).

echo ================================================
echo AGENT IN THE ARMCHAIR - AUDIO SETUP
echo ================================================
echo.
echo This sets up ONE-WAY audio capture (listen only, no TTS):
echo   Call app audio (Teams, Zoom, Signal, Meet... - whichever you use) ^> CABLE-A Input ^> CABLE-A Output ^> ffmpeg ^> armchair_audio.raw
echo   You hear the meeting through your stereo speakers (via Listen tab)
echo   Your call app mic stays on your normal microphone (unchanged)
echo.
echo ================================================
echo.
echo STEP 1: Set Your Call App Speaker to CABLE-A Input
echo.
echo   Open your communication app (Teams, Zoom, Signal, Meet - whichever you use)
echo   Settings ^> Audio / Devices
echo   Speaker: "CABLE-A Input (VB-Audio Virtual Cable A)"
echo   Microphone: "Jabra PanaCast 20" (keep as-is)
echo   Noise suppression: Off or Low (let Whisper handle it)
echo.
echo ================================================
echo.
echo STEP 2: Enable "Listen" on CABLE-A Output so you hear the meeting
echo.
echo   Right-click speaker icon in taskbar ^> Sound Settings
echo   ^> More sound settings (Control Panel)
echo   ^> Playback tab ^> select your stereo speakers ^> Set Default
echo   ^> Recording tab ^> find "CABLE-A Output" ^> Properties
echo   ^> Listen tab
echo   ^> Check "Listen to this device"
echo   ^> Playback through: select your stereo speakers
echo   ^> Apply ^> OK
echo.
echo Now: Your call app plays to CABLE-A Input, ffmpeg captures CABLE-A Output,
echo   and you hear everything through your stereo speakers.
echo.
echo ================================================
echo.
echo STEP 3: Verify VB-Cable A is installed
echo.

REM Check if CABLE-A Output exists as a capture device
C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -list_devices true -f dshow -i dummy 2>&1 | findstr /C:"CABLE-A Output" >nul
if %errorlevel%==0 (
    echo [OK] CABLE-A Output detected - VB-Audio Virtual Cable A is installed
) else (
    echo [WARNING] CABLE-A Output not found!
    echo Download VB-Audio Virtual Cable from https://vb-audio.com/Cable/
    echo Install and restart before running the pipeline.
)

echo.
echo ================================================
echo.
echo STEP 4: Test capture (5 seconds)
echo.

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -y -f dshow -i "audio=CABLE-A Output (VB-Audio Virtual Cable A)" -ac 1 -ar 16000 -sample_fmt s16 -t 5 B:\armchair_test.raw 2>nul

if exist B:\armchair_test.raw (
    for %%A in (B:\armchair_test.raw) do echo Test capture: %%~zA bytes
    if %%~zA GTR 0 (
        echo [OK] Audio capture is working!
    ) else (
        echo [WARNING] Capture file is empty. Play some audio and try again.
    )
    del B:\armchair_test.raw
) else (
    echo [WARNING] No audio captured. Check:
    echo   - CABLE-A Output exists
    echo   - Your call app is playing audio through CABLE-A Input
    echo   - "Listen to this device" is enabled on CABLE-A Output
)

echo.
echo Ready to start the pipeline?
echo   1. Run stream_to_file.bat (Windows - captures audio)
echo   2. Run: python3 armchair_live.py (WSL - transcribes)
echo   3. Open http://localhost:8765 (dashboard)
echo.
pause

pause

exit /b 0
