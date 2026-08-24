# STATUS — Agent In The Armchair

## Current Version: v2 (streaming) — WORKING

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Streaming VTT** | ✅ Working | Silero VAD + faster-whisper streaming (word timestamps) |
| **Speaker Diarization** | ✅ Working | pyannote-audio on 16s rolling buffer, per-segment matching |
| **Talk/Listen Mode** | ✅ Working | LLM gate (deepseek-v4-flash), [SILENCE] for mentions |
| **Piper TTS** | ✅ Working | Alan (British RP), ~1s generation, plays to meeting via CABLE-A |
| **Dashboard** | ✅ Working | Speaker naming with Label button, agent config, mode toggle |
| **Session Management** | ✅ Working | Timestamped folders, clean start/stop, archives transcript + audio |
| **One-Click Launcher** | ✅ Working | start_armchair.bat — starts everything, Ctrl+C saves and cleans |
| **Mic Capture** | ✅ Working | ffmpeg amix mixes meeting audio + Jabra Panacast mic |
| **Voices Folder** | ✅ In repo | 8 sample WAVs (3 British, 5 American) with README |
| **requirements.txt** | ✅ Created | For external installation |

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

### TTS
- `Speaker` — Piper TTS
- Voice: en_GB-alan-medium (British RP)
- Piper generates WAV → copy to /mnt/b/ → PowerShell PlaySync → CABLE-A → meeting
- ~1s generation on CPU
- Speed adjustable via --length-scale

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
- **TTS:** Piper (`/home/krisr/.local/bin/piper`)
- **LLM:** Ollama deepseek-v4-flash:cloud
- **HF Token:** stored in `/mnt/b/OpenClaw/.openclaw/.env`
- **Piper voices:** `/home/krisr/.local/share/piper/`

## CUDA/cuDNN Notes

- **cuDNN MUST be disabled for pyannote** — `torch.backends.cudnn.enabled = False`
- cu12 (9.23) and cu13 (9.20) cuDNN packages conflict at GPU level
- faster-whisper only needs cuBLAS — works fine without cuDNN
- Without cuDNN: Whisper ~0.3s, pyannote ~1.5s per 16s buffer

## Known Issues

1. **TTS echo** — Agricola's TTS voice gets picked up by the mic capture (CABLE-A loop). Need echo suppression like Cochran.
2. **LLM latency** — ~1-2s for deepseek-v4-flash. Could be faster with a smaller model.
3. **Diarization on short utterances** — rapid speaker switches (gym interviews) are hard. Real meetings are easier.
4. **GPU load** — Whisper + pyannote both on CUDA. VAD helps but Talk mode adds LLM + TTS.

## Git
- Repo: https://github.com/Roughn3ck/Armchair
- Local: `/mnt/b/Github/Armchair/`