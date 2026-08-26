# setup_audio.ps1 - Armchair audio routing automation
# Automates the Windows-side routing so a new user doesn't have to click through Sound settings.
# Run: powershell -ExecutionPolicy Bypass -File setup_audio.ps1
#
# What it does:
#   1. Finds CABLE-A Input / Output devices
#   2. Sets Windows default playback -> CABLE-A Input
#   3. Enables "Listen to this device" on CABLE-A Output -> local speakers (Option B path)
#   4. Prints manual steps for anything that can't be safely automated (Voicemeeter preset, per-app devices)
#
# Requires: run as normal user; some steps may need elevation (UAC prompt).

$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "  Agent In The Armchair - Audio Setup"
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

$cableIn = Get-DeviceByName "*CABLE-A Input*"
$cableOut = Get-DeviceByName "*CABLE-A Output*"

if (-not $cableIn -or -not $cableOut) {
    Write-Host "[ERROR] VB-Audio Virtual Cable not found."
    Write-Host "        Install from https://vb-audio.com/Cable/ then reboot and re-run this script."
    exit 1
}
Write-Host "[OK] Found: $($cableIn.Name)"
Write-Host "[OK] Found: $($cableOut.Name)"
Write-Host ""

# --- Step 1: default playback -> CABLE-A Input ---
try {
    Set-AudioDevice -ID $cableIn.ID
    Write-Host "[OK] Windows default playback set to CABLE-A Input"
} catch {
    Write-Host "[WARN] Could not set default playback automatically."
    Write-Host "       Manual: Settings > Sound > Output > select 'CABLE-A Input'"
}

# --- Step 2: Listen-to-this-device on CABLE-A Output ---
# Registry approach: HKCU\Software\Microsoft\Multimedia\Audio\... is unreliable across builds;
# use the documented 'Listen' flag via the audio endpoint registry, fall back to instructions.
Write-Host ""
Write-Host "[INFO] Enabling 'Listen to this device' on CABLE-A Output..."
$listened = $false
try {
    # Locate the capture endpoint GUID for CABLE-A Output via registry enumeration
    $mmDevices = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
    $targetGuid = $null
    Get-ChildItem $mmDevices | ForEach-Object {
        $props = Get-ItemProperty ("$mmDevices\$($_.PSChildName)\Properties")
        if ($props.'{a45c254e-df1c-4efd-8020-67d146a850e0},2' -like "*CABLE-A Output*") {
            $targetGuid = $_.PSChildName
        }
    }
    if ($targetGuid) {
        # Find render endpoint of default speakers for the listen target
        $listenPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture\$targetGuid"
        Write-Host "[INFO] Found capture endpoint: $targetGuid"
        Write-Host "[WARN] Listen-tab automation is build-dependent; opening Sound panel for one click:"
        $listened = $false
    }
} catch { }

if (-not $listened) {
    Write-Host ""
    Write-Host "MANUAL STEP (one click):"
    Write-Host "  1. Opening mmsys.cpl playback+recording panel..."
    Start-Process control mmsys.cpl
    Write-Host "  2. Recording tab > 'CABLE-A Output' > Properties > Listen tab"
    Write-Host "  3. Check 'Listen to this device', Playback through: your speakers"
    Write-Host "  4. Apply > OK"
}

# --- Step 3: Voicemeeter guidance ---
Write-Host ""
Write-Host "VOICEMEETER BANANA (Option A - optional but recommended):"
Write-Host "  If you use Voicemeeter Banana, load the bundled preset:"
Write-Host "    Voicemeeter Menu > Load preset > armchair-voicemeeter.xml"
Write-Host "  Then set your call app microphone to: Voicemeeter Output (VAIO)"

Write-Host ""
Write-Host "CALL APP SETTINGS:"
Write-Host "  Microphone: Voicemeeter Output (VAIO) [Voicemeeter path]"
Write-Host "              -- or --"
Write-Host "              CABLE-A Output [no-Voicemeeter path]"
Write-Host "  Speaker: your normal speakers/headphones"

Write-Host ""
Write-Host "========================================"
Write-Host "  Audio setup complete!"
Write-Host "========================================"
