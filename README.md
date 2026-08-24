# 🪑 Agent In The Armchair

**Real-time streaming Voice-to-Text + AI Agent for Microsoft Teams.** Invisible. Local. Free.

Agent In The Armchair sits in your Teams meetings, listens, transcribes with speaker labels, and can speak when directly addressed — in real time, on your hardware, with zero per-hour costs. No bot joins the meeting. Teams doesn't know it's there.

Part of [The Pack](https://github.com/Roughn3ck/ExecutiveMind) at [Executive Mind](https://executivemind.io).

---

## Architecture (v2 — Streaming)

```
Teams Meeting Audio (speaker output)
       ↓
CABLE-A Input (Teams playback device)
       ↓
CABLE-A Output → ffmpeg (16kHz mono PCM, continuous stream)
       ↓
B:\armchair_audio.raw
       ↓
WSL: armchair_live.py (streaming pipeline)
       ↓
Silero VAD — detects speech, skips silence (nearly free on GPU)
       ↓
faster-whisper streaming — incremental transcription via local agreement
       ↓
pyannote-audio (16s rolling buffer, every 10s) — speaker labels
       ↓
Dashboard (http://localhost:8765) with live labeled transcript
       ↓
[If Talk mode + agent name detected]
       ↓
LLM gate: "Am I being directly addressed?"
       ↓
Yes → Piper TTS → WAV → CABLE-A Input → meeting hears agent
No  → [SILENCE] — agent stays quiet
```

### v1 → v2 Architecture Change

**v1 (chunk-based):** Fixed 4s chunks → transcribe each chunk → diarize each chunk.

**Problems with v1:**
- Diarization can't work on 4s chunks (pyannote needs 16-30s context)
- SPEAKER_UNKNOWN flickered between diarization runs
- GPU heavy — running Whisper + pyannote on every 4s chunk, even silence
- No partial results — 4s minimum latency before any text appears
- Chunk boundaries cut words mid-sentence

**v2 (streaming):** VAD-driven → only process speech → incremental transcription → separate diarization on rolling buffer.

**Benefits of v2:**
- VAD skips silence — Whisper only runs on actual speech
- Incremental transcription — text appears as words become confident (local agreement)
- Diarization runs independently on 16s rolling buffer — accurate speaker separation
- No SPEAKER_UNKNOWN — defaults to last known speaker, only updates when a new speaker is confirmed
- Much lighter on GPU — VAD is nearly free, Whisper only on speech, pyannote every 10s

## What's Here

| File | Purpose |
|------|---------|
| `armchair_live.py` | Main streaming pipeline (VTT + diarization + LLM + TTS) |
| `dashboard_server.py` | HTTP server for live dashboard + API |
| `dashboard.html` | Web dashboard with speaker naming, agent config, mode toggle |
| `stream_to_file.bat` | Windows ffmpeg audio capture |
| `setup_audio.bat` | Audio routing setup guide |
| `requirements.txt` | Python dependencies |

## Features

### Streaming VTT
- Silero VAD detects speech, skips silence (nearly free on GPU)
- faster-whisper with local agreement policy — text appears incrementally
- No fixed chunk boundaries — processes as audio arrives

### Speaker Diarization
- pyannote-audio on 16s rolling buffer (runs every 10s)
- Speakers labeled as SPEAKER_00, SPEAKER_01, etc.
- Stable labels — no flickering between speakers
- Dashboard speaker naming: assign names mid-call, applies retroactively

### Talk / Listen Mode
- 🔇 Listen: Pure VTT with speaker labels
- 🎤 Talk: VTT + LLM + TTS — agent responds when directly addressed
- LLM decides: direct address vs mention (returns [SILENCE] for mentions)
- Agent name configurable in dashboard

### TTS (Piper)
- Piper TTS — fast, ~1s generation on CPU
- Voice configurable in dashboard

### Post-Call Memory
- Transcript saved with speaker labels + agent responses
- Speaker names mapping saved to JSON

## Setup

### Prerequisites

**WSL (Python 3.12+):**
```bash
pip install -r requirements.txt
```

**Windows:**
- VB-Audio Virtual Cable (CABLE-A) — [download](https://vb-audio.com/Cable/)
- ffmpeg at `C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe`

**GPU:** NVIDIA with CUDA support

**HuggingFace (for pyannote-audio):**
- Accept license at [pyannote/speaker-diarization-3.1](https://hf.co/pyannote/speaker-diarization-3.1)
- Accept license at [pyannote/speaker-diarization-community-1](https://hf.co/pyannote/speaker-diarization-community-1)
- Set `HF_TOKEN` in environment

**Ollama (for Talk mode):** Running on localhost:11434

### Audio Routing (One-Time)
1. Run `setup_audio.bat` on Windows
2. Set Windows default playback → CABLE-A Input
3. Enable "Listen to this device" on CABLE-A Output → your stereo speakers
4. Teams mic stays on your normal microphone

### Running the Pipeline

**Terminal 1 (Windows):** `stream_to_file.bat`

**Terminal 2 (WSL):**
```bash
/home/krisr/.local/share/whisper-venv/bin/python3 armchair_live.py
```

**Browser:** `http://localhost:8765`

## License

MIT — See [LICENSE](LICENSE)

---

*Agent In The Armchair.* 🪑