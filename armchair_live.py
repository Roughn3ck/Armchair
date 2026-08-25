#!/usr/bin/env python3
r"""
Agent In The Armchair — Streaming VTT + AI Agent for MS Teams

Architecture (v2 — streaming):
  Windows ffmpeg -> B:\armchair_audio.raw (16kHz mono PCM, continuous stream)
  WSL reads /mnt/b/armchair_audio.raw continuously
    -> Silero VAD (detects speech, skips silence — nearly free)
    -> faster-whisper streaming (local agreement policy, incremental output)
    -> pyannote-audio (16s rolling buffer, every 10s — speaker labels)
    -> Dashboard (live transcript with speaker labels on http://localhost:8765)

  Talk mode (when enabled):
    -> LLM gate: "Is the agent being directly addressed?"
    -> If yes: LLM generates response -> Piper TTS -> meeting
    -> If no: [SILENCE] — agent stays quiet

  Post-call:
    -> Transcript saved with speaker labels
    -> Agent's own responses logged

Usage:
  python3 armchair_live.py [--whisper-model MODEL] [--agent-name NAME] [--voice VOICE]
  python3 armchair_live.py --agent-name Agricola --voice en_US-norman-medium
"""

import struct
import wave
import os
import sys
import time
import json
import signal
import argparse
import threading
import subprocess
import urllib.request
import shutil
import re
import numpy as np

# Add whisper_streaming to path
sys.path.insert(0, '/tmp/whisper_streaming')

# ============================================================
# CONFIG
# ============================================================
AUDIO_FILE = "/mnt/b/armchair_audio.raw"
SAMPLE_RATE = 16000
SILENCE_THRESHOLD = 3  # % amplitude — fallback silence detection
READ_INTERVAL = 0.5   # How often to read from the raw file (seconds)
READ_CHUNK = 8000      # 0.5s of audio per read (16kHz * 0.5s * 2 bytes)

# Whisper config
WHISPER_MODEL_DEFAULT = "large-v3-turbo"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "float16"

# VAD config (Silero)
VAD_THRESHOLD = 0.5    # Speech probability threshold
VAD_MIN_SPEECH = 0.25   # Min seconds of speech to trigger
VAD_MAX_BUFFER = 10    # Max seconds of audio in Whisper buffer

# Diarization config
DIARIZE_INTERVAL = 10  # Re-run diarization every N seconds
DIAR_BUFFER_SECONDS = 16  # Rolling buffer for diarization

# LLM config (Ollama)
LLM_MODEL_DEFAULT = "deepseek-v4-flash:cloud"
LLM_API_HOST = "localhost"
LLM_API_PORT = 11434
LLM_API_PATH = "/api/chat"
LLM_MAX_TOKENS = 150
LLM_TEMPERATURE = 0.7

# TTS config (engines)
TTS_VOICE_DEFAULT = "en_GB-alan-medium"
TTS_ENGINE_DEFAULT = "piper"  # piper | kokoro | chatterbox
PIPER_BIN = "/home/krisr/.local/bin/piper"
PIPER_MODELS_DIR = "/home/krisr/.local/share/piper"
CHATTERBOX_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_workers", "chatterbox_worker.py")
CHATTERBOX_PY = "/home/krisr/.local/share/chatterbox-venv/bin/python"
KOKORO_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_workers", "kokoro_worker.py")
KOKORO_PY = "/home/krisr/.local/share/kokoro-venv/bin/python"
# Hard-wired for now — Muska voice reference (break out to config later)
CHATTERBOX_REF_DEFAULT = "/home/krisr/.local/share/chatterbox/muska-reference.wav"
KOKORO_VOICE_DEFAULT = "af_heart"
TTS_OUTPUT_DIR = "/mnt/b/armchair_tmp/tts"

# Agent defaults
AGENT_NAME_DEFAULT = "Agricola"
AGENT_PERSONA_DEFAULT = (
    "You are {agent_name}, a strategic advisor participating in a Microsoft Teams meeting. "
    "You are calm, measured, and speak only when directly addressed. "
    "Your responses are concise and strategic. "
    "Never use asterisks, markdown, bullet points, or special characters. Plain English only. "
    "Say as much as the situation demands — no more, no less. "
    "If you are NOT being directly addressed (someone is just mentioning your name in conversation), "
    "respond with exactly: [SILENCE] "
    "If you ARE being directly addressed, respond with your message. "
    "Do not repeat yourself. Do not announce that you are staying silent."
)

# Pipeline state files
TRANSCRIPT_FILE = "/tmp/armchair/transcript.txt"
LATENCY_FILE = "/tmp/armchair/latency.txt"
MODE_FILE = "/tmp/armchair/mode.txt"
PREWARM_FILE = "/tmp/armchair/tts_prewarm.txt"
SPEAKER_NAMES_FILE = "/tmp/armchair/speaker_names.json"
DETECTED_SPEAKERS_FILE = "/tmp/armchair/detected_speakers.json"
AGENT_CONFIG_FILE = "/tmp/armchair/agent_config.json"
TTS_PLAYBACK_DIR = "/mnt/b/armchair_tmp"
TTS_OUTPUT_DIR = "/mnt/b/armchair_tmp/tts"

