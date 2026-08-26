@echo off
REM ============================================================
REM  Agent In The Armchair - Windows Installer
REM  Run this once after cloning the repo.
REM  Creates venvs, installs deps, downloads Piper, VB-Cable.
REM ============================================================

setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "PARENT=%ROOT%.."
set "VENV_DIR=%PARENT%\venvs"
set "PIPER_DIR=%PARENT%\piper"
set "TMP_DIR=%PARENT%\armchair_tmp"

echo.
echo ========================================
echo   Agent In The Armchair - Installer
echo   Executive Mind
echo ========================================
echo.
echo   ROOT: %ROOT%
echo   PARENT: %PARENT%
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH. Install Python 3.12+ and add to PATH.
    echo         https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [OK] %PYVER%

REM --- Check ffmpeg ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "C:\Users\%USERNAME%\Documents\ffmpeg\ffmpeg.exe" (
        echo [OK] ffmpeg found at C:\Users\%USERNAME%\Documents\ffmpeg\
    ) else (
        echo [INFO] ffmpeg not found - downloading local copy...
        if not exist "%ROOT%ffmpeg" mkdir "%ROOT%ffmpeg"
        powershell -Command "try { Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile '%ROOT%ffmpeg\ffmpeg.zip' -ErrorAction Stop; echo 'Downloaded' } catch { echo 'Download failed'; exit 1 }"
        if exist "%ROOT%ffmpeg\ffmpeg.zip" (
            powershell -Command "Expand-Archive -Path '%ROOT%ffmpeg\ffmpeg.zip' -DestinationPath '%ROOT%ffmpeg' -Force"
            for /d %%d in ("%ROOT%ffmpeg\ffmpeg-*") do set "FFMPEG_DIR=%%d"
            copy "%FFMPEG_DIR%\bin\ffmpeg.exe" "%ROOT%ffmpeg\ffmpeg.exe" >nul
            del "%ROOT%ffmpeg\ffmpeg.zip" 2>nul
            rmdir /s /q "%FFMPEG_DIR%" 2>nul
            if exist "%ROOT%ffmpeg\ffmpeg.exe" (
                echo [OK] ffmpeg downloaded to %ROOT%ffmpeg
                echo      Set FFMPEG_PATH in .env to point at it
            ) else (
                echo [WARN] ffmpeg extraction failed. Download manually: https://ffmpeg.org/download.html
            )
        ) else (
            echo [WARN] Could not download ffmpeg. Get it from https://ffmpeg.org/download.html
        )
    )
) else (
    echo [OK] ffmpeg on PATH
)

REM --- Create directories ---
echo [INFO] Creating directories...
mkdir "%VENV_DIR%" 2>nul
mkdir "%TMP_DIR%" 2>nul
mkdir "%TMP_DIR%\tts" 2>nul
mkdir "%TMP_DIR%\session_logs" 2>nul
mkdir "%PIPER_DIR%" 2>nul

REM --- Create .env from example if not exists ---
if not exist "%ROOT%.env" (
    copy "%ROOT%.env.example" "%ROOT%.env" >nul
    echo [OK] Created .env from example
) else (
    echo [OK] .env already exists
)

REM ============================================================
REM  1. Whisper venv (faster-whisper, torch+CUDA, pyannote)
REM ============================================================
echo.
echo [1/5] Creating Whisper environment...
if exist "%VENV_DIR%\whisper\Scripts\python.exe" (
    echo   Already exists, skipping. Delete to recreate.
) else (
    echo   Creating venv...
    python -m venv "%VENV_DIR%\whisper"
    if not exist "%VENV_DIR%\whisper\Scripts\python.exe" (
        echo [ERROR] Failed to create whisper venv
        pause
        exit /b 1
    )
    call "%VENV_DIR%\whisper\Scripts\activate.bat"
    echo   Installing torch CUDA 12.8...
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
    if errorlevel 1 (
        echo [ERROR] torch install failed. Check your CUDA version.
        pause
        exit /b 1
    )
    call :verify_torch_cuda "whisper"
    if !TORCH_CUDA_OK! EQU 0 (
        echo [WARN] torch is CPU-only! Reinstalling with CUDA index...
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 --force-reinstall
        call :verify_torch_cuda "whisper"
    )
    echo   Installing faster-whisper, pyannote-audio...
    pip install faster-whisper pyannote-audio soundfile numpy
    call deactivate
    echo [OK] Whisper environment ready
)

REM ============================================================
REM  2. Kokoro venv
REM ============================================================
echo.
echo [2/5] Creating Kokoro environment...
if exist "%VENV_DIR%\kokoro\Scripts\python.exe" (
    echo   Already exists, skipping.
) else (
    echo   Creating venv...
    python -m venv "%VENV_DIR%\kokoro"
    call "%VENV_DIR%\kokoro\Scripts\activate.bat"
    echo   Installing torch CUDA 12.8...
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
    call :verify_torch_cuda "kokoro"
    if !TORCH_CUDA_OK! EQU 0 (
        echo [WARN] torch is CPU-only! Reinstalling with CUDA index...
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 --force-reinstall
        call :verify_torch_cuda "kokoro"
    )
    echo   Installing kokoro...
    pip install kokoro soundfile numpy
    call deactivate
    echo [OK] Kokoro environment ready
)

