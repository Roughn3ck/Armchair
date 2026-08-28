@echo off
REM ============================================================
REM  Agent In The Armchair - Windows Launcher (single window)
REM  Starts audio capture + dashboard + pipeline in one process.
REM  Ctrl+C stops everything cleanly.
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "PARENT=%ROOT%.."
set "WHISPER_VENV=%PARENT%\venvs\whisper"
set "WHISPER_PY=%WHISPER_VENV%\Scripts\python.exe"

REM --- Check venvs exist ---
if not exist "%WHISPER_PY%" (
    echo [ERROR] Whisper venv not found. Run install.bat first.
    pause
    exit /b 1
)

REM --- Audio config ---
set "OUTPUT_FILE=%PARENT%\armchair_audio.raw"
set "FFMPEG=C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe"
if defined FFMPEG_PATH set "FFMPEG=%FFMPEG_PATH%"
if defined ARMCHAIR_CABLE_DEVICE (
    set "CABLE_DEVICE=%ARMCHAIR_CABLE_DEVICE%"
) else (
    set "CABLE_DEVICE=CABLE-A Output (VB-Audio Virtual Cable A)"
)
if defined ARMCHAIR_MIC_DEVICE (
    set "MIC_DEVICE=%ARMCHAIR_MIC_DEVICE%"
) else (
    set "MIC_DEVICE=Microphone (Jabra PanaCast 20)"
)

REM --- Piper voices check: repo ships starter voices; open catalog only if none exist ---
set "PIPER_VOICES_FOUND=0"
set "VOICES_DIR=%ROOT%voices"
for %%f in ("%VOICES_DIR%\*.onnx") do set "PIPER_VOICES_FOUND=1"
if "%PIPER_VOICES_FOUND%"=="0" (
    echo [INFO] No Piper voices found in %VOICES_DIR%
    echo [INFO] Note: the .wav files in voices\ are just previews - Piper needs the .onnx model
    start "" "https://github.com/rhasspy/piper/blob/master/VOICES.md"
    timeout /t 5 /nobreak >nul
)

REM --- Check ffmpeg ---
if not exist "%FFMPEG%" (
    where ffmpeg >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] ffmpeg not found. Set FFMPEG_PATH in .env or install to PATH.
        pause
        exit /b 1
    )
    set "FFMPEG=ffmpeg"
)

echo ================================================
echo   Agent In The Armchair - Executive Mind v2.6
echo ================================================
echo.

REM --- Kill any stale Armchair processes (prevents double-pipeline zombies) ---
REM (Must run BEFORE capture start, or it kills the fresh ffmpeg)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*armchair_live.py*' -or $_.CommandLine -like '*dashboard_server.py*' -or $_.CommandLine -like '*chatterbox_worker.py*' -or $_.CommandLine -like '*kokoro_worker.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
taskkill /f /im ffmpeg.exe >nul 2>&1

REM --- Delete old capture file ---
if exist "%OUTPUT_FILE%" del "%OUTPUT_FILE%"

REM --- Start audio capture (background, no window) ---
echo [INFO] Starting audio capture...
start /b "" "%FFMPEG%" -y ^
  -f dshow -i "audio=%CABLE_DEVICE%" ^
  -f dshow -i "audio=%MIC_DEVICE%" ^
  -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]" ^
  -map "[a]" ^
  -ac 1 -ar 16000 -sample_fmt s16 -f s16le "%OUTPUT_FILE%" >nul 2>&1

REM --- Wait for audio file to appear ---
timeout /t 2 /nobreak >nul

REM --- Start dashboard server (background, no window) ---
echo [INFO] Starting dashboard on http://localhost:8765 ...
start /b "" "%WHISPER_PY%" "%ROOT%dashboard_server.py" >nul 2>&1
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -Uri 'http://localhost:8765/api/status' -UseBasicParsing -TimeoutSec 3; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Dashboard did not respond on port 8765. Something else may be holding the port.
    echo        Check with: netstat -ano ^| findstr :8765
) else (
    echo [OK] Dashboard is up.
)

REM --- Open browser ---
timeout /t 1 /nobreak >nul
start http://localhost:8765

REM --- Start main pipeline (foreground - Ctrl+C stops here) ---
echo [INFO] Starting pipeline...
echo.
echo ================================================================
echo   TO STOP: Press Ctrl+C, then answer N if asked
echo            "Terminate batch job (Y/N)?" so cleanup runs.
echo   (Or simply close this window - the pipeline saves automatically
echo    on shutdown, and the next start cleans up any leftovers.)
echo ================================================================
echo.
"%WHISPER_PY%" "%ROOT%armchair_live.py" %*

REM ============================================================
REM  Cleanup - runs after pipeline exits (Ctrl+C or error)
REM ============================================================
echo.
echo [INFO] Stopping all components...

REM Kill ffmpeg (audio capture) and any TTS workers
taskkill /f /im ffmpeg.exe >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*chatterbox_worker.py*' -or $_.CommandLine -like '*kokoro_worker.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM Kill dashboard server
REM (wmic is deprecated/removed on Win11 24H2+ - use PowerShell CIM)
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*dashboard_server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM Clean up audio file
if exist "%OUTPUT_FILE%" del "%OUTPUT_FILE%" 2>nul

echo [INFO] All stopped. Session archived.
pause