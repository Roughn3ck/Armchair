# STATUS — Agent In The Armchair

## Current Version: v2.1 (multi-engine TTS) — WORKING

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Streaming VTT** | ✅ Working | Silero VAD + faster-whisper streaming (word timestamps) |
| **Speaker Diarization** | ⚠️ Weak | pyannote works but recognition quality poor — enrollment planned for v2.2 |
| **Talk/Listen Mode** | ✅ Working | LLM gate (deepseek-v4-flash), [SILENCE] for mentions |
| **Piper TTS** | ✅ Working | Alan default, ~1s generation, instant voice swaps |
| **Kokoro TTS** | ✅ Working | ~1.6s warm gen, persistent worker in own venv (CUDA) |
| **Chatterbox TTS** | ✅ Working | Voice cloning from ref WAV (Muska), ~2.4s warm / ~8s cold |
| **Mid-call engine/voice hot-swap** | ✅ Working | (engine, voice, ref) signature checked between responses |
| **⚡Activate pre-warm** | ✅ Working | Dashboard button loads engine in background via watcher thread |
| **Worker pool** | ✅ Working | Engines stay loaded; switch-back is instant |
| **Memory directory** | ✅ Working | Custom folder of .md/.txt loaded into system prompt; Windows paths auto-normalized |
| **Dashboard** | ✅ Working | Speaker naming, agent config, engine select + Activate, mode toggle |
| **Session Management** | ✅ Working | Timestamped folders, clean start/stop, archives transcript + audio |
| **One-Click Launcher** | ✅ Working | start_armchair.bat |
| **Mic Capture** | ✅ Working | ffmpeg amix (meeting audio + Jabra Panacast) |

## Verified Live (2026-08-25)

- Full call test with Chatterbox/Muska voice cloning — clear, perfect clone from 22s reference WAV
- Agent loaded with Muska's real workspace memory (`/mnt/b/OpenClaw/.openclaw/workspace`) at call time
- Voicemeeter Banana routing verified end-to-end (Jabra → B1 mix, CABLE-A capture)
- Kokoro worker: 6.3s load, 1.6s warm generation
- Chatterbox worker: 6.9s load, 8.5s cold gen, 2.4s warm generation

## Verified Live (2026-08-24)

