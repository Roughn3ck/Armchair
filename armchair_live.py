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

# TTS config (Piper)
TTS_VOICE_DEFAULT = "en_GB-alan-medium"
PIPER_BIN = "/home/krisr/.local/bin/piper"
PIPER_MODELS_DIR = "/home/krisr/.local/share/piper"
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
SPEAKER_NAMES_FILE = "/tmp/armchair/speaker_names.json"
DETECTED_SPEAKERS_FILE = "/tmp/armchair/detected_speakers.json"
AGENT_CONFIG_FILE = "/tmp/armchair/agent_config.json"
TTS_PLAYBACK_DIR = "/mnt/b/armchair_tmp"

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
    })


def format_speaker(speaker_id, names=None):
    if names and speaker_id in names and names[speaker_id]:
        return names[speaker_id]
    return speaker_id


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
    def __init__(self, model_id, agent_name, persona):
        self.model_id = model_id
        self.agent_name = agent_name
        self.persona = persona.replace('{agent_name}', agent_name)
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
# TTS SPEAKER (Piper)
# ============================================================
class Speaker:
    def __init__(self, voice_model):
        self.voice_model = voice_model
        self.voice_path = os.path.join(PIPER_MODELS_DIR, f"{voice_model}.onnx")
        self.config_path = os.path.join(PIPER_MODELS_DIR, f"{voice_model}.onnx.json")
        self.speaking = False
        os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
        os.makedirs(TTS_PLAYBACK_DIR, exist_ok=True)

        if not os.path.exists(self.voice_path):
            log("TTS", f"WARNING: Voice not found: {self.voice_path}")
            self.voice_path = None
        else:
            log("TTS", f"Voice: {voice_model}")

    def speak_and_release(self, text, agent_name):
        try:
            self.speak(text, agent_name)
        finally:
            self.speaking = False

    def speak(self, text, agent_name):
        if not text or len(text) < 3 or not self.voice_path:
            return

        timestamp = int(time.time() * 1000)
        wav_path = f"{TTS_OUTPUT_DIR}/agent_{timestamp}.wav"
        win_path = f"B:\\armchair_tmp\\agent_{timestamp}.wav"

        try:
            result = subprocess.run(
                [PIPER_BIN, "-m", self.voice_path, "-c", self.config_path,
                 "-f", wav_path],
                input=text, capture_output=True, text=True, timeout=15
            )

            if not os.path.exists(wav_path):
                log("TTS", "Failed to generate audio")
                return

            shutil.copy2(wav_path, win_path)

            powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
            play_cmd = [
                powershell, '-c',
                f"(New-Object System.Media.SoundPlayer '{win_path}').PlaySync()"
            ]
            log("TTS", f"{agent_name}: {text[:80]}...")
            subprocess.run(play_cmd, capture_output=True, text=True, timeout=30)

        except subprocess.TimeoutExpired:
            log("TTS", "Timeout")
        except Exception as e:
            log("TTS", f"Error: {e}")
        finally:
            for p in [wav_path, win_path]:
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

    if not os.path.exists(MODE_FILE):
        with open(MODE_FILE, 'w') as f:
            f.write('listen')

    # Clear state
    for f in [TRANSCRIPT_FILE, LATENCY_FILE, DETECTED_SPEAKERS_FILE]:
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
        thinker = Thinker(llm_model, agent_name, persona)
        speaker = Speaker(voice_model)

    transcript_buffer = []
    last_minute_stamp = None
    last_think_time = 0
    THINK_INTERVAL = 4

    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"AGENT IN THE ARMCHAIR — {agent_name} (streaming)")
    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"Whisper: {args.whisper_model} ({WHISPER_DEVICE})")
    log("ARMCHAIR", f"VAD: Silero (threshold={VAD_THRESHOLD})")
    log("ARMCHAIR", f"Diarization: {'enabled' if diarizer else 'disabled'}")
    log("ARMCHAIR", f"LLM: {llm_model if thinker else 'disabled'}")
    log("ARMCHAIR", f"TTS: {voice_model if speaker else 'disabled'}")
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

    # Save final transcript
    if transcript_buffer:
        final_path = f"/mnt/b/armchair_tmp/transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        with open(final_path, 'w') as f:
            f.write('\n'.join(transcript_buffer))
        log("ARMCHAIR", f"Final transcript saved: {final_path}")

        names = get_speaker_names()
        if names:
            names_path = f"/mnt/b/armchair_tmp/speakers_{time.strftime('%Y%m%d_%H%M%S')}.json"
            save_json(names_path, names)

    log("ARMCHAIR", "Pipeline stopped.")


if __name__ == "__main__":
    main()