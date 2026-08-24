#!/usr/bin/env python3
r"""
Agent In The Armchair — Real-time VTT + AI Agent for MS Teams

Architecture:
  Windows ffmpeg -> B:\armchair_audio.raw (16kHz mono PCM)
  WSL reads /mnt/b/armchair_audio.raw
    -> Whisper (faster-whisper, CUDA) -> transcript
    -> pyannote-audio (CUDA) -> speaker diarization
    -> Dashboard (live transcript with speaker labels on http://localhost:8765)

  Talk mode (when enabled):
    -> LLM gate: "Is the agent being directly addressed?"
    -> If yes: LLM generates response -> Piper TTS -> WAV -> PowerShell -> CABLE-A Input -> meeting
    -> If no: [SILENCE] — agent stays quiet

  Post-call:
    -> Transcript saved with speaker labels
    -> Agent's own responses logged
    -> Speaker names assigned via dashboard

Usage:
  python3 armchair_live.py [--whisper-model MODEL] [--agent-name NAME] [--voice VOICE]
  python3 armchair_live.py --agent-name Agricola --voice en_US-norman-medium
"""

import subprocess
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

# ============================================================
# CONFIG
# ============================================================
AUDIO_FILE = "/mnt/b/armchair_audio.raw"
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
CHUNK_SECONDS = 4
CHUNK_BYTES = 128000
SILENCE_THRESHOLD = 3
OVERLAP_SECONDS = 1
OVERLAP_BYTES = int(OVERLAP_SECONDS * SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)

# Whisper config
WHISPER_MODEL_DEFAULT = "large-v3-turbo"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "float16"

# Diarization config
DIARIZATION_MIN_SPEAKERS = 2
DIARIZATION_MAX_SPEAKERS = 10

# LLM config (Ollama)
LLM_MODEL_DEFAULT = "deepseek-v3.2:cloud"
LLM_API_HOST = "localhost"
LLM_API_PORT = 11434
LLM_API_PATH = "/api/chat"
LLM_MAX_TOKENS = 150
LLM_TEMPERATURE = 0.7

# TTS config (Piper)
TTS_VOICE_DEFAULT = "en_US-norman-medium"
PIPER_BIN = "/home/krisr/.local/bin/piper"
PIPER_MODELS_DIR = "/home/krisr/.local/share/piper"
TTS_OUTPUT_DIR = "/tmp/armchair/tts"

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
AGENT_CONFIG_FILE = "/tmp/armchair/agent_config.json"
TTS_PLAYBACK_DIR = "/mnt/b/armchair_tmp"

# Whisper hallucination filter
SKIP_PHRASES = [
    "thanks for watching", "subscribe", "the end", "thank you",
    "thank you.", "you", "bye", "bye-bye", "bye bye", "goodbye",
    "see you next time", "i'll see you next time",
    "we'll see you next time", "we'll be right back"
]


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
# AUDIO CAPTURE
# ============================================================
class AudioCapture:
    def __init__(self, audio_file, chunk_bytes, overlap_bytes=0):
        self.audio_file = audio_file
        self.chunk_bytes = chunk_bytes
        self.overlap_bytes = overlap_bytes
        self.offset = 0
        self._caught_up = False

    def read_chunk(self):
        if not os.path.exists(self.audio_file):
            return None
        try:
            current_size = os.path.getsize(self.audio_file)
        except OSError:
            return None

        if not self._caught_up:
            if current_size >= self.chunk_bytes:
                self.offset = current_size - self.chunk_bytes
                self._caught_up = True
                log("CAPTURE", f"Skipping to end of existing data (offset={self.offset})")
            else:
                return None

        if current_size < self.offset:
            self.offset = 0
        if current_size < self.offset + self.chunk_bytes:
            return None
        try:
            with open(self.audio_file, 'rb') as f:
                f.seek(self.offset)
                data = f.read(self.chunk_bytes)
            self.offset += self.chunk_bytes - self.overlap_bytes
            return data
        except OSError:
            return None


