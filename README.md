# 🪑 Agent In The Armchair

**Real-time streaming Voice-to-Text + AI Agent for Microsoft Teams.** Invisible. Local. Free.

Agent In The Armchair sits in your Teams meetings, listens, transcribes with speaker labels, and speaks when directly addressed — in real time, on your hardware, with zero per-hour costs. No bot joins the meeting. Teams doesn't know it's there.

Part of [The Pack](https://github.com/Roughn3ck/ExecutiveMind) at [Executive Mind](https://executivemind.io).

---

## Architecture (v2 — Streaming)

```
Teams Meeting Audio (speaker output) + Local Mic
       ↓
ffmpeg amix (mixes meeting audio + mic into one 16kHz mono stream)
       ↓
B:\armchair_audio.raw (continuous PCM stream)
       ↓
WSL: armchair_live.py (streaming pipeline)
       ↓
Silero VAD — detects speech, skips silence (nearly free on GPU)
       ↓
faster-whisper streaming — incremental transcription with word timestamps
       ↓
pyannote-audio (16s rolling buffer, every 10s) — per-segment speaker labels
       ↓
Dashboard (http://localhost:8765) with live labeled transcript
       ↓
[If Talk mode + agent name detected in speech]
       ↓
LLM gate (Ollama): "Am I being directly addressed?"
       ↓
Yes → TTS engine (Piper / Kokoro / Chatterbox voice cloning) → WAV → PowerShell → CABLE-A → meeting hears agent
No  → [SILENCE] — agent stays quiet
```

### Key Design Decisions

- **No bot joins the meeting.** Hardware audio capture via VB-Cable. Teams can't block it.
- **No third-party APIs.** Runs entirely on local hardware. Zero per-hour cost.
- **VAD-driven, not time-driven.** Silero VAD detects speech, only sends speech to Whisper. Silence is skipped.
- **Per-segment speaker matching.** Whisper word timestamps matched to pyannote speaker segments. Handles mid-utterance speaker switches.
- **LLM gate for direct address.** The LLM decides if it's being addressed vs mentioned. No keyword matching.
- **Three TTS engines, swappable mid-call.** Piper (fast, ~1s, built-in voices), Kokoro (premium quality, ~1.6s), Chatterbox (zero-shot voice cloning from a reference WAV — the agent can speak in *any* voice you give it). Engines run as persistent workers in isolated venvs; a dashboard ⚡Activate button pre-warms an engine so switching is instant. Worker pool keeps used engines loaded — switch back with zero latency.
- **Session management.** Each session archived to its own folder with transcript, audio, and speaker data.

## What's Here

| File | Purpose |
|------|---------|
| `armchair_live.py` | Main streaming pipeline (VTT + diarization + LLM + TTS) |
| `dashboard_server.py` | HTTP server for live dashboard + API |
| `dashboard.html` | Web dashboard with speaker naming, agent config, TTS engine select, mode toggle |
| `tts_workers/` | Persistent TTS engine workers (kokoro, chatterbox) — isolated venvs, JSON-over-stdin |
| `stream_to_file.bat` | Windows ffmpeg audio capture (meeting audio + mic) |
| `start_armchair.bat` | One-click launcher (audio + dashboard + pipeline + browser) |
| `setup_audio.bat` | Audio routing setup guide |
| `voices/` | Sample voice files (British + American) with README |
| `requirements.txt` | Python dependencies |
| `STATUS.md` | Full architecture history and component docs |

## Features

### Streaming VTT
- Silero VAD detects speech, skips silence
- faster-whisper with incremental transcription (word timestamps)
- ~0.3s transcription latency

### Speaker Diarization
- pyannote-audio on 16s rolling buffer (runs every 10s)
- Per-segment speaker labels matched to Whisper word timestamps
- Handles mid-utterance speaker switches
- Dashboard speaker naming: auto-populates detected speakers, type names, applies retroactively
- Label button for explicit save

### Talk / Listen Mode
- 🔇 Listen: Pure VTT with speaker labels
- 🎤 Talk: VTT + LLM + TTS — agent responds when directly addressed
- LLM decides: direct address vs mention (returns [SILENCE] for mentions)
- Agent name configurable in dashboard

### TTS — Three Engines
- **Piper** — built-in voices (Alan default), ~1s generation, instant voice swaps
- **Kokoro** — premium quality voices (~1.6s warm), own venv (`~/.local/share/kokoro-venv`)
- **Chatterbox** — zero-shot voice cloning from a reference WAV (e.g. Muska's voice), own venv (`~/.local/share/chatterbox-venv`), ~2.4s warm
- Engine selectable from dashboard; ⚡Activate button pre-warms an engine in the background
- Worker pool keeps engines loaded — switching back to a used engine is instant
- Hot-swap mid-call: engine, Piper voice, and reference WAV all switch on the next utterance

### Agent Memory
- Custom memory directory field on dashboard — any folder of .md/.txt files loaded into the system prompt at startup
- Windows-style paths (`B:\...`) auto-normalized to WSL (`/mnt/b/...`)
- Point it at an agent's workspace and it calls with that agent's brain, not just its voice

### Session Management
- Each session creates `B:\armchair_tmp\session_logs\YYYY-MM-DD_HHMMSS\`
- On shutdown: saves transcript.txt, speaker_names.json, detected_speakers.json, audio.raw
- Clean start each time — no bleed between sessions

### One-Click Launcher
- `start_armchair.bat` — double-click to start everything
- Opens audio capture, dashboard, browser, and pipeline
- Ctrl+C stops and saves session

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
4. Teams mic → your normal microphone

### Running the Pipeline

**One-click:** Double-click `start_armchair.bat`

**Or manually:**
1. Windows: `stream_to_file.bat`
2. WSL: `python3 armchair_live.py`
3. Browser: `http://localhost:8765`

## Latency

| Step | Time |
|------|------|
| VAD (Silero) | ~0ms (nearly free) |
| Whisper (CUDA) | ~0.3s |
| pyannote (CUDA) | ~1.5s (every 10s) |
| LLM gate (Ollama) | ~1-2s |
| Piper TTS | ~1s |
| Audio playback | ~0.5s |
| **Total (Listen mode)** | **~0.3s** |
| **Total (Talk mode)** | **~3-4s** |

## Voices

See `voices/README.md` for the full list of sample voices.

| Voice | Accent | Recommended |
|-------|--------|:-----------:|
| **Alan** | British RP | ⭐ |
| Aru | British | |
| Northern English Male | Northern UK | |
| Norman | US, deep | |

Download more from [Piper Voices](https://github.com/rhasspy/piper/blob/master/VOICES.md).

## License

MIT — See [LICENSE](LICENSE)

---

*Agent In The Armchair.* 🪑