- 3 speakers detected and labeled correctly in real-time (YouTube gym interviews)
- Agent (Agricola) responds when directly addressed, stays silent for mentions
- TTS plays Alan's British RP voice through CABLE-A to meeting
- Speaker naming on dashboard with Label button — applies retroactively
- Session archives to `B:\armchair_tmp\session_logs\YYYY-MM-DD_HHMMSS\`
- 0.3s transcription latency in Listen mode
- ~3-4s response latency in Talk mode (LLM + TTS)

## Architecture History

### v1 (chunk-based) — ABANDONED
- Fixed 4s chunks → transcribe each → diarize each
- Diarization can't separate speakers on 4s chunks
- SPEAKER_UNKNOWN flickered, GPU heavy, 4s min latency, words cut

### v2 (streaming) — CURRENT
- Silero VAD detects speech, skips silence
- faster-whisper streaming with word timestamps
- pyannote-audio on 16s rolling buffer (every 10s)
- Per-segment speaker matching (Whisper timestamps → pyannote labels)
- Stable speaker labels — no flickering
- Much lighter GPU — VAD nearly free, Whisper only on speech

## Pipeline Components

### Audio Capture
- `stream_to_file.bat` — ffmpeg captures CABLE-A Output + Jabra Panacast mic
- `amix` filter mixes both into one 16kHz mono PCM stream
- Continuous stream (not fixed chunks)

### Audio Reader
- `AudioStreamReader` — reads raw file continuously, tracks offset
- Skips to end on first read (don't process old audio)

### VAD
- `VAD` — Silero VAD model (torch.hub)
- 512-sample frames (32ms at 16kHz)
- Returns speech audio or None (silence)
- Threshold: 0.5 speech probability

### Streaming Transcriber
- `StreamingTranscriber` — faster-whisper with word_timestamps=True
- Returns segments with start/end timestamps
- 10s max buffer

### Diarizer
- `Diarizer` — pyannote-audio on 16s rolling buffer
- Runs every 10s (not every chunk)
- Returns per-segment speaker labels (start, end, speaker)
- `get_speaker_for_time()` matches Whisper segments to speakers
- cuDNN disabled (cu12/cu13 version conflict)
- ~1.5s per diarization pass on CUDA

### LLM Gate
- `Thinker` — Ollama API (deepseek-v4-flash:cloud)
- Receives recent transcript, decides: direct address vs mention
- Returns [SILENCE] for mentions, response for direct address
- Agent name configurable in dashboard

### TTS — Multi-Engine
- `Speaker` dispatches to piper | kokoro | chatterbox via `tts_engine` config
- Kokoro/chatterbox run as persistent `EngineWorker` subprocesses in isolated venvs
  - JSON-over-stdin protocol; tolerates non-JSON noise on stdout
  - Global `_WORKER_POOL` keeps engines loaded across hot-swaps
- Hot-swap: main loop re-reads agent config after each response; rebuilds Speaker when (engine, voice, ref) changes
- Prewarm: dashboard ⚡Activate → `/tmp/armchair/tts_prewarm.txt` → watcher thread starts worker in background
- Generation writes to `/tmp/armchair_tts/` (native ext4 — drvfs write races), then single copy to `B:\` for PowerShell PlaySync
- Piper speed: --length-scale 0.8

### Dashboard
- `dashboard_server.py` — HTTP server on :8765
- API: /api/status, /api/mode, /api/speaker-names, /api/agent-config
- `dashboard.html` — live transcript, speaker naming (with Label button), agent config, mode toggle
- 2s refresh interval
- Speaker rows added incrementally (input keeps focus)

### Session Management
- On startup: creates `B:\armchair_tmp\session_logs\YYYY-MM-DD_HHMMSS\`
- Clears all runtime state (no bleed between sessions)
- On shutdown: saves transcript.txt, speaker_names.json, detected_speakers.json, audio.raw

## Audio Routing

```
Teams speaker → CABLE-A Input (Windows default playback)
CABLE-A Output → "Listen to this device" → stereo speakers
ffmpeg captures CABLE-A Output + Jabra Panacast mic → amix → B:\armchair_audio.raw
Agricola TTS → PowerShell PlaySync → CABLE-A Input → CABLE-A Output → meeting + speakers
```

## Environment

- **Python venv:** `/home/krisr/.local/share/whisper-venv/`
- **Whisper model:** large-v3-turbo (CUDA)
- **VAD:** Silero VAD (via torch.hub)
- **Diarization:** pyannote-audio 4.0.7 (CUDA, cuDNN disabled)
- **TTS:** Piper (`/home/krisr/.local/bin/piper`); Kokoro (`~/.local/share/kokoro-venv`); Chatterbox (`~/.local/share/chatterbox-venv`)
- **Voice refs:** `/home/krisr/.local/share/chatterbox/*.wav`
- **LLM:** Ollama deepseek-v4-flash:cloud
- **HF Token:** stored in `/mnt/b/OpenClaw/.openclaw/.env`
- **Piper voices:** `/home/krisr/.local/share/piper/`

## CUDA/cuDNN Notes

- **cuDNN MUST be disabled for pyannote** — `torch.backends.cudnn.enabled = False`
- cu12 (9.23) and cu13 (9.20) cuDNN packages conflict at GPU level
- faster-whisper only needs cuBLAS — works fine without cuDNN
- Without cuDNN: Whisper ~0.3s, pyannote ~1.5s per 16s buffer

## Known Issues

1. **Speaker recognition weak** — generic clustering mislabels/mixes speakers. Plan (v2.2): pyannote speaker enrollment (embed reference samples per person, match per utterance), larger rolling buffer (16→24s), per-utterance re-check.
2. **TTS echo** — agent's TTS picked up by mic capture (CABLE-A loop). Name-gate mostly handles it; echo suppression still needed.
3. **LLM latency** — ~1-2s for deepseek-v4-flash. Could be faster with a smaller model.
4. **Diarization on short utterances** — rapid speaker switches are hard. Real meetings are easier.
5. **GPU load** — Whisper + pyannote + parked TTS workers all share CUDA. Monitor VRAM when both engines activated.

## Git
- Repo: https://github.com/Roughn3ck/Armchair
- Local: `/mnt/b/Github/Armchair/`