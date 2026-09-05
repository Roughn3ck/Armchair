@echo off
REM setup_audio.bat - Configure Windows audio routing for Agent In The Armchair
REM v2: THREE-LISTENER MATRIX - replaces the old "Listen to this device" setup (it echoed)
REM Run this BEFORE starting your call app (Teams, Zoom, Signal, Meet...) + Armchair pipeline
REM
REM This is a GUIDE - it walks you through the manual Windows/Voicemeeter settings.
REM No audio device changes are automated.

echo ================================================
echo AGENT IN THE ARMCHAIR - AUDIO SETUP (v2 MATRIX)
echo ================================================
echo.
echo THREE LISTENERS - every Voicemeeter bus is one listener's ears:
echo   A1  speakers                      = YOU (agent TTS + remote caller)
echo   B1  "Voicemeeter Output" rec dev  = AGENT/PIPELINE (you + remote caller)
echo   B2  "Voicemeeter AUX Output" rec  = REMOTE CALLER (you + agent TTS)
echo.
echo RULE: No Windows "Listen to this device" anywhere. Voicemeeter does all routing.
echo   (Old setup had Listen ON - it is a delayed duplicate of audio Voicemeeter
echo    already routes. That was the echo. UNCHECK IT.)
echo.
echo ================================================
echo.
echo STEP 1: Windows Sound settings
echo.
echo   Playback devices: set DEFAULT to "CABLE-A Input (VB-Audio Virtual Cable A)"
echo     (the agent's TTS plays here - it arrives on Voicemeeter's CABLE-A Output strip)
echo   Recording devices: set DEFAULT to "Voicemeeter Output (VB-Audio Voicemeeter VAIO)"
echo   Recording devices: on EACH device, Properties, Listen tab:
echo     "Listen to this device" must be UNCHECKED on ALL of them
echo.
echo ================================================
echo.
echo STEP 2: Voicemeeter - one source per strip, route by bus
echo.
echo   Bus A1 output device: your speakers/headphones
echo   Strip 1: Microphone (Jabra PanaCast)  - B1 + B2 ON, A1 OFF, MONO ON
echo   Strip 2: CABLE-A Output               - A1 + B2 ON, B1 OFF
echo   Strip 3: (empty)
echo   Strip 4: Voicemeeter Input (VAIO)     - A1 + B1 ON, B2 OFF
echo   Strip 5: Voicemeeter AUX Input        - spare
echo.
echo   RED LINES (break these and you get echo):
echo     - VAIO strip NEVER to B2           - or the remote caller hears themselves
echo     - CABLE-A Output strip NEVER to B1 - or the agent transcribes its own TTS
echo     - Mic strip NEVER to A1            - or your mic loops through the speakers
echo.
echo ================================================
echo.
echo STEP 3: Call app settings (explicit devices, not "System default")
echo.
echo   Open your call app (Teams, Zoom, Signal, Meet - whichever you use)
echo   Settings, Audio / Devices
echo   Microphone: "Voicemeeter AUX Output (VB-Audio Voicemeeter AUX VAIO)"
echo   Speaker:    "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"
echo   Noise suppression: Off or Low (let Whisper handle it)
echo.
echo ================================================
echo.
echo STEP 4: Verify VB-Cable + Voicemeeter are installed
echo.

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -list_devices true -f dshow -i dummy 2>&1 | findstr /C:"CABLE-A Output" >nul
if %errorlevel%==0 (
    echo [OK] CABLE-A Output detected - VB-Audio Virtual Cable A is installed
) else (
    echo [WARNING] CABLE-A Output not found!
    echo Download VB-Audio Virtual Cable from https://vb-audio.com/Cable/
)

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -list_devices true -f dshow -i dummy 2>&1 | findstr /C:"Voicemeeter Output" >nul
if %errorlevel%==0 (
    echo [OK] Voicemeeter detected
) else (
    echo [WARNING] Voicemeeter not found - REQUIRED for Talk mode (the matrix).
    echo Download from https://vb-audio.com/voicemeeter/
)

echo.
echo ================================================
echo.
echo STEP 5: Test the pipeline feed (5 seconds) - records bus B1
echo.
echo   SPEAK INTO YOUR MIC while this runs. The file must not be empty.
echo.

C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe -y -f dshow -i "audio=Voicemeeter Output (VB-Audio Voicemeeter VAIO)" -ac 1 -ar 16000 -sample_fmt s16 -t 5 B:\armchair_test.raw 2>nul

if exist B:\armchair_test.raw (
    for %%A in (B:\armchair_test.raw) do echo Test capture: %%~zA bytes
    if %%~zA GTR 0 (
        echo [OK] Mic is reaching B1 - the agent/pipeline feed is live.
    ) else (
        echo [WARNING] Capture file is empty. Check:
        echo   - Voicemeeter is running
        echo   - Strip 1 (mic) has B1 ON and you spoke during the test
    )
    del B:\armchair_test.raw
) else (
    echo [WARNING] No audio captured. Check:
    echo   - "Voicemeeter Output" exists as a recording device (Voicemeeter installed)
    echo   - Voicemeeter is running - B1 is its bus
)

echo.
echo Ready to start the pipeline?
echo   1. Run start_armchair.bat (audio + dashboard + pipeline + browser)
echo   2. Talk mode: see the capture-repoint note in STATUS.md (pending live test)
echo.
pause

exit /b 0