#!/usr/bin/env python3
r"""
Agent In The Armchair — Real-time VTT (Voice-to-Text) for MS Teams

Architecture:
  Windows ffmpeg -> B:\armchair_audio.raw (16kHz mono PCM)
  WSL reads /mnt/b/armchair_audio.raw -> Whisper (faster-whisper, CUDA) -> transcript
  -> Dashboard (live transcript view on http://localhost:8765)

No TTS. No LLM. Pure listen + transcribe. Invisible to Teams.

Usage:
  python3 armchair_live.py [--whisper-model MODEL]
  python3 armchair_live.py --whisper-model large-v3-turbo
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

# ============================================================
# CONFIG
# ============================================================
AUDIO_FILE = "/mnt/b/armchair_audio.raw"
SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
CHUNK_SECONDS = 4          # 4s chunks = good balance of speed and accuracy
CHUNK_BYTES = 128000       # 4s * 16kHz * 1ch * 2bytes
SILENCE_THRESHOLD = 3     # 3% max amplitude = speech detection threshold
OVERLAP_SECONDS = 1
OVERLAP_BYTES = int(OVERLAP_SECONDS * SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)

# Whisper config
WHISPER_MODEL_DEFAULT = "large-v3-turbo"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "float16"

# Pipeline state
TRANSCRIPT_FILE = "/tmp/armchair/transcript.txt"
LATENCY_FILE = "/tmp/armchair/latency.txt"


def log(tag, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{tag}] {msg}", flush=True)


# ============================================================
# AUDIO CAPTURE
# ============================================================
class AudioCapture:
    def __init__(self, audio_file, chunk_bytes, overlap_bytes=0):
        self.audio_file = audio_file
        self.chunk_bytes = chunk_bytes
        self.overlap_bytes = overlap_bytes
        self.offset = 0
        self._caught_up = False  # Skip old data on first read

    def read_chunk(self):
        if not os.path.exists(self.audio_file):
            return None
        try:
            current_size = os.path.getsize(self.audio_file)
        except OSError:
            return None

        # On first reads, skip to the end of existing data to avoid processing old audio
        if not self._caught_up:
            if current_size >= self.chunk_bytes:
                self.offset = current_size - self.chunk_bytes
                self._caught_up = True
                log("CAPTURE", f"Skipping to end of existing data (offset={self.offset})")
            else:
                return None  # File too small, wait for more data

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

        # Preload CUDA libraries before importing faster_whisper.
        # Setting LD_LIBRARY_PATH after process start isn't enough — the
        # dynamic linker caches its search path at startup. ctypes.WAIT
        # forces the linker to pick up the new path.
        import ctypes
        for lib in ['libcublas.so.12', 'libcublasLt.so.12', 'libcudnn.so.8', 'libcudart.so.12']:
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
# MAIN PIPELINE
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Agent In The Armchair — VTT")
    parser.add_argument("--whisper-model", default=WHISPER_MODEL_DEFAULT)
    parser.add_argument("--whisper-device", default=WHISPER_DEVICE)
    args = parser.parse_args()

    os.makedirs("/tmp/armchair", exist_ok=True)

    # Clear state files
    for f in [TRANSCRIPT_FILE, LATENCY_FILE]:
        if os.path.exists(f):
            os.remove(f)

    capture = AudioCapture(AUDIO_FILE, CHUNK_BYTES, overlap_bytes=OVERLAP_BYTES)
    transcriber = Transcriber(args.whisper_model, args.whisper_device,
                              "float16" if args.whisper_device == "cuda" else "int8")

    transcript_buffer = []
    last_minute_stamp = None

    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", "AGENT IN THE ARMCHAIR — VTT")
    log("ARMCHAIR", "=" * 60)
    log("ARMCHAIR", f"Whisper: {args.whisper_model} ({args.whisper_device})")
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

        # LISTEN
        transcribe_start = time.time()
        text = transcriber.transcribe_pcm(chunk_data)
        transcribe_elapsed = time.time() - transcribe_start

        if not text or len(text) < 3:
            continue

        # Filter common Whisper hallucinations
        skip_phrases = [
            "thanks for watching", "subscribe", "the end", "thank you",
            "thank you.", "you", "bye", "bye-bye", "bye bye", "goodbye",
            "see you next time", "i'll see you next time",
            "we'll see you next time", "we'll be right back"
        ]
        if text.lower().strip() in skip_phrases:
            continue

        log("HEARD", f"({transcribe_elapsed:.1f}s) {text}")

        # Write latency
        try:
            with open(LATENCY_FILE, 'w') as f:
                f.write(f'{transcribe_elapsed:.1f}s')
        except:
            pass

        # Append to transcript buffer — timestamp once per minute
        current_minute = time.strftime('%H:%M')
        if current_minute != last_minute_stamp:
            transcript_buffer.append(f"--- {current_minute} ---")
            last_minute_stamp = current_minute
        transcript_buffer.append(text)

        # Keep last 500 lines in memory
        if len(transcript_buffer) > 500:
            transcript_buffer = transcript_buffer[-500:]

        # Write transcript file for dashboard
        with open(TRANSCRIPT_FILE, 'w') as f:
            f.write('\n'.join(transcript_buffer))

    # Save final transcript
    if transcript_buffer:
        final_path = f"/tmp/armchair/transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        with open(final_path, 'w') as f:
            f.write('\n'.join(transcript_buffer))
        log("ARMCHAIR", f"Final transcript saved: {final_path}")

    log("ARMCHAIR", "Pipeline stopped.")


if __name__ == "__main__":
    main()