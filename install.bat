@echo off
REM ============================================================
REM  Agent In The Armchair — Windows Installer
REM  Run this once after cloning the repo.
REM  Creates venvs, installs deps, downloads Piper.
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "PARENT=%ROOT%.."
set "VENV_DIR=%PARENT%\venvs"
set "PIPER_DIR=%PARENT%\piper"
set "TMP_DIR=%PARENT%\armchair_tmp"

echo.
echo ========================================
echo   Agent In The Armchair — Installer
echo   Executive Mind
echo ========================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3.12+ and add to PATH.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^^&1') do set "PYVER=%%v"
echo [OK] %PYVER%

REM --- Create directories ---
mkdir "%VENV_DIR%" 2>nul
mkdir "%TMP_DIR%" 2>nul
mkdir "%TMP_DIR%\tts" 2>nul
mkdir "%TMP_DIR%\session_logs" 2>nul
mkdir "%PIPER_DIR%" 2>nul

REM --- Create .env from example if not exists ---
if not exist "%ROOT%.env" (
    copy "%ROOT%.env.example" "%ROOT%.env" >nul
    echo [OK] Created .env from example — edit it to add your API keys
)

REM ============================================================
REM  1. Whisper venv (faster-whisper, torch+CUDA, pyannote)
REM ============================================================
echo.
echo [1/3] Creating Whisper environment...
if exist "%VENV_DIR%\whisper\Scripts\python.exe" (
    echo   Already exists, skipping. Delete to recreate.
) else (
    python -m venv "%VENV_DIR%\whisper"
    call "%VENV_DIR%\whisper\Scripts\activate.bat"
    echo   Installing torch (CUDA)...
    pip install torch --index-url https://download.pytorch.org/whl/cu124
    echo   Installing faster-whisper, pyannote-audio, silero...
    pip install faster-whisper pyannote-audio soundfile numpy
    pip install openai-whisper
    call deactivate
    echo [OK] Whisper environment ready
)

REM ============================================================
REM  2. Kokoro venv
REM ============================================================
echo.
echo [2/3] Creating Kokoro environment...
if exist "%VENV_DIR%\kokoro\Scripts\python.exe" (
    echo   Already exists, skipping.
) else (
    python -m venv "%VENV_DIR%\kokoro"
    call "%VENV_DIR%\kokoro\Scripts\activate.bat"
    pip install torch --index-url https://download.pytorch.org/whl/cu124
    pip install kokoro soundfile numpy
    call deactivate
    echo [OK] Kokoro environment ready
)

REM ============================================================
REM  3. Chatterbox venv
REM ============================================================
echo.
echo [3/3] Creating Chatterbox environment...
if exist "%VENV_DIR%\chatterbox\Scripts\python.exe" (
    echo   Already exists, skipping.
) else (
    python -m venv "%VENV_DIR%\chatterbox"
    call "%VENV_DIR%\chatterbox\Scripts\activate.bat"
    pip install torch --index-url https://download.pytorch.org/whl/cu124
    pip install chatterbox-tts soundfile numpy
    call deactivate
    echo [OK] Chatterbox environment ready
)

REM ============================================================
REM  4. Piper (download binary + voice models)
REM ============================================================
echo.
echo [4/4] Setting up Piper...
if exist "%PIPER_DIR%\piper.exe" (
    echo   Already exists, skipping.
) else (
    echo   Downloading Piper for Windows...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/rhasspy/piper/releases/latest/download/piper_windows_amd64.zip' -OutFile '%PIPER_DIR%\piper.zip'"
    powershell -Command "Expand-Archive -Path '%PIPER_DIR%\piper.zip' -DestinationPath '%PIPER_DIR%' -Force"
    del "%PIPER_DIR%\piper.zip"
    echo [OK] Piper installed
)

REM ============================================================
REM  Done
REM ============================================================
echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo   Next steps:
echo   1. Edit .env to add your LLM API keys (if not using Ollama)
echo   2. Set up VB-Audio Virtual Cable (CABLE-A)
echo   3. Set Windows default playback to CABLE-A Input
echo   4. Run start_armchair.bat
echo.
echo   See README.md for full setup guide.
echo.
pause