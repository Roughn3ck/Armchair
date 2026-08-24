# 🪑 Agent In The Armchair

**Real-time Voice-to-Text + AI Agent for Microsoft Teams.** Invisible. Local. Free.

Agent In The Armchair sits in your Teams meetings, listens, transcribes with speaker labels, and can speak when directly addressed — in real time, on your hardware, with zero per-hour costs. No bot joins the meeting. Teams doesn't know it's there.

Part of [The Pack](https://github.com/Roughn3ck/ExecutiveMind) at [Executive Mind](https://executivemind.io).

---

## What This Is

A real-time pipeline that captures Teams meeting audio through a virtual cable, transcribes it with faster-whisper (CUDA), identifies speakers with pyannote-audio, and optionally responds via LLM + Piper TTS when directly addressed.

```
Teams Meeting Audio (speaker output)
       ↓
CABLE-A Input (Teams playback device)
       ↓
CABLE-A Output → ffmpeg (16kHz mono PCM)
       ↓
B:\armchair_audio.raw
       ↓
WSL: armchair_live.py
       ↓
faster-whisper (CUDA) → transcript
       ↓
pyannote-audio (CUDA) → speaker labels (SPEAKER_00, SPEAKER_01, ...)
       ↓
Dashboard (http://localhost:8765) with live labeled transcript
       ↓
[If Talk mode + agent name detected in speech]
       ↓
LLM gate: "Am I being directly addressed?"
       ↓
Yes → Piper TTS → WAV → CABLE-A Input → meeting hears agent
No  → [SILENCE] — agent stays quiet
```

## What's Here

| File | Purpose |
|------|---------|
| `armchair_live.py` | Main pipeline (VTT + diarization + LLM + TTS) |
| `dashboard_server.py` | HTTP server for live dashboard + API |
| `dashboard.html` | Web dashboard with speaker naming, agent config, mode toggle |
| `stream_to_file.bat` | Windows ffmpeg audio capture |
| `setup_audio.bat` | Audio routing setup guide |
| `requirements.txt` | Python dependencies |

## Features

### Voice-to-Text
- Real-time transcription with faster-whisper (CUDA, ~0.2s per 4s chunk)
- Minute-separator timestamps in transcript

### Speaker Diarization
- pyannote-audio 4.0 on CUDA identifies who speaks when
- Speakers labeled as SPEAKER_00, SPEAKER_01, etc.
- **Dashboard speaker naming:** assign names to speakers mid-call
  - Names apply retroactively to the whole transcript AND going forward
  - Just type the name next to the speaker ID in the dashboard

### Talk / Listen Mode
- **🔇 Listen:** Pure VTT with speaker labels (no LLM, no TTS)
- **🎤 Talk:** VTT + LLM + TTS — agent can respond when addressed
- **Hard rule:** Agent only responds when directly addressed
  - LLM receives the transcript and decides: direct address vs. mention
  - "Agricola, what do you think?" → agent responds
  - "Agricola is in the room" → [SILENCE], agent stays quiet
- Agent name is configurable in the dashboard

### TTS (Piper)
- Piper TTS with standard voices (fast, ~1s generation on CPU)
- Voice is configurable in the dashboard
- Recommended voices for a commanding agent: `norman`, `joe`

### Post-Call Memory
- Transcript saved with speaker labels
- Agent's own responses logged in transcript
- Speaker names mapping saved to JSON
- Transcripts stored in `/tmp/armchair/transcript_YYYYMMDD_HHMMSS.txt`

## Setup

### Prerequisites

**WSL (Python 3.12+):**
```bash
pip install -r requirements.txt
```

**Windows:**
- **VB-Audio Virtual Cable** (CABLE-A) — [download](https://vb-audio.com/Cable/)
- **ffmpeg** at `C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe`
- **Piper TTS** — installed at `/home/krisr/.local/bin/piper` (WSL)

**GPU:**
- NVIDIA GPU with CUDA support
- faster-whisper and pyannote-audio both run on CUDA

**HuggingFace (for pyannote-audio):**
- Create a HuggingFace account
- Accept the model license at [pyannote/speaker-diarization-3.1](https://hf.co/pyannote/speaker-diarization-3.1)
- Set `HF_TOKEN` environment variable or use cached credentials

**Ollama (for Talk mode):**
- Ollama running on localhost:11434
- Any chat model (default: `deepseek-v3.2:cloud`)

### Audio Routing (One-Time)

1. Run `setup_audio.bat` on Windows
2. Set Windows default playback → **CABLE-A Input**
3. Enable "Listen to this device" on CABLE-A Output → your stereo speakers
4. Teams mic stays on your normal microphone (e.g., Jabra PanaCast)

### Running the Pipeline

**Terminal 1 (Windows):**
```
stream_to_file.bat
```

**Terminal 2 (WSL):**
```bash
/home/krisr/.local/share/whisper-venv/bin/python3 armchair_live.py
```

**Browser:**
```
http://localhost:8765
```

### Dashboard Controls

- **Mode toggle:** Listen / Talk
- **Agent name:** Configurable text field
- **Voice:** Dropdown of available Piper voices
- **Speaker names:** Auto-populates as speakers are detected; type names to label them
- **Copy All:** Copy the full transcript

## Latency Budget

| Step | Time |
|------|------|
| Whisper (4s chunk, CUDA) | ~0.1s |
| pyannote diarization (CUDA) | ~0.1s |
| LLM gate + response (Ollama) | ~2-3s |
| Piper TTS generation | ~1s |
| Audio playback | ~0.5s |
| **Total (Talk mode)** | **~3.5-4.5s** |
| **Total (Listen mode)** | **~0.2s** |

## Design Decisions

- **No bot joins the meeting.** Hardware audio capture via VB-Cable. Teams can't block it.
- **No third-party APIs.** Runs entirely on local hardware. Zero per-hour cost.
- **Piper TTS, not Kokoro.** Piper is ~12x faster (1s vs 12s cold start). Standard voices, lower quality, but the latency win is decisive for real-time conversation.
- **LLM gate for direct address.** The LLM decides if it's being addressed vs. mentioned. No fragile keyword matching. One call, natural understanding.
- **Agent name and voice configurable.** The dashboard lets you change the agent identity without touching code. Use any name, any Piper voice.
- **Speaker naming in the dashboard.** Assign names to speaker labels mid-call. Applies retroactively and going forward.

## License

MIT — See [LICENSE](LICENSE)

---

*Agent In The Armchair.* 🪑