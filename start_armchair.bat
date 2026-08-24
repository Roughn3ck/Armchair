@echo off
REM start_armchair.bat — One-click launch for Agent In The Armchair
REM Starts: audio capture + dashboard + pipeline + browser
REM
REM Usage: Double-click start_armchair.bat
REM Stop:  Ctrl+C in the pipeline window (saves session on exit)

echo ================================================
echo AGENT IN THE ARMCHAIR — Starting
echo ================================================
echo.

REM Step 1: Start audio capture in a new window
echo [1/4] Starting audio capture...
start "Armchair Audio Capture" cmd /k "cd /d B:\Github\Armchair && stream_to_file.bat"
timeout /t 2 /nobreak >nul

REM Step 2: Start dashboard server in WSL (background)
echo [2/4] Starting dashboard server...
start /b wsl bash -c "python3 /mnt/b/Github/Armchair/dashboard_server.py &"
timeout /t 2 /nobreak >nul

REM Step 3: Open browser
echo [3/4] Opening dashboard...
start http://localhost:8765
timeout /t 1 /nobreak >nul

REM Step 4: Start pipeline in WSL (foreground — Ctrl+C to stop and save session)
echo [4/4] Starting pipeline...
echo.
echo ================================================
echo Pipeline running. Press Ctrl+C to stop and save session.
echo ================================================
echo.

wsl bash -c "export $(grep HF_TOKEN /mnt/b/OpenClaw/.openclaw/.env) && /home/krisr/.local/share/whisper-venv/bin/python3 /mnt/b/Github/Armchair/armchair_live.py"

REM After pipeline stops, clean up
echo.
echo ================================================
echo Session saved. Cleaning up...
echo ================================================
REM Kill dashboard server
wsl bash -c "pkill -f dashboard_server.py" 2>nul
REM Close audio capture window
taskkill /fi "WINDOWTITLE eq Armchair Audio Capture*" /f 2>nul
echo Done.
pause