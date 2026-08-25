#!/usr/bin/env python3
"""
Platform abstraction layer for Agent In The Armchair.
Detects OS and provides platform-correct paths, audio I/O, and config.

Supports:
  - WSL (Windows Subsystem for Linux) — legacy bridge mode
  - Linux-native (PipeWire/PulseAudio)
  - Windows-native (VB-Cable + PowerShell)

Usage:
  from platform_config import Platform
  pf = Platform.detect()
  audio_file = pf.audio_input_path
  playback = pf.create_audio_output()
  playback.play(wav_path)
"""
import os
import sys
import platform
import shutil
import subprocess
import time
import json
import wave


def log(tag, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


class AudioOutput:
    """Interface — play a WAV file into the meeting mix."""
    def play(self, wav_path):
        raise NotImplementedError

    def cleanup(self, wav_path):
        """Remove the wav after playback."""
        try:
            if os.path.exists(wav_path):
                os.remove(wav_path)
        except Exception:
            pass


class WindowsAudioOutput(AudioOutput):
    """Windows/WSL: copy WAV to B:\\ drive, PowerShell PlaySync."""
    def __init__(self, playback_dir):
        self.playback_dir = playback_dir
        self.powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        # On pure Windows (no WSL), use native powershell
        if not os.path.exists(self.powershell):
            self.powershell = 'powershell.exe'

    def play(self, wav_path):
        # Copy to Windows-accessible path
        basename = os.path.basename(wav_path)
        dest = os.path.join(self.playback_dir, basename)
        shutil.copy2(wav_path, dest)

        # Construct Windows path
        if dest.startswith('/mnt/'):
            drive = dest[5]
            rest = dest[6:].replace('/', '\\')
            win_path = f"{drive.upper()}:{rest}"
        else:
            win_path = dest

        try:
            result = subprocess.run(
                [self.powershell, '-c',
                 f"(New-Object System.Media.SoundPlayer '{win_path}').PlaySync()"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                log("TTS", f"PlaySync error: {result.stderr[:200]}")
        except Exception as e:
            log("TTS", f"Playback error: {e}")
        finally:
            self.cleanup(dest)

    def cleanup(self, wav_path):
        try:
            if os.path.exists(wav_path):
                os.remove(wav_path)
        except Exception:
            pass


class LinuxAudioOutput(AudioOutput):
    """Linux-native: play WAV via pw-play (PipeWire) or paplay (PulseAudio)."""
    def __init__(self, device=None):
        self.device = device  # optional: specific sink name
        self.player = shutil.which('pw-play') or shutil.which('paplay') or shutil.which('aplay')

    def play(self, wav_path):
        if not self.player:
            log("TTS", "No audio player found (pw-play/paplay/aplay)")
            return
        cmd = [self.player]
        if self.device and self.player == 'pw-play':
            cmd += ['--target', self.device]
        elif self.device and self.player == 'paplay':
            cmd += ['-d', self.device]
        cmd.append(wav_path)
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception as e:
            log("TTS", f"Playback error: {e}")
        finally:
            self.cleanup(wav_path)


class Platform:
    """Base platform config. Subclasses override path strategies."""
    name = "base"

    def __init__(self):
        self.home = os.path.expanduser("~")
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

    # --- Paths (override in subclasses) ---
    @property
    def audio_input_path(self): raise NotImplementedError
    @property
    def tmp_dir(self): raise NotImplementedError
    @property
    def tts_output_dir(self): raise NotImplementedError
    @property
    def session_log_dir(self): raise NotImplementedError
    @property
    def piper_bin(self): raise NotImplementedError
    @property
    def piper_models_dir(self): raise NotImplementedError
    @property
    def chatterbox_python(self): raise NotImplementedError
    @property
    def kokoro_python(self): raise NotImplementedError
    @property
    def whisper_cache_dir(self): raise NotImplementedError
    @property
    def whisper_venv_lib(self): raise NotImplementedError

    # --- Audio I/O ---
    def create_audio_output(self) -> AudioOutput:
        raise NotImplementedError

    # --- Env / secrets ---
    @property
    def env_file(self):
        return os.path.join(self.script_dir, '.env')

    @property
    def hf_token_file(self):
        return None  # let .env or os.environ handle it

    @staticmethod
    def detect():
        """Detect platform and return the right Platform instance."""
        system = platform.system()
        if system == 'Linux':
            if os.path.exists('/proc/sys/fs/binfmt_misc/WSLInterop'):
                return WSLPlatform()
            return LinuxPlatform()
        elif system == 'Windows':
            return WindowsPlatform()
        else:
            raise RuntimeError(f"Unsupported platform: {system}")


class WSLPlatform(Platform):
    """WSL bridge mode — legacy. Uses /mnt/b for Windows-accessible paths."""
    name = "wsl"

    @property
    def audio_input_path(self):
        return os.environ.get('AUDIO_FILE', '/mnt/b/armchair_audio.raw')

    @property
    def tmp_dir(self):
        return '/tmp/armchair_tts'

    @property
    def tts_output_dir(self):
        return '/mnt/b/armchair_tmp/tts'

    @property
    def session_log_dir(self):
        return '/mnt/b/armchair_tmp/session_logs'

    @property
    def piper_bin(self):
        return os.environ.get('PIPER_BIN', '/home/krisr/.local/bin/piper')

    @property
    def piper_models_dir(self):
        return os.environ.get('PIPER_MODELS_DIR', '/home/krisr/.local/share/piper')

    @property
    def chatterbox_python(self):
        return os.environ.get('CHATTERBOX_PY', '/home/krisr/.local/share/chatterbox-venv/bin/python')

    @property
    def kokoro_python(self):
        return os.environ.get('KOKORO_PY', '/home/krisr/.local/share/kokoro-venv/bin/python')

    @property
    def whisper_cache_dir(self):
        return os.environ.get('WHISPER_CACHE', '/home/krisr/.local/share/whisper')

    @property
    def whisper_venv_lib(self):
        return '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages'

    def create_audio_output(self):
        return WindowsAudioOutput('/mnt/b/armchair_tmp')


class LinuxPlatform(Platform):
    """Linux-native. Uses XDG dirs, PipeWire for audio."""
    name = "linux"

    @property
    def audio_input_path(self):
        return os.environ.get('AUDIO_FILE', '/tmp/armchair_audio.raw')

    @property
    def tmp_dir(self):
        return '/tmp/armchair_tts'

    @property
    def tts_output_dir(self):
        return os.path.expanduser('~/.local/share/armchair/tts')

    @property
    def session_log_dir(self):
        return os.path.expanduser('~/.local/share/armchair/sessions')

    @property
    def piper_bin(self):
        return os.environ.get('PIPER_BIN', shutil.which('piper') or '/usr/local/bin/piper')

    @property
    def piper_models_dir(self):
        return os.environ.get('PIPER_MODELS_DIR', os.path.expanduser('~/.local/share/piper'))

    @property
    def chatterbox_python(self):
        return os.environ.get('CHATTERBOX_PY', os.path.expanduser('~/.local/share/chatterbox-venv/bin/python'))

    @property
    def kokoro_python(self):
        return os.environ.get('KOKORO_PY', os.path.expanduser('~/.local/share/kokoro-venv/bin/python'))

    @property
    def whisper_cache_dir(self):
        return os.environ.get('WHISPER_CACHE', os.path.expanduser('~/.cache/whisper'))

    @property
    def whisper_venv_lib(self):
        # On Linux-native, whisper deps are in the main venv or system
        # Return the venv lib path if we can find it
        venv = os.environ.get('WHISPER_VENV', '')
        if venv:
            import glob
            libs = glob.glob(os.path.join(venv, 'lib', 'python*', 'site-packages'))
            if libs:
                return libs[0]
        return None  # None means "use system paths"

    def create_audio_output(self):
        device = os.environ.get('TTS_OUTPUT_DEVICE', '') or None
        return LinuxAudioOutput(device=device)


class WindowsPlatform(Platform):
    r"""Windows-native (no WSL). Pure Windows paths.

    Expected layout:
      C:\armchair\
        Armchair\          <- repo (cloned)
        venvs\              <- whisper, kokoro, chatterbox venvs
        piper\              <- piper.exe + voice models
        armchair_tmp\       <- session logs, TTS output
    """
    name = "windows"

    def __init__(self):
        super().__init__()
        # Parent of the repo dir = C:\armchair\
        self._root = os.path.dirname(self.script_dir)

    @property
    def audio_input_path(self):
        return os.environ.get('AUDIO_FILE', os.path.join(self._root, 'armchair_audio.raw'))

    @property
    def tmp_dir(self):
        return os.path.join(os.environ.get('TEMP', self._root), 'armchair_tts')

    @property
    def tts_output_dir(self):
        return os.path.join(self._root, 'armchair_tmp', 'tts')

    @property
    def session_log_dir(self):
        return os.path.join(self._root, 'armchair_tmp', 'session_logs')

    @property
    def piper_bin(self):
        return os.environ.get('PIPER_BIN', os.path.join(self._root, 'piper', 'piper.exe'))

    @property
    def piper_models_dir(self):
        return os.environ.get('PIPER_MODELS_DIR', os.path.join(self._root, 'piper'))

    @property
    def chatterbox_python(self):
        return os.environ.get('CHATTERBOX_PY', os.path.join(self._root, 'venvs', 'chatterbox', 'Scripts', 'python.exe'))

    @property
    def kokoro_python(self):
        return os.environ.get('KOKORO_PY', os.path.join(self._root, 'venvs', 'kokoro', 'Scripts', 'python.exe'))

    @property
    def whisper_cache_dir(self):
        return os.environ.get('WHISPER_CACHE', os.path.join(self.home, '.cache', 'whisper'))

    @property
    def whisper_venv_lib(self):
        return None  # Windows uses venv site-packages directly, no LD_LIBRARY_PATH needed

    def create_audio_output(self):
        playback_dir = os.path.join(self._root, 'armchair_tmp')
        return WindowsAudioOutput(playback_dir)