# ============================================================
# WHISPER TRANSCRIPTION (faster-whisper, CUDA)
# ============================================================
class Transcriber:
    def __init__(self, model_name, device="cuda", compute_type="float16"):
        os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
        os.environ['XDG_CACHE_HOME'] = '/home/krisr/.local/share/whisper'
        cuda = '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages/nvidia/cublas/lib'
        cudnn = '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages/nvidia/cudnn/lib'
        nvrtc = '/home/krisr/.local/share/whisper-venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib'
        ld = os.environ.get('LD_LIBRARY_PATH', '')
        os.environ['LD_LIBRARY_PATH'] = f"{cuda}:{cudnn}:{nvrtc}:{ld}"

        import ctypes
        # Only preload cuBLAS (needed by faster-whisper/ctranslate2).
        # Do NOT preload cuDNN — PyTorch 2.13 bundles its own cuDNN (cu13)
        # and preloading the cu12 version causes CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH
        # when pyannote-audio runs on CUDA.
        for lib in ['libcublas.so.12', 'libcublasLt.so.12', 'libcudart.so.12']:
            for d in [cuda, cudnn, nvrtc]:
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

    def transcribe_pcm(self, pcm_data, sample_rate=16000):
        tmp_wav = f"/tmp/armchair/chunk_{int(time.time()*1000)}.wav"
        try:
            with wave.open(tmp_wav, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_data)
            segments, info = self.model.transcribe(
                tmp_wav, beam_size=5, language='en',
                vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500)
            )
            text = ' '.join(seg.text.strip() for seg in segments)
            return text.strip()
        except Exception as e:
            log("STT", f"Error: {e}")
            return ""
        finally:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)


# ============================================================
# SPEAKER DIARIZATION (pyannote-audio, CUDA)
# ============================================================
class Diarizer:
    SIMILARITY_THRESHOLD = 0.75  # cosine similarity to match a known speaker

    def __init__(self, min_speakers=2, max_speakers=10):
        log("DIAR", "Loading pyannote-audio pipeline...")
        from pyannote.audio import Pipeline
        import torch
        import numpy as np

        # Disable cuDNN to avoid version conflict between faster-whisper (cu12 cuDNN)
        # and PyTorch 2.13 (cu13 cuDNN). CUDA still works — just no cuDNN acceleration.
        torch.backends.cudnn.enabled = False
        log("DIAR", "cuDNN disabled (avoids cu12/cu13 version conflict)")

        # Read HF token from .env file if not in environment
        token = os.environ.get('HF_TOKEN', '')
        if not token:
            try:
                with open('/mnt/b/OpenClaw/.openclaw/.env', 'r') as f:
                    for line in f:
                        if line.startswith('HF_TOKEN='):
                            token = line.strip().split('=', 1)[1]
                            break
            except:
                pass

        self.pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=token if token else None
        )

        if torch.cuda.is_available():
            self.pipeline.to(torch.device("cuda"))
            log("DIAR", f"Pipeline loaded on CUDA ({torch.cuda.get_device_name(0)})")
        else:
            log("DIAR", "CUDA not available, running on CPU")

        # Speaker embedding database: {label: [embedding_array, ...]}
        self.known_speakers = {}  # {"SPEAKER_00": np.array([...]), "SPEAKER_01": ...}
        self.speaker_count = 0
        self.np = np
        log("DIAR", "Ready (embedding-based speaker tracking)")

    def _cosine_similarity(self, a, b):
        """Cosine similarity between two numpy arrays."""
        return float(self.np.dot(a, b) / (self.np.linalg.norm(a) * self.np.linalg.norm(b) + 1e-8))

    def _match_speaker(self, embedding):
        """Match embedding to known speaker. Returns (label, similarity) or (None, 0)."""
        best_match = None
        best_sim = 0.0
        for label, ref_embedding in self.known_speakers.items():
            sim = self._cosine_similarity(embedding, ref_embedding)
            if sim > best_sim:
                best_sim = sim
                best_match = label
        return best_match, best_sim

    def _register_speaker(self, embedding):
        """Register a new speaker with the given embedding."""
        label = f"SPEAKER_{self.speaker_count:02d}"
        self.known_speakers[label] = embedding
        self.speaker_count += 1
        log("DIAR", f"New speaker registered: {label} (total: {self.speaker_count})")
        return label

    def diarize_pcm(self, pcm_data, sample_rate=16000):
        """Run diarization on a PCM chunk. Returns primary speaker label for the chunk."""
        import torch
        import soundfile as sf
        import tempfile

        tmp_wav = tempfile.NamedTemporaryFile(suffix='.wav', dir='/tmp/armchair', delete=False)
        tmp_wav.close()
        try:
            with wave.open(tmp_wav.name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm_data)

            # Load audio with soundfile (avoids torchaudio/torchcodec dependency)
            audio_data, sr = sf.read(tmp_wav.name, dtype='float32')

            # Convert to torch tensor: shape (channel, time) = (1, samples)
            waveform = torch.from_numpy(audio_data).unsqueeze(0)

            # Run diarization
            result = self.pipeline(
                {"waveform": waveform, "sample_rate": sample_rate}
            )

            # Get speaker embedding from result
            embeddings = result.speaker_embeddings
            if embeddings is not None and len(embeddings) > 0:
                # Use the first (and usually only) embedding
                chunk_embedding = self.np.array(embeddings[0])

                # Match against known speakers
                match_label, sim = self._match_speaker(chunk_embedding)

                if match_label and sim >= self.SIMILARITY_THRESHOLD:
                    # Update the reference embedding (running average for stability)
                    old = self.known_speakers[match_label]
                    self.known_speakers[match_label] = 0.7 * old + 0.3 * chunk_embedding
                    return match_label
                else:
                    # No match — register new speaker
                    label = self._register_speaker(chunk_embedding)
                    return label

            # Fallback: use diarization labels directly
            diarization = result.speaker_diarization
            labels = list(diarization.labels())
            if labels:
                return labels[0]

            return "SPEAKER_UNKNOWN"

        except Exception as e:
            log("DIAR", f"Error: {e}")
            return "SPEAKER_UNKNOWN"
        finally:
            if os.path.exists(tmp_wav.name):
                os.remove(tmp_wav.name)


