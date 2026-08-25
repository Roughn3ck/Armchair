@echo off
REM ============================================================
REM  Agent In The Armchair — Windows Launcher
REM  Starts dashboard server + main pipeline, opens browser.
REM  Press Ctrl+C to stop (session saves automatically).
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

REM --- Check audio file (will be created by stream_to_file.bat) ---
REM Start the audio capture in a separate window
if exist "%ROOT%stream_to_file.bat" (
    echo [INFO] Starting audio capture...
    start "Armchair Audio" cmd /c "%ROOT%stream_to_file.bat"
    timeout /t 3 /nobreak >nul
)

REM --- Start dashboard server ---
echo [INFO] Starting dashboard server on http://localhost:8765 ...
start "Armchair Dashboard" "%WHISPER_PY%" "%ROOT%dashboard_server.py"

REM --- Open browser ---
timeout /t 1 /nobreak >nul
start http://localhost:8765

REM --- Start main pipeline ---
echo [INFO] Starting pipeline...
echo [INFO] Press Ctrl+C to stop (session saves automatically)
echo.
"%WHISPER_PY%" "%ROOT%armchair_live.py" %*

REM --- Cleanup on exit ---
echo.
echo [INFO] Pipeline stopped. Cleaning up...
taskkill /fi "WINDOWTITLE eq Armchair Dashboard*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq Armchair Audio*" /f >nul 2>&1
echo [INFO] Done.
pause