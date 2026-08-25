@echo off
REM ============================================================
REM  Agent In The Armchair — Windows Launcher (single window)
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
echo   Agent In The Armchair — Executive Mind v2.6
echo ================================================
echo.

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

REM --- Open browser ---
timeout /t 1 /nobreak >nul
start http://localhost:8765

REM --- Start main pipeline (foreground — Ctrl+C stops here) ---
echo [INFO] Starting pipeline...
echo [INFO] Press Ctrl+C to stop (session saves automatically)
echo.
"%WHISPER_PY%" "%ROOT%armchair_live.py" %*

REM ============================================================
REM  Cleanup — runs after pipeline exits (Ctrl+C or error)
REM ============================================================
echo.
echo [INFO] Stopping all components...

REM Kill ffmpeg (audio capture)
taskkill /f /im ffmpeg.exe >nul 2>&1

REM Kill dashboard server
REM Find the python process running dashboard_server.py and kill it
for /f "tokens=2" %%p in ('wmic process where "commandline like %%dashboard_server.py%%" get processid /value 2^>nul ^| findstr processid') do (
    taskkill /f /pid %%p >nul 2>&1
)

REM Clean up audio file
if exist "%OUTPUT_FILE%" del "%OUTPUT_FILE%" 2>nul

echo [INFO] All stopped. Session archived.
pause