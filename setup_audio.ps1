# setup_audio.ps1 - Armchair audio routing automation
# v2: THREE-LISTENER MATRIX - no Windows "Listen to this device" (that was the echo)
# Run: powershell -ExecutionPolicy Bypass -File setup_audio.ps1
#
# What it does:
#   1. Verifies VB-Cable + Voicemeeter devices exist (Voicemeeter REQUIRED for Talk mode)
#   2. Sets Windows default playback -> CABLE-A Input (agent TTS rides the cable to strip 2)
#   3. Prints the manual steps it cannot safely automate:
#      - default recording -> Voicemeeter Output (B1)
#      - "Listen to this device" UNCHECKED on every recording device (opens Sound panel)
#      - the Voicemeeter strip matrix + red lines
#      - call-app device settings
#
# Requires: AudioDeviceCmdlets module (auto-installed per-user if missing).

$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "  Agent In The Armchair - Audio Setup (v2 Matrix)"
Write-Host "========================================"
Write-Host ""

# --- Load AudioDeviceCmdlets module (install if missing) ---
if (-not (Get-Module -ListAvailable -Name AudioDeviceCmdlets)) {
    Write-Host "[INFO] Installing AudioDeviceCmdlets PowerShell module..."
    try {
        Install-Module -Name AudioDeviceCmdlets -Force -Scope CurrentUser
    } catch {
        Write-Host "[WARN] Could not install AudioDeviceCmdlets ($($_.Exception.Message))"
        Write-Host "       Will print manual steps instead."
    }
}

function Get-DeviceByName([string]$pattern) {
    try {
        return Get-AudioDevice -List | Where-Object { $_.Name -like $pattern } | Select-Object -First 1
    } catch { return $null }
}

$cableIn  = Get-DeviceByName "*CABLE-A Input*"
$cableOut = Get-DeviceByName "*CABLE-A Output*"
$vmOut    = Get-DeviceByName "*Voicemeeter Output*"
$vmAuxOut = Get-DeviceByName "*Voicemeeter AUX Output*"
$vmIn     = Get-DeviceByName "*Voicemeeter Input*"
$vmAuxIn  = Get-DeviceByName "*Voicemeeter AUX Input*"

if (-not $cableIn -or -not $cableOut) {
    Write-Host "[ERROR] VB-Audio Virtual Cable not found."
    Write-Host "        Install from https://vb-audio.com/Cable/ then reboot and re-run."
    exit 1
}
Write-Host "[OK] Found: $($cableIn.Name)"

if (-not $vmOut -or -not $vmAuxOut -or -not $vmIn) {
    Write-Host "[ERROR] Voicemeeter devices not found."
    Write-Host "        Voicemeeter is REQUIRED for Talk mode (three-listener matrix)."
    Write-Host "        Install from https://vb-audio.com/voicemeeter/ then reboot and re-run."
    exit 1
}
Write-Host "[OK] Found: $($vmOut.Name)"
Write-Host "[OK] Found: $($vmAuxOut.Name)"
Write-Host "[OK] Found: $($vmIn.Name)"
Write-Host ""

# --- Step 1: default playback -> CABLE-A Input ---
try {
    Set-AudioDevice -ID $cableIn.ID
    Write-Host "[OK] Windows default playback set to CABLE-A Input (agent TTS rides the cable)"
} catch {
    Write-Host "[WARN] Could not set default playback automatically."
    Write-Host "       Manual: Settings > Sound > Output > select 'CABLE-A Input'"
}

# --- Step 2: manual steps (build-dependent, not safe to automate) ---
Write-Host ""
Write-Host "MANUAL STEPS (cannot be safely automated):"
Write-Host ""
Write-Host "1. Default recording device -> 'Voicemeeter Output (VB-Audio Voicemeeter VAIO)'"
Write-Host "   Settings > Sound > Input > select it."
Write-Host ""
Write-Host "2. 'Listen to this device' must be UNCHECKED on EVERY recording device."
Write-Host "   The Listen path is a delayed duplicate of audio Voicemeeter already routes -"
Write-Host "   it is the echo. If your old setup has it ON (typically on CABLE-A Output),"
Write-Host "   uncheck it now. Opening the Sound panel..."
Start-Process control mmsys.cpl
Write-Host "   Recording tab > each device > Properties > Listen tab > uncheck > Apply."
Write-Host ""
Write-Host "3. VOICEMEETER MATRIX (one source per strip, route by bus):"
Write-Host "   Bus A1 output device: your speakers/headphones"
Write-Host "   Strip 1: Microphone (Jabra PanaCast)  - B1 + B2 ON, A1 OFF, MONO ON"
Write-Host "   Strip 2: CABLE-A Output               - A1 + B2 ON, B1 OFF"
Write-Host "   Strip 3: (empty)"
Write-Host "   Strip 4: Voicemeeter Input (VAIO)     - A1 + B1 ON, B2 OFF"
Write-Host "   Strip 5: Voicemeeter AUX Input        - spare"
Write-Host ""
Write-Host "   RED LINES (break these and you get echo):"
Write-Host "   - VAIO strip NEVER to B2           - or the remote caller hears themselves"
Write-Host "   - CABLE-A Output strip NEVER to B1 - or the agent transcribes its own TTS"
Write-Host "   - Mic strip NEVER to A1            - or your mic loops through the speakers"
Write-Host ""
Write-Host "4. CALL APP SETTINGS (explicit devices, not 'System default'):"
Write-Host "   Microphone: 'Voicemeeter AUX Output (VB-Audio Voicemeeter AUX VAIO)'  (= B2)"
Write-Host "   Speaker:    'Voicemeeter Input (VB-Audio Voicemeeter VAIO)'"
Write-Host ""
Write-Host "WHO HEARS WHOM:"
Write-Host "  You (A1):     agent TTS + remote caller - never your own voice"
Write-Host "  Agent (B1):   you + remote caller      - never its own TTS"
Write-Host "  Caller (B2):  you + agent TTS          - never their own voice"
Write-Host ""
Write-Host "========================================"
Write-Host "  Audio setup complete!"
Write-Host "========================================"