# Session logs — archived to Windows side
SESSION_LOG_DIR = "/mnt/b/armchair_tmp/session_logs"

# Identity folder — agent context files loaded on startup
IDENTITY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Identity")

# Whisper hallucination filter
SKIP_PHRASES = {
    "thanks for watching", "subscribe", "the end", "thank you",
    "thank you.", "you", "bye", "bye-bye", "bye bye", "goodbye",
    "see you next time", "i'll see you next time",
    "we'll see you next time", "we'll be right back"
}


def log(tag, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


def clean_for_speech(text):
    """Strip markdown and special characters for TTS."""
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'^[-*] ', '', text, flags=re.MULTILINE)
    text = text.replace('_', ' ')
    text = text.replace('"', '')
    text = re.sub(r'[\[\](){}]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ============================================================
# STATE MANAGEMENT
# ============================================================
def load_json(path, default):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default


def save_json(path, data):
    try:
        with open(path, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log("STATE", f"Failed to save {path}: {e}")


def get_mode():
    try:
        with open(MODE_FILE, 'r') as f:
            return f.read().strip()
    except:
        return 'listen'


def get_speaker_names():
    return load_json(SPEAKER_NAMES_FILE, {})


def get_agent_config():
    return load_json(AGENT_CONFIG_FILE, {
        'name': AGENT_NAME_DEFAULT,
        'voice': TTS_VOICE_DEFAULT,
        'llm_model': LLM_MODEL_DEFAULT,
        'persona': AGENT_PERSONA_DEFAULT,
        'tts_engine': TTS_ENGINE_DEFAULT,
        'tts_reference': CHATTERBOX_REF_DEFAULT,
        'memory_dir': '',
    })


def format_speaker(speaker_id, names=None):
    if names and speaker_id in names and names[speaker_id]:
        return names[speaker_id]
    return speaker_id


def load_identity(identity_dir):
    """Load all .md and .txt files from the Identity folder (including memory/ subfolder).
    Returns concatenated text for the LLM system prompt.
    """
    if not os.path.isdir(identity_dir):
        log("IDENTITY", f"Folder not found: {identity_dir}")
        return ""

    context_parts = []

    # Load files from the Identity folder
    for fname in sorted(os.listdir(identity_dir)):
        fpath = os.path.join(identity_dir, fname)
        if os.path.isfile(fpath) and fname.lower().endswith(('.md', '.txt')):
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content:
                    context_parts.append(f"--- {fname} ---\n{content}")
                    log("IDENTITY", f"Loaded: {fname} ({len(content)} chars)")
            except Exception as e:
                log("IDENTITY", f"Error reading {fname}: {e}")

    # Load files from memory/ subfolder
    memory_dir = os.path.join(identity_dir, "memory")
    if os.path.isdir(memory_dir):
        for fname in sorted(os.listdir(memory_dir)):
            fpath = os.path.join(memory_dir, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(('.md', '.txt')):
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                    if content:
                        context_parts.append(f"--- memory/{fname} ---\n{content}")
                        log("IDENTITY", f"Loaded: memory/{fname} ({len(content)} chars)")
                except Exception as e:
                    log("IDENTITY", f"Error reading memory/{fname}: {e}")

    if context_parts:
        log("IDENTITY", f"Loaded {len(context_parts)} files, {sum(len(p) for p in context_parts)} chars total")
    else:
        log("IDENTITY", "No identity files found — using default persona only")

    return "\n\n".join(context_parts)


# ============================================================
# AUDIO READER (continuous stream from raw file)
# ============================================================
class AudioStreamReader:
    """Reads the raw PCM file continuously, like a stream."""

    def __init__(self, audio_file, read_chunk=READ_CHUNK):
        self.audio_file = audio_file
        self.read_chunk = read_chunk  # bytes per read
        self.offset = 0
        self._caught_up = False

    def read(self):
        """Read available audio data. Returns numpy float32 array or None."""
        if not os.path.exists(self.audio_file):
            return None
        try:
            current_size = os.path.getsize(self.audio_file)
        except OSError:
            return None

        # Skip to end on first read (don't process old audio)
        if not self._caught_up:
            if current_size >= self.read_chunk:
                self.offset = current_size
                self._caught_up = True
                log("STREAM", f"Caught up to end of file (offset={self.offset})")
            else:
                return None

        if current_size < self.offset:
            # File was reset
            self.offset = 0
            return None

        available = current_size - self.offset
        if available < 1024:  # Need at least 512 samples (1024 bytes)
            return None

        try:
            with open(self.audio_file, 'rb') as f:
                f.seek(self.offset)
                raw = f.read(available)
            self.offset = current_size

            # Convert raw 16-bit PCM to float32 numpy array
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            return samples

        except OSError:
            return None


# ============================================================
# VAD (Silero Voice Activity Detection)
# ============================================================
class VAD:
    """Silero VAD — detects speech in audio chunks. Nearly free on GPU."""

    def __init__(self, threshold=VAD_THRESHOLD, min_speech_sec=VAD_MIN_SPEECH):
        import torch
        self.model = torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)[0]
        self.threshold = threshold
        self.min_speech_sec = min_speech_sec
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False
        self.speech_buffer = []
        self.sample_rate = 16000
        # Silero expects 512 samples (32ms at 16kHz)
        self.frame_size = 512
        log("VAD", f"Silero VAD loaded (threshold={threshold})")

    def process(self, audio_samples):
        """Process a chunk of audio. Returns speech audio or None (silence)."""
        import torch

        # Process in 512-sample frames
        offset = 0
        speech_output = []

        while offset + self.frame_size <= len(audio_samples):
            frame = audio_samples[offset:offset + self.frame_size]
            offset += self.frame_size

            # Get speech probability
            with torch.no_grad():
                prob = self.model(torch.from_numpy(frame), self.sample_rate).item()

            if prob >= self.threshold:
                self.speech_frames += 1
                self.speech_buffer.append(frame)
                if not self.is_speaking:
                    self.is_speaking = True
            else:
                self.silence_frames += 1
                if self.is_speaking:
                    # End of speech utterance
                    self.is_speaking = False

        # Return accumulated speech if we have any
        if self.speech_buffer:
            speech = np.concatenate(self.speech_buffer)
            self.speech_buffer = []
            return speech

        return None


# ============================================================
# STREAMING TRANSCRIBER (faster-whisper with local agreement)
# ============================================================
class StreamingTranscriber:
    """Streaming transcription using faster-whisper with word timestamps.

    Returns word-level segments that can be matched to pyannote speaker labels.
    """

    def __init__(self, model_name, device="cuda", compute_type="float16"):
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['XDG_CACHE_HOME'] = '/home/krisr/.local/share/whisper'
        cuda = '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages/nvidia/cublas/lib'
        nvrtc = '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib'
        ld = os.environ.get('LD_LIBRARY_PATH', '')
        os.environ['LD_LIBRARY_PATH'] = f"{cuda}:{nvrtc}:{ld}"

        import ctypes
        for lib in ['libcublas.so.12', 'libcublasLt.so.12', 'libcudart.so.12']:
            for d in [cuda, nvrtc]:
                path = os.path.join(d, lib)
                if os.path.exists(path):
                    try:
                        ctypes.CDLL(path)
                    except OSError:
                        pass
                    break

        from faster_whisper import WhisperModel
        log("STT", f"Loading {model_name} ({device}/{compute_type})...")
        self.model = WhisperModel(model_name, device=device, compute_type=compute_type)
        log("STT", "Model loaded")

        self.audio_buffer = np.array([], dtype=np.float32)
        self.last_output_end = 0.0  # Timestamp of last output word
        self.max_buffer = VAD_MAX_BUFFER * 16000
        self._buffer_start_time = 0.0  # Time offset of buffer start

    def add_speech(self, audio):
        """Add VAD-detected speech to the buffer."""
        self.audio_buffer = np.append(self.audio_buffer, audio)
        if len(self.audio_buffer) > self.max_buffer:
            excess = len(self.audio_buffer) - self.max_buffer
            self.audio_buffer = self.audio_buffer[excess:]
            self._buffer_start_time += excess / 16000.0
            self.last_output_end -= excess / 16000.0
            if self.last_output_end < 0:
                self.last_output_end = 0.0

    def transcribe_with_timestamps(self):
        """Transcribe buffer. Returns list of (start_time, end_time, text) segments."""
        if len(self.audio_buffer) < 1600:
            return []

        try:
            import warnings
            with warnings.catch_warnings():
                # faster-whisper emits harmless "Mean of empty slice" warnings on
                # sub-second VAD blips — silence them
                warnings.simplefilter("ignore", RuntimeWarning)
                with np.errstate(all="ignore"):
                    segments, _ = self.model.transcribe(
                        self.audio_buffer, beam_size=5, language='en',
                        vad_filter=False,
                        condition_on_previous_text=False,
                        word_timestamps=True
                    )
                    result = []
                    for seg in segments:
                        result.append({
                            'start': seg.start,
                            'end': seg.end,
                            'text': seg.text.strip()
                        })
            return result

        except Exception as e:
            log("STT", f"Error: {e}")
            return []

    def get_new_segments(self):
        """Transcribe and return only segments after last_output_end."""
        all_segs = self.transcribe_with_timestamps()
        new_segs = [s for s in all_segs if s['end'] > self.last_output_end + 0.1]
        if all_segs:
            self.last_output_end = all_segs[-1]['end']
        return new_segs

    def clear(self):
        """Clear buffer."""
        self.audio_buffer = np.array([], dtype=np.float32)
        self.last_output_end = 0.0
        self._buffer_start_time = 0.0


# ============================================================
# SPEAKER DIARIZATION (pyannote-audio, rolling buffer)
# ============================================================
class Diarizer:
    """Rolling buffer diarization. Runs every 10s on 16s of audio."""

    def __init__(self):
        log("DIAR", "Loading pyannote-audio pipeline...")
        import torch

        torch.backends.cudnn.enabled = False  # Avoid cu12/cu13 conflict

        token = os.environ.get('HF_TOKEN', '')
        if not token:
            try:
                with open('/mnt/b/OpenClaw/.openclaw/.env', 'r') as f:
                    for line in f:
                        if line.startswith('HF_TOKEN='):
                            token = line.strip().split('=', 1)[1]
                            break
            except Exception:
                pass

        from pyannote.audio import Pipeline
        self.pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=token if token else None
        )

        if torch.cuda.is_available():
            self.pipeline.to(torch.device("cuda"))
            log("DIAR", f"Pipeline loaded on CUDA ({torch.cuda.get_device_name(0)})")
        else:
            log("DIAR", "CUDA not available, running on CPU")

        self.buffer = bytearray()
        self.buffer_max = DIAR_BUFFER_SECONDS * 16000 * 2
        self.last_diarize_time = 0
        self.speaker_map = {}
        self.speaker_count = 0
        self.current_speaker = "SPEAKER_00"
        self._has_result = False
        self._cached_segments = [(0, 999, "SPEAKER_00")]
        log("DIAR", f"Ready (16s rolling buffer, diarize every {DIARIZE_INTERVAL}s)")

    def add_audio(self, pcm_bytes):
        """Add audio to the rolling buffer."""
        self.buffer.extend(pcm_bytes)
        if len(self.buffer) > self.buffer_max:
            excess = len(self.buffer) - self.buffer_max
            del self.buffer[:excess]

    def get_speaker_segments(self):
        """Run diarization and return list of (start, end, speaker_label) segments.
        Re-runs every DIARIZE_INTERVAL seconds, returns cached result between runs.
        """
        now = time.time()
        if self._has_result and (now - self.last_diarize_time) < DIARIZE_INTERVAL:
            return self._cached_segments

        if len(self.buffer) < 128000 * 2:  # Need at least 8s
            return [(0, 999, self.current_speaker)]

        self.last_diarize_time = now
        self._has_result = True

        import torch
        import soundfile as sf
        import tempfile

        tmp_wav = tempfile.NamedTemporaryFile(suffix='.wav', dir='/tmp/armchair', delete=False)
        tmp_wav.close()
        try:
            with wave.open(tmp_wav.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(bytes(self.buffer))

            audio_data, _ = sf.read(tmp_wav.name, dtype='float32')
            waveform = torch.from_numpy(audio_data).unsqueeze(0)

            result = self.pipeline({"waveform": waveform, "sample_rate": 16000})
            diarization = result.speaker_diarization

            # Extract all speaker segments with timestamps
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                # Map to stable label
                if speaker not in self.speaker_map:
                    stable_label = f"SPEAKER_{self.speaker_count:02d}"
                    self.speaker_map[speaker] = stable_label
                    self.speaker_count += 1
                    log("DIAR", f"New speaker: {speaker} -> {stable_label} ({self.speaker_count} total)")
                stable = self.speaker_map[speaker]
                segments.append((turn.start, turn.end, stable))

            if not segments:
                segments = [(0, 999, self.current_speaker)]

            self._cached_segments = segments
            self.current_speaker = segments[-1][2]

            # Write detected speakers for dashboard
            all_speakers = sorted(set(self.speaker_map.values()))
            save_json(DETECTED_SPEAKERS_FILE, all_speakers)

            # Log if multiple speakers
            unique_speakers = set(s[2] for s in segments)
            if len(unique_speakers) > 1:
                log("DIAR", f"Speakers: {sorted(unique_speakers)}")

            return segments

        except Exception as e:
            log("DIAR", f"Error: {e}")
            return [(0, 999, self.current_speaker)]
        finally:
            if os.path.exists(tmp_wav.name):
                os.remove(tmp_wav.name)

    def get_speaker_for_time(self, t, segments=None):
        """Get speaker label for a specific timestamp."""
        if segments is None:
            segments = self._cached_segments if self._has_result else [(0, 999, self.current_speaker)]
        for start, end, speaker in segments:
            if start <= t <= end:
                return speaker
        return self.current_speaker


# ============================================================
# LLM THINKER (Ollama API)
# ============================================================
class Thinker:
    def __init__(self, model_id, agent_name, persona, identity_context=""):
        self.model_id = model_id
        self.agent_name = agent_name
        self.persona = persona.replace('{agent_name}', agent_name)
        # Prepend identity context to the system prompt
        if identity_context:
            self.persona = f"{identity_context}\n\n--- PERSONA ---\n{self.persona}"
            log("LLM", f"System prompt: {len(self.persona)} chars (identity + persona)")
        self.conversation = []

    def think(self, transcript):
        if not transcript or len(transcript) < 5:
            return None

        self.conversation.append({
            "role": "user",
            "content": f"Recent transcript:\n{transcript}\n\nAre you being directly addressed? If so, respond. If not, respond with [SILENCE]."
        })

        if len(self.conversation) > 20:
            self.conversation = self.conversation[-20:]

        payload = json.dumps({
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self.persona},
                *self.conversation
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_predict": LLM_MAX_TOKENS,
                "temperature": LLM_TEMPERATURE
            }
        })

        try:
            req = urllib.request.Request(
                f"http://{LLM_API_HOST}:{LLM_API_PORT}{LLM_API_PATH}",
                data=payload.encode('utf-8'),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                response_text = result.get("message", {}).get("content", "").strip()

                if response_text:
                    if "[SILENCE]" in response_text.upper():
                        self.conversation.append({"role": "assistant", "content": "[SILENCE]"})
                        return None
                    self.conversation.append({"role": "assistant", "content": response_text})
                    return response_text
                return None
        except Exception as e:
            log("LLM", f"Error: {e}")
            return None


# ============================================================
# TTS SPEAKER (multi-engine: piper | kokoro | chatterbox)
# ============================================================
# Global worker pool — keeps engines loaded across Speaker rebuilds.
# Swapping voices/engines reuses warm workers instead of killing them.
_WORKER_POOL = {}

def get_worker(engine):
    """Get or lazily create the persistent worker for an engine."""
    if engine not in _WORKER_POOL:
        if engine == "kokoro":
            _WORKER_POOL[engine] = EngineWorker("kokoro", KOKORO_PY, KOKORO_WORKER)
        elif engine == "chatterbox":
            _WORKER_POOL[engine] = EngineWorker("chatterbox", CHATTERBOX_PY, CHATTERBOX_WORKER)
        else:
            return None
    return _WORKER_POOL[engine]


class EngineWorker:
    """Persistent worker subprocess (kokoro / chatterbox venv).
    JSON-over-stdin protocol. Model loads once, reused per utterance.
    """
    def __init__(self, name, py_bin, worker_script):
        self.name = name
        self.py_bin = py_bin
        self.worker_script = worker_script
        self.proc = None
        self.lock = threading.Lock()

    def _start(self):
        log("TTS", f"Starting {self.name} worker ({self.py_bin})...")
        self.proc = subprocess.Popen(
            [self.py_bin, self.worker_script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1
        )
        # Wait for ready event
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"{self.name} worker died during startup")
            try:
                evt = json.loads(line.strip())
                if evt.get("event") in ("loaded", "ready"):
                    break
            except json.JSONDecodeError:
                continue
        log("TTS", f"{self.name} worker ready")

    def generate(self, text, out_path, ref=None):
        with self.lock:
            for attempt in range(2):
                try:
                    if self.proc is None or self.proc.poll() is not None:
                        self._start()
                    req = {"text": text, "out": out_path}
                    if ref:
                        req["ref"] = ref
                    self.proc.stdin.write(json.dumps(req) + "\n")
                    self.proc.stdin.flush()
                    resp = None
                    while resp is None:
                        resp_line = self.proc.stdout.readline()
                        if not resp_line:
                            raise RuntimeError("worker closed stdout")
                        try:
                            resp = json.loads(resp_line.strip())
                        except json.JSONDecodeError:
                            log("TTS", f"{self.name} non-JSON stdout: {resp_line.strip()[:120]}")
                    if resp.get("ok"):
                        return True
                    raise RuntimeError(resp.get("error", "unknown worker error"))
                except Exception as e:
                    log("TTS", f"{self.name} attempt {attempt+1} failed: {e}")
                    try:
                        if self.proc:
                            self.proc.kill()
                    except Exception:
                        pass
                    self.proc = None
            return False

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
        except Exception:
            try:
                if self.proc:
                    self.proc.kill()
            except Exception:
                pass
        self.proc = None


class Speaker:
    """TTS speaker — dispatches to piper | kokoro | chatterbox.
    All engines produce a WAV in TTS_OUTPUT_DIR; playback path is shared.
    """
    def __init__(self, voice_model, engine="piper", tts_reference=None):
        self.engine = engine
        self.voice_model = voice_model
        self.tts_reference = tts_reference or CHATTERBOX_REF_DEFAULT
        self.speaking = False
        os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
        os.makedirs(TTS_PLAYBACK_DIR, exist_ok=True)

        self.worker = None  # lazily created for kokoro/chatterbox

        if engine == "piper":
            self.voice_path = os.path.join(PIPER_MODELS_DIR, f"{voice_model}.onnx")
            self.config_path = os.path.join(PIPER_MODELS_DIR, f"{voice_model}.onnx.json")
            if not os.path.exists(self.voice_path):
                log("TTS", f"WARNING: Voice not found: {self.voice_path}")
                self.voice_path = None
            else:
                log("TTS", f"Engine: piper, voice: {voice_model}")
        elif engine == "kokoro":
            log("TTS", f"Engine: kokoro, voice: {KOKORO_VOICE_DEFAULT}")
        elif engine == "chatterbox":
            if not os.path.exists(self.tts_reference):
                log("TTS", f"WARNING: Reference wav not found: {self.tts_reference}")
            else:
                log("TTS", f"Engine: chatterbox, reference: {self.tts_reference}")
        else:
            raise ValueError(f"Unknown TTS engine: {engine}")

    def speak_and_release(self, text, agent_name):
        try:
            self.speak(text, agent_name)
        finally:
            self.speaking = False

    def _generate_piper(self, text, wav_path):
        result = subprocess.run(
            [PIPER_BIN, "-m", self.voice_path, "-c", self.config_path,
             "--length-scale", "0.8",
             "-f", wav_path],
            input=text, capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            log("TTS", f"Piper error (rc={result.returncode}): {result.stderr[:200]}")
        return os.path.exists(wav_path)

    def speak(self, text, agent_name):
        if not text or len(text) < 3:
            return
        if self.engine == "piper" and not self.voice_path:
            log("TTS", "Skipping: no piper voice loaded")
            return

        timestamp = int(time.time() * 1000)
        # Generate on native WSL fs (/tmp) — reliable & fast; only playback copies over drvfs
        os.makedirs("/tmp/armchair_tts", exist_ok=True)
        wav_path = f"/tmp/armchair_tts/agent_{timestamp}.wav"
        wsl_playback = f"{TTS_PLAYBACK_DIR}/agent_{timestamp}.wav"
        win_playback = f"B:\\armchair_tmp\\agent_{timestamp}.wav"

        log("TTS", f"Generating ({self.engine}): {text[:100]}")

        try:
            if self.engine == "piper":
                if not self._generate_piper(text, wav_path):
                    log("TTS", "Failed to generate audio (piper)")
                    return
            elif self.engine == "kokoro":
                if not get_worker("kokoro").generate(text, wav_path):
                    log("TTS", "Failed to generate audio (kokoro)")
                    return
            elif self.engine == "chatterbox":
                if not get_worker("chatterbox").generate(text, wav_path, ref=self.tts_reference):
                    log("TTS", "Failed to generate audio (chatterbox)")
                    return

            # Worker confirms ok only AFTER closing the file — but cold-start
            # writes can lag; give it up to 15s to become visible
            for _ in range(150):
                if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
                    break
                time.sleep(0.1)
            else:
                # Worker said ok — trust it and attempt the copy anyway
                log("TTS", f"WAV slow to appear, trying copy anyway: {wav_path}")

            # Shared playback path (Windows-side PowerShell PlaySync)
            shutil.copy2(wav_path, wsl_playback)
            if not os.path.exists(wsl_playback):
                log("TTS", f"ERROR: WAV not copied to {wsl_playback}")
                return

            log("TTS", f"WAV ready: {win_playback}")
            powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
            play_cmd = [
                powershell, '-c',
                f"(New-Object System.Media.SoundPlayer '{win_playback}').PlaySync()"
            ]
            log("TTS", f"{agent_name}: {text[:80]}...")
            result = subprocess.run(play_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                log("TTS", f"PlaySync error: {result.stderr[:200]}")

        except subprocess.TimeoutExpired:
            log("TTS", "Timeout")
        except Exception as e:
            log("TTS", f"Error: {e}")
        finally:
            for p in [wav_path, wsl_playback]:
                if os.path.exists(p):
                    os.remove(p)


# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    import subprocess

    parser = argparse.ArgumentParser(description="Agent In The Armchair — Streaming VTT")
    parser.add_argument("--whisper-model", default=WHISPER_MODEL_DEFAULT)
    parser.add_argument("--agent-name", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--llm", default=None)
    parser.add_argument("--no-diarization", action="store_true")
    parser.add_argument("--no-tts", action="store_true")
    args = parser.parse_args()

    os.makedirs("/tmp/armchair", exist_ok=True)
    os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TTS_PLAYBACK_DIR, exist_ok=True)

    # Create session folder
    session_start = time.strftime("%Y-%m-%d_%H%M%S")
    session_dir = os.path.join(SESSION_LOG_DIR, session_start)
    os.makedirs(session_dir, exist_ok=True)
    log("SESSION", f"Session started: {session_dir}")

    # Load agent config
    agent_config = get_agent_config()
    if args.agent_name:
        agent_config['name'] = args.agent_name
    if args.voice:
        agent_config['voice'] = args.voice
    if args.llm:
        agent_config['llm_model'] = args.llm
    save_json(AGENT_CONFIG_FILE, agent_config)

    agent_name = agent_config['name']
    voice_model = agent_config['voice']
    llm_model = agent_config.get('llm_model', LLM_MODEL_DEFAULT)
    persona = agent_config.get('persona', AGENT_PERSONA_DEFAULT)
    tts_engine = agent_config.get('tts_engine', TTS_ENGINE_DEFAULT)
    tts_reference = agent_config.get('tts_reference', CHATTERBOX_REF_DEFAULT)

    # Load identity files from Identity/ folder + custom memory directory
    identity_context = load_identity(IDENTITY_DIR)
    memory_dir = agent_config.get('memory_dir', '').strip()
    # Normalize Windows-style paths (B:\foo\bar) to WSL (/mnt/b/foo/bar)
    if memory_dir and ':' in memory_dir[:3]:
        drive, rest = memory_dir.split(':', 1)
        memory_dir = f"/mnt/{drive.lower().strip()}{rest.replace('\\', '/')}"
        log("IDENTITY", f"Normalized memory dir to: {memory_dir}")
    if memory_dir and os.path.isdir(memory_dir):
        extra_context = load_identity(memory_dir)
        if extra_context:
            identity_context = (identity_context + "\n\n" + extra_context).strip()
            log("IDENTITY", f"Merged custom memory directory: {memory_dir}")

    if not os.path.exists(MODE_FILE):
        with open(MODE_FILE, 'w') as f:
            f.write('listen')

    # Clear state (fresh session — no bleed from previous runs)
    for f in [TRANSCRIPT_FILE, LATENCY_FILE, DETECTED_SPEAKERS_FILE, SPEAKER_NAMES_FILE]:
        if os.path.exists(f):
            os.remove(f)

    # Initialize components
    reader = AudioStreamReader(AUDIO_FILE)
    vad = VAD()
    transcriber = StreamingTranscriber(args.whisper_model, WHISPER_DEVICE,
                                       "float16" if WHISPER_DEVICE == "cuda" else "int8")

    diarizer = None
    if not args.no_diarization:
        try:
            diarizer = Diarizer()
        except Exception as e:
            log("DIAR", f"Failed to init: {e}")

    thinker = None
    speaker = None
    if not args.no_tts:
        thinker = Thinker(llm_model, agent_name, persona, identity_context)
        speaker = Speaker(voice_model, engine=tts_engine, tts_reference=tts_reference)

    transcript_buffer = []
    last_minute_stamp = None
    last_think_time = 0
    THINK_INTERVAL = 4
    last_tts_sig = None  # (engine, voice, ref) — rebuild Speaker when dashboard changes it

    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"AGENT IN THE ARMCHAIR — {agent_name} (streaming)")
    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"Whisper: {args.whisper_model} ({WHISPER_DEVICE})")
    log("ARMCHAIR", f"VAD: Silero (threshold={VAD_THRESHOLD})")
    log("ARMCHAIR", f"Diarization: {'enabled' if diarizer else 'disabled'}")
    log("ARMCHAIR", f"LLM: {llm_model if thinker else 'disabled'}")
    log("ARMCHAIR", f"TTS: {tts_engine} ({voice_model if tts_engine == 'piper' else ('Muska ref' if tts_engine == 'chatterbox' else KOKORO_VOICE_DEFAULT)})" + (" — disabled" if not speaker else ""))
    if memory_dir:
        log("ARMCHAIR", f"Memory dir: {memory_dir}")
    log("ARMCHAIR", f"Agent: {agent_name}")
    log("ARMCHAIR", f"Dashboard: http://localhost:8765")
    log("ARMCHAIR", "")
    log("ARMCHAIR", "Waiting for audio stream...")
    log("ARMCHAIR", "  Run stream_to_file.bat on Windows")
    log("ARMCHAIR", "")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log("ARMCHAIR", "Shutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    silence_counter = 0
    SILENCE_TIMEOUT = 2  # seconds of silence before committing utterance

    # Prewarm watcher — dashboard writes engine name to PREWARM_FILE to
    # load a TTS model in the background before it's needed
    def prewarm_watcher():
        last_seen = None
        while running:
            try:
                with open(PREWARM_FILE, 'r') as f:
                    engine = f.read().strip()
                if engine and engine != last_seen and get_worker(engine):
                    last_seen = engine
                    log("TTS", f"Prewarming {engine} worker (background)...")
                    w = get_worker(engine)
                    if w.proc is None or w.proc.poll() is not None:
                        w._start()
            except FileNotFoundError:
                pass
            except Exception as e:
                log("TTS", f"Prewarm error: {e}")
            time.sleep(1.0)

    threading.Thread(target=prewarm_watcher, daemon=True).start()

    while running:
        # Read audio from the stream
        audio = reader.read()
        if audio is None:
            time.sleep(0.2)
            continue

        # Feed to diarizer rolling buffer (always, even silence)
        raw_bytes = (audio * 32768).astype(np.int16).tobytes()
        if diarizer:
            diarizer.add_audio(raw_bytes)

        # Feed to VAD
        speech = vad.process(audio)

        if speech is not None:
            log("VAD", f"Speech detected: {len(speech)} samples ({len(speech)/16000:.1f}s)")

        if speech is not None:
            # We have speech — add to transcriber buffer
            transcriber.add_speech(speech)
            silence_counter = 0

            # Try incremental transcription with timestamps
            transcribe_start = time.time()
            new_segs = transcriber.get_new_segments()
            transcribe_elapsed = time.time() - transcribe_start

            if new_segs:
                # Get speaker segments from diarizer
                speaker_segments = None
                if diarizer:
                    speaker_segments = diarizer.get_speaker_segments()

                # Write latency
                try:
                    with open(LATENCY_FILE, 'w') as f:
                        f.write(f'{transcribe_elapsed:.1f}s')
                except Exception:
                    pass

                # Process each new segment
                for seg in new_segs:
                    text = seg['text'].strip()
                    if not text or len(text) < 3 or text.lower().strip() in SKIP_PHRASES:
                        continue

                    # Match speaker using timestamp
                    speaker_label = "SPEAKER_00"
                    if diarizer and speaker_segments:
                        speaker_label = diarizer.get_speaker_for_time(seg['start'], speaker_segments)

                    speaker_names = get_speaker_names()
                    display_name = format_speaker(speaker_label, speaker_names)

                    # Append to transcript with minute separator
                    current_minute = time.strftime('%H:%M')
                    if current_minute != last_minute_stamp:
                        transcript_buffer.append(f"--- {current_minute} ---")
                        last_minute_stamp = current_minute

                    # If last line is from the same speaker, append to it
                    if transcript_buffer and transcript_buffer[-1].startswith(f"{display_name}: "):
                        transcript_buffer[-1] += " " + text
                    else:
                        transcript_buffer.append(f"{display_name}: {text}")

                    if len(transcript_buffer) > 1000:
                        transcript_buffer = transcript_buffer[-1000:]

                    with open(TRANSCRIPT_FILE, 'w') as f:
                        f.write('\n'.join(transcript_buffer))

                    log("HEARD", f"({transcribe_elapsed:.1f}s) [{display_name}] {text[:80]}")

                    # Talk mode — check if agent name is in the text
                    current_mode = get_mode()
                    if current_mode == 'talk' and thinker and agent_name.lower() in text.lower():
                        now = time.time()
                        if (now - last_think_time) >= THINK_INTERVAL:
                            recent = '\n'.join(transcript_buffer[-10:])
                            log("LLM", "Agent name detected — checking...")
                            response = thinker.think(recent)
                            last_think_time = time.time()

                            if response:
                                cleaned = clean_for_speech(response)
                                log("THINK", f"{cleaned[:80]}")
                                transcript_buffer.append(f"{agent_name}: {cleaned}")
                                with open(TRANSCRIPT_FILE, 'w') as f:
                                    f.write('\n'.join(transcript_buffer))

                                # Hot-swap TTS engine/voice if dashboard config changed mid-call
                                cfg_now = get_agent_config()
                                tts_sig = (cfg_now.get('tts_engine', TTS_ENGINE_DEFAULT),
                                           cfg_now.get('voice', TTS_VOICE_DEFAULT),
                                           cfg_now.get('tts_reference', CHATTERBOX_REF_DEFAULT))
                                if speaker and tts_sig != last_tts_sig:
                                    try:
                                        new_speaker = Speaker(tts_sig[1], engine=tts_sig[0], tts_reference=tts_sig[2])
                                        # Workers stay warm in pool — no kill, instant switch-back
                                        speaker = new_speaker
                                        last_tts_sig = tts_sig
                                        log("TTS", f"Voice/engine switched -> {tts_sig[0]} ({tts_sig[1] if tts_sig[0]=='piper' else 'cloned'})")
                                    except Exception as e:
                                        log("TTS", f"Engine switch failed: {e}")

                                if speaker and not speaker.speaking:
                                    speaker.speaking = True
                                    threading.Thread(
                                        target=speaker.speak_and_release,
                                        args=(cleaned, agent_name),
                                        daemon=True
                                    ).start()
                            else:
                                log("LLM", "[SILENCE]")
        else:
            # Silence — after timeout, clear buffer for next utterance
            silence_counter += 1
            if silence_counter >= SILENCE_TIMEOUT * 2 and len(transcriber.audio_buffer) > 0:
                transcriber.clear()
                silence_counter = 0

    # Save session: transcript + speaker names + detected speakers + audio
    if transcript_buffer:
        transcript_path = os.path.join(session_dir, "transcript.txt")
        with open(transcript_path, 'w') as f:
            f.write('\n'.join(transcript_buffer))
        log("SESSION", f"Transcript saved: {transcript_path}")

        names = get_speaker_names()
        if names:
            save_json(os.path.join(session_dir, "speaker_names.json"), names)
            log("SESSION", "Speaker names saved")

        try:
            with open(DETECTED_SPEAKERS_FILE, 'r') as f:
                detected = json.load(f)
            save_json(os.path.join(session_dir, "detected_speakers.json"), detected)
        except:
            pass

    # Copy audio file to session folder
    if os.path.exists(AUDIO_FILE):
        import shutil
        audio_dest = os.path.join(session_dir, "audio.raw")
        try:
            shutil.copy2(AUDIO_FILE, audio_dest)
            log("SESSION", f"Audio saved: {audio_dest}")
        except:
            pass

    log("SESSION", f"Session ended: {session_dir}")
    log("ARMCHAIR", "Pipeline stopped.")


if __name__ == "__main__":
    main()