REM ============================================================
REM  3. Chatterbox venv
REM ============================================================
echo.
echo [3/5] Creating Chatterbox environment...
if exist "%VENV_DIR%\chatterbox\Scripts\python.exe" (
    echo   Already exists, skipping.
) else (
    echo   Creating venv...
    python -m venv "%VENV_DIR%\chatterbox"
    call "%VENV_DIR%\chatterbox\Scripts\activate.bat"
    echo   Installing torch CUDA 12.8...
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
    call :verify_torch_cuda "chatterbox"
    if !TORCH_CUDA_OK! EQU 0 (
        echo [WARN] torch is CPU-only! Reinstalling with CUDA index...
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 --force-reinstall
        call :verify_torch_cuda "chatterbox"
    )
    echo   Installing chatterbox...
    pip install chatterbox-tts soundfile numpy
    call deactivate
    echo [OK] Chatterbox environment ready
)

REM ============================================================
REM  4. Piper (download binary)
REM ============================================================
echo.
echo [4/5] Setting up Piper...
if exist "%PIPER_DIR%\piper.exe" (
    echo   Already exists, skipping.
) else (
    echo   Downloading Piper for Windows...
    powershell -Command "try { Invoke-WebRequest -Uri 'https://github.com/rhasspy/piper/releases/latest/download/piper_windows_amd64.zip' -OutFile '%PIPER_DIR%\piper.zip' -ErrorAction Stop; echo 'Downloaded' } catch { echo 'Download failed'; exit 1 }"
    if exist "%PIPER_DIR%\piper.zip" (
        powershell -Command "Expand-Archive -Path '%PIPER_DIR%\piper.zip' -DestinationPath '%PIPER_DIR%' -Force"
        REM flatten nested piper\piper folder from the zip
        if exist "%PIPER_DIR%\piper\piper.exe" (
            move /y "%PIPER_DIR%\piper\*" "%PIPER_DIR%" >nul
            rmdir /s /q "%PIPER_DIR%\piper"
        )
        del "%PIPER_DIR%\piper.zip"
        echo [OK] Piper installed
    ) else (
        echo   [WARN] Could not download Piper. Get it manually from:
        echo         https://github.com/rhasspy/piper/releases
    )
)

REM ============================================================
REM  5. VB-Audio Virtual Cable (CABLE-A)
REM ============================================================
echo.
echo [5/5] Checking VB-Audio Virtual Cable...
powershell -Command "Get-WmiObject Win32_SoundDevice | Select-Object Name" 2>nul | findstr /i "CABLE" >nul
if not errorlevel 1 (
    echo   VB-Cable already installed, skipping.
) else (
    echo   VB-Cable not found. Downloading...
    powershell -Command "try { Invoke-WebRequest -Uri 'https://download.vb-audio.com/Download_CABLE/253/VBCABLE_Setup_x64.exe' -OutFile '%PARENT%\VBCABLE_Setup.exe' -ErrorAction Stop; echo 'Downloaded' } catch { echo 'Download failed'; exit 1 }"
    if exist "%PARENT%\VBCABLE_Setup.exe" (
        echo   Running VB-Cable installer - requires admin...
        echo   NOTE: If prompted by UAC, click Yes. Then click Install in the VB-Cable window.
        powershell -Command "Start-Process '%PARENT%\VBCABLE_Setup.exe' -Verb RunAs -Wait"
        del "%PARENT%\VBCABLE_Setup.exe" 2>nul
        echo [OK] VB-Cable install attempted
    ) else (
        echo   [WARN] Could not auto-download. Install manually from:
        echo         https://vb-audio.com/Cable/
    )
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
echo   1. Edit .env to add your LLM API keys if not using Ollama
echo   2. Run setup_audio.ps1 to configure audio routing
echo   3. Run start_armchair.bat (opens the Piper voices page on first run)
echo.
echo   See README.md for full setup guide.
echo.
pause
exit /b 0

:verify_torch_cuda
REM %1 = venv name. Checks installed torch reports CUDA support.
set "TORCH_CUDA_OK=0"
for /f "delims=" %%i in ('python -c "import torch; print(1 if torch.cuda.is_available() else 0)" 2^>nul') do set "TORCH_CUDA_OK=%%i"
if "%TORCH_CUDA_OK%"=="1" (
    echo   [OK] torch %~1: CUDA available
) else (
    echo   [CHECK] torch %~1: CUDA not reported ^(CPU build or no driver^)
)
exit /b 0