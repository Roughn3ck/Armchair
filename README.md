# 🪑 Agent In The Armchair

**Real-time Voice-to-Text for Microsoft Teams.** Invisible. Local. Free.

Agent In The Armchair sits in your Teams meetings, listens, and transcribes — in real time, on your hardware, with zero per-hour costs. No bot joins the meeting. Teams doesn't know it's there. You're just a person with your headset on.

Part of [The Pack](https://github.com/Roughn3ck/ExecutiveMind) at [Executive Mind](https://executivemind.io).

---

## What This Is

A real-time VTT (Voice-to-Text) pipeline that captures Teams meeting audio through a virtual cable, transcribes it with faster-whisper (CUDA), and displays a live transcript on a local dashboard.

```
Teams Meeting Audio (speaker output)
       ↓
CABLE-A Input (Teams playback device)
       ↓
CABLE-A Output → ffmpeg (16kHz mono PCM)
       ↓
B:\armchair_audio.raw
       ↓
WSL: armchair_live.py → faster-whisper (CUDA) → transcript
       ↓
Dashboard (http://localhost:8765)
```

You hear the meeting through your stereo speakers (via CABLE-A Output "Listen" tab). Teams mic stays on your Jabra PanaCast. No changes to how you talk — only how the audio output gets routed.

## What's Here

| File | Purpose |
|------|---------|
| `armchair_live.py` | Main VTT pipeline (listen + transcribe) |
| `dashboard_server.py` | HTTP server for live dashboard |
| `dashboard.html` | Web dashboard with live transcript |
| `stream_to_file.bat` | Windows ffmpeg audio capture |
| `setup_audio.bat` | Audio routing setup guide |

## Setup

### Prerequisites
- **VB-Audio Virtual Cable** (CABLE-A) — [download](https://vb-audio.com/Cable/)
- **ffmpeg** on Windows (at `C:\Users\krisr\Documents\ffmpeg\ffmpeg.exe`)
- **faster-whisper** with CUDA in WSL (`/home/krisr/.local/share/whisper-venv/`)
- **RTX GPU** (CUDA support for real-time transcription)

### One-Time Setup
1. Run `setup_audio.bat` on Windows — walks you through routing
2. Set Teams speaker → **CABLE-A Input**
3. Enable "Listen to this device" on CABLE-A Output → your stereo speakers
4. Keep Teams mic → **Jabra PanaCast 20**

### Running the Pipeline

**Terminal 1 (Windows):**
```
stream_to_file.bat
```

**Terminal 2 (WSL):**
```
python3 armchair_live.py
```

**Browser:**
```
http://localhost:8765
```

### Latency Budget

| Step | Time |
|------|------|
| ffmpeg capture (4s chunk) | ~0s (streaming) |
| Whisper (4s chunk, CUDA) | ~0.1s |
| **Total** | **~0.1s per 4s chunk** |

## Design Decisions

- **No bot joins the meeting.** Teams can't block this approach. No Azure registration, no admin consent, no API limits.
- **No third-party APIs.** Runs entirely on local hardware. Zero per-hour cost.
- **VTT only (for now).** No TTS, no LLM. Pure transcription. TTS and agent integration can be added later.
- **CABLE-A, not CABLE.** Uses the second VB-Cable to avoid conflicts with Cochran's CABLE.

## License

MIT — See [LICENSE](LICENSE)

---

*Agent In The Armchair.* 🪑