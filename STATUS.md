# STATUS — Agent In The Armchair

## Current Version: v2 (streaming)

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Streaming VTT** | ✅ Built | Silero VAD + faster-whisper streaming (local agreement) |
| **Speaker Diarization** | ✅ Built | pyannote-audio on 16s rolling buffer, every 10s |
| **Talk/Listen Mode** | ✅ Built | LLM gate, [SILENCE] for mentions, Piper TTS |
| **Dashboard** | ✅ Built | Speaker naming, agent config, mode toggle |
| **Post-call transcript** | ✅ Built | Speaker-labeled + agent responses |
| **requirements.txt** | ✅ Created | For external installation |
| **README** | ✅ Updated | v2 streaming architecture documented |

## Architecture History

### v1 (chunk-based) — ABANDONED
- Fixed 4s chunks → transcribe → diarize each chunk
- **Problem:** Diarization can't separate speakers on 4s chunks
- **Problem:** SPEAKER_UNKNOWN flickered between diarization runs
- **Problem:** GPU heavy — Whisper + pyannote on every chunk including silence
- **Problem:** 4s minimum latency, chunks cut words mid-sentence

### v2 (streaming) — CURRENT
- Silero VAD detects speech, skips silence (nearly free)
- faster-whisper streaming with local agreement (incremental output)
- pyannote-audio on 16s rolling buffer (every 10s, separate thread)
- Stable speaker labels — defaults to last known, no flickering
- Much lighter GPU usage — VAD is nearly free, Whisper only on speech

## Pipeline Components

### Audio Capture
- `stream_to_file.bat` — ffmpeg captures CABLE-A Output → `B:\armchair_audio.raw`
- Continuous stream (not fixed chunks)
- 16kHz mono 16-bit PCM

### Audio Reader
- `AudioStreamReader` — reads raw file continuously, tracks offset
- Skips to end on first read (don't process old audio)
- Returns numpy float32 arrays

### VAD
- `VAD` — Silero VAD model
- Processes audio in 512-sample frames (32ms at 16kHz)
- Returns speech audio or None (silence)
- Threshold: 0.5 speech probability

### Streaming Transcriber
- `StreamingTranscriber` — faster-whisper with local agreement
- Accumulates VAD-detected speech
- Transcribes incrementally — only commits text that appears in consecutive transcriptions
- Max buffer: 30s of audio

### Diarizer
- `Diarizer` — pyannote-audio on 16s rolling buffer
- Runs every 10s (not every chunk)
- Maps pyannote labels to stable SPEAKER_XX labels
- cuDNN disabled (cu12/cu13 version conflict)
- Without cuDNN: ~1.5-2s per diarization pass on CUDA

### LLM Gate
- `Thinker` — Ollama API
- Receives recent transcript, decides: direct address vs mention
- Returns [SILENCE] for mentions, response for direct address
- Agent name configurable in dashboard

### TTS
- `Speaker` — Piper TTS
- Voice configurable in dashboard (norman recommended for commanding agent)
- Plays to CABLE-A Input → meeting hears agent
- ~1s generation on CPU

### Dashboard
- `dashboard_server.py` — HTTP server on :8765
- `dashboard.html` — live transcript, speaker naming, agent config, mode toggle
- API endpoints: /api/status, /api/mode, /api/speaker-names, /api/agent-config

## Audio Routing

```
Teams speaker → CABLE-A Input (Windows default playback)
CABLE-A Output → "Listen to this device" → stereo speakers (you hear meeting)
ffmpeg captures CABLE-A Output → B:\armchair_audio.raw
Teams mic → Jabra PanaCast 20 (unchanged)
```

## Environment

- **Python venv:** `/home/krisr/.local/share/whisper-venv/`
- **Whisper model:** large-v3-turbo (CUDA)
- **VAD:** Silero VAD (via torch.hub)
- **Diarization:** pyannote-audio 4.0.7 (CUDA, cuDNN disabled)
- **TTS:** Piper (`/home/krisr/.local/bin/piper`)
- **HF Token:** stored in `/mnt/b/OpenClaw/.openclaw/.env`
- **whisper_streaming:** cloned to `/tmp/whisper_streaming` (for reference, not used directly)

## CUDA/cuDNN Notes

- **cuDNN MUST be disabled for pyannote** — `torch.backends.cudnn.enabled = False`
- cu12 (9.23) and cu13 (9.20) cuDNN packages conflict at GPU level
- Enabling cuDNN causes `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` or CUDA illegal memory access
- faster-whisper only needs cuBLAS, not cuDNN — works fine without it
- Without cuDNN: Whisper ~0.2s per chunk, pyannote ~1.5-2s per 16s buffer

## Git
- Repo: `/mnt/b/Github/Armchair/` (local only, not pushed to GitHub yet)
- Commits: 10+

## Next Steps
1. Test streaming pipeline live with YouTube video (two speakers)
2. Verify speaker separation works on 16s rolling buffer
3. Test Talk mode (say "Agricola" and verify LLM gate)
4. Push to GitHub (create Roughn3ck/Armchair repo)
5. Add post-call speaker naming prompt
6. Consider cloud API fallback (Deepgram) for comparison