# ============================================================
# LLM THINKER (Ollama API)
# ============================================================
class Thinker:
    def __init__(self, model_id, agent_name, persona):
        self.model_id = model_id
        self.agent_name = agent_name
        self.persona = persona.replace('{agent_name}', agent_name)
        self.conversation = []

    def think(self, transcript, agent_name_in_text):
        """Send recent transcript to LLM. Returns response or None for [SILENCE]."""
        if not transcript or len(transcript) < 5:
            return None

        self.conversation.append({
            "role": "user",
            "content": f"Recent transcript:\n{transcript}\n\nYour name is {self.agent_name}. Are you being directly addressed? If so, respond. If not, respond with [SILENCE]."
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
                    # Check for silence signal
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
            log("TTS", f"WARNING: Voice model not found: {self.voice_path}")
            log("TTS", "TTS will be disabled")
            self.voice_path = None
        else:
            log("TTS", f"Voice: {voice_model} ({self.voice_path})")

    def speak_and_release(self, text, agent_name):
        """Generate TTS and play it. Blocks until audio finishes."""
        try:
            self.speak(text, agent_name)
        finally:
            self.speaking = False
            log("TTS", "Speaking lock released")

    def speak(self, text, agent_name):
        if not text or len(text) < 3 or not self.voice_path:
            return

        timestamp = int(time.time() * 1000)
        wav_path = f"{TTS_OUTPUT_DIR}/agent_{timestamp}.wav"
        win_path = f"B:\\armchair_tmp\\agent_{timestamp}.wav"

        try:
            # Generate TTS with Piper (subprocess — fast, ~1s)
            result = subprocess.run(
                [PIPER_BIN, "-m", self.voice_path, "-c", self.config_path,
                 "-f", wav_path, "--cuda"],
                input=text, capture_output=True, text=True, timeout=15
            )

            if not os.path.exists(wav_path):
                log("TTS", "Failed to generate audio")
                return

            # Copy to Windows-accessible path
            shutil.copy2(wav_path, win_path)

            # Play audio to Windows default device (CABLE-A Input)
            powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
            play_cmd = [
                powershell, '-c',
                f"(New-Object System.Media.SoundPlayer '{win_path}').PlaySync()"
            ]
            log("TTS", f"{agent_name}: {text[:80]}...")
            subprocess.run(play_cmd, capture_output=True, text=True, timeout=30)

        except subprocess.TimeoutExpired:
            log("TTS", "Timeout generating/playing audio")
        except Exception as e:
            log("TTS", f"Error: {e}")
        finally:
            if os.path.exists(wav_path):
                os.remove(wav_path)
            if os.path.exists(win_path):
                os.remove(win_path)


# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Agent In The Armchair — VTT + AI Agent")
    parser.add_argument("--whisper-model", default=WHISPER_MODEL_DEFAULT)
    parser.add_argument("--whisper-device", default=WHISPER_DEVICE)
    parser.add_argument("--agent-name", default=None, help="Agent name (default: from config or Agricola)")
    parser.add_argument("--voice", default=None, help="Piper voice model (default: from config)")
    parser.add_argument("--llm", default=None, help="Ollama LLM model (default: from config)")
    parser.add_argument("--no-diarization", action="store_true", help="Disable speaker diarization")
    parser.add_argument("--no-tts", action="store_true", help="Disable TTS (VTT only)")
    args = parser.parse_args()

    os.makedirs("/tmp/armchair", exist_ok=True)
    os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)
    os.makedirs(TTS_PLAYBACK_DIR, exist_ok=True)

    # Load or initialize agent config
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

    # Write default mode
    if not os.path.exists(MODE_FILE):
        with open(MODE_FILE, 'w') as f:
            f.write('listen')

    # Clear state files
    for f in [TRANSCRIPT_FILE, LATENCY_FILE]:
        if os.path.exists(f):
            os.remove(f)

    # Initialize components
    capture = AudioCapture(AUDIO_FILE, CHUNK_BYTES, overlap_bytes=OVERLAP_BYTES)
    transcriber = Transcriber(args.whisper_model, args.whisper_device,
                             "float16" if args.whisper_device == "cuda" else "int8")

    diarizer = None
    if not args.no_diarization:
        try:
            diarizer = Diarizer(DIARIZATION_MIN_SPEAKERS, DIARIZATION_MAX_SPEAKERS)
        except Exception as e:
            log("DIAR", f"Failed to init diarization: {e}")
            log("DIAR", "Continuing without speaker labels")

    thinker = None
    speaker = None
    if not args.no_tts:
        thinker = Thinker(llm_model, agent_name, persona)
        speaker = Speaker(voice_model)

    transcript_buffer = []
    last_minute_stamp = None
    last_think_time = 0
    THINK_INTERVAL = 4  # seconds between LLM calls
    SPEECH_DEBOUNCE = 3  # seconds of silence before thinking

    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"AGENT IN THE ARMCHAIR — {agent_name}")
    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"Whisper: {args.whisper_model} ({args.whisper_device})")
    log("ARMCHAIR", f"Diarization: {'enabled (pyannote-audio CUDA)' if diarizer else 'disabled'}")
    log("ARMCHAIR", f"LLM: {llm_model if thinker else 'disabled'}")
    log("ARMCHAIR", f"TTS: {voice_model if speaker else 'disabled'}")
    log("ARMCHAIR", f"Agent: {agent_name}")
    log("ARMCHAIR", f"Audio: {AUDIO_FILE}")
    log("ARMCHAIR", f"Chunk: {CHUNK_SECONDS}s, Overlap: {OVERLAP_SECONDS}s")
    log("ARMCHAIR", f"Dashboard: http://localhost:8765")
    log("ARMCHAIR", "")
    log("ARMCHAIR", "Waiting for audio data...")
    log("ARMCHAIR", "  Run stream_to_file.bat on Windows")
    log("ARMCHAIR", "")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        log("ARMCHAIR", "Shutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)

    while running:
        chunk_data = capture.read_chunk()
        if chunk_data is None:
            time.sleep(0.5)
            continue

        # Check silence
        num_samples = len(chunk_data) // 2
        if num_samples > 0:
            samples = struct.unpack('<' + 'h' * min(num_samples, 8000), chunk_data[:16000])
            max_val = max(abs(s) for s in samples)
            vol_pct = max_val / 32767 * 100
            if vol_pct < SILENCE_THRESHOLD:
                continue

        # LISTEN — transcribe
        transcribe_start = time.time()
        text = transcriber.transcribe_pcm(chunk_data)
        transcribe_elapsed = time.time() - transcribe_start

        if not text or len(text) < 3:
            continue

        if text.lower().strip() in SKIP_PHRASES:
            continue

        # DIARIZE — identify speaker using embedding similarity
        speaker_label = "SPEAKER_UNKNOWN"
        if diarizer:
            diarize_start = time.time()
            speaker_label = diarizer.diarize_pcm(chunk_data)
            diarize_elapsed = time.time() - diarize_start
            log("DIAR", f"({diarize_elapsed:.1f}s) {speaker_label}")

        # Load current speaker names (from dashboard)
        speaker_names = get_speaker_names()
        display_name = format_speaker(speaker_label, speaker_names)

        total_elapsed = transcribe_elapsed + (diarize_elapsed if diarizer else 0)
        log("HEARD", f"({total_elapsed:.1f}s) [{display_name}] {text}")

        # Write latency
        try:
            with open(LATENCY_FILE, 'w') as f:
                f.write(f'{total_elapsed:.1f}s')
        except:
            pass

        # Append to transcript buffer — minute separator + labeled line
        current_minute = time.strftime('%H:%M')
        if current_minute != last_minute_stamp:
            transcript_buffer.append(f"--- {current_minute} ---")
            last_minute_stamp = current_minute
        transcript_buffer.append(f"{display_name}: {text}")

        if len(transcript_buffer) > 1000:
            transcript_buffer = transcript_buffer[-1000:]

        with open(TRANSCRIPT_FILE, 'w') as f:
            f.write('\n'.join(transcript_buffer))

        # THINK — only in talk mode and if agent name appears in transcript
        current_mode = get_mode()
        if current_mode != 'talk' or not thinker:
            continue

        # Check if agent name is mentioned in the text
        agent_name_lower = agent_name.lower()
        if agent_name_lower not in text.lower():
            continue

        # Rate limit
        now = time.time()
        if (now - last_think_time) < THINK_INTERVAL:
            continue

        # Build recent transcript context
        recent_lines = transcript_buffer[-10:]
        recent_context = '\n'.join(recent_lines)

        log("LLM", f"Agent name detected — checking if directly addressed...")
        think_start = time.time()
        response = thinker.think(recent_context, agent_name)
        think_elapsed = time.time() - think_start
        last_think_time = time.time()

        if response:
            cleaned = clean_for_speech(response)
            log("THINK", f"({think_elapsed:.1f}s) {cleaned}")

            # Append agent response to transcript
            transcript_buffer.append(f"{agent_name}: {cleaned}")
            with open(TRANSCRIPT_FILE, 'w') as f:
                f.write('\n'.join(transcript_buffer))

            # SPEAK — Piper TTS to meeting
            if speaker and not speaker.speaking:
                speaker.speaking = True
                threading.Thread(
                    target=speaker.speak_and_release,
                    args=(cleaned, agent_name),
                    daemon=True
                ).start()
        else:
            log("LLM", f"({think_elapsed:.1f}s) [SILENCE] — not directly addressed")

    # Save final transcript with speaker labels
    if transcript_buffer:
        final_path = f"/tmp/armchair/transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        with open(final_path, 'w') as f:
            f.write('\n'.join(transcript_buffer))
        log("ARMCHAIR", f"Final transcript saved: {final_path}")

        # Also save speaker names mapping
        names = get_speaker_names()
        if names:
            names_path = f"/tmp/armchair/speakers_{time.strftime('%Y%m%d_%H%M%S')}.json"
            save_json(names_path, names)
            log("ARMCHAIR", f"Speaker names saved: {names_path}")

    log("ARMCHAIR", "Pipeline stopped.")


if __name__ == "__main__":
    main()