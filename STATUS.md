# STATUS — Agent In The Armchair

## Current Version: v2.1 (multi-engine TTS) — WORKING

## Build Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Streaming VTT** | ✅ Working | Silero VAD + faster-whisper streaming (word timestamps) |
| **Speaker Diarization** | ⚠️ Weak | pyannote works but recognition quality poor — enrollment planned for v3.0 |
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

---

## Roadmap to v3.0 — Production Ready

### v2.2 — Branding & Dashboard Polish (current)
- [ ] EM brand kit on dashboard (grunge dark logo, link to executivemind.io)
- [ ] Version number visible on dashboard
- [ ] Dashboard CSS overhaul — grunge/cyberpunk aesthetic matching brand
- [ ] Settings panel foundation (collapsed section, ready for v2.3 fields)

### v2.3 — LLM Provider Settings
- [ ] Settings section in dashboard:
  - LLM provider dropdown: Ollama / OpenAI / Anthropic / TokenRa / OpenRouter
  - API key fields per provider (stored in agent_config.json, never in repo)
  - Model field per provider (text input — user picks their model)
  - Timezone selector (dropdown, defaults to system tz — for VPN/travel users)
- [ ] Thinker class refactored to provider-agnostic LLMClient
- [ ] Remove all hardcoded LLM host/model/credentials
- [ ] Config validation (test API key on save, show green/red)

### v2.4 — Platform Abstraction Layer
- [ ] `platform_config.py` — detects OS, loads platform-specific paths/config
- [ ] `AudioOutput` interface — play wav into meeting mix
  - `WindowsCableOutput` (PowerShell PlaySync → VB-Cable)
  - `LinuxSinkOutput` (pw-play/paplay → PipeWire virtual sink)
- [ ] `AudioCapture` interface — provide 16kHz mono PCM stream
  - `WindowsFFmpegCapture` (ffmpeg + VB-Cable, as now)
  - `LinuxPipeWireCapture` (ffmpeg + PipeWire monitor source)
- [ ] Remove all hardcoded paths (`/home/krisr`, `B:\`, `/mnt/b/`)
- [ ] `config.toml` — all user-configurable paths, devices, venv locations
- [ ] `start_armchair.sh` — Linux one-click launcher

### v2.5 — Linux-Native Build & Test
- [ ] Pre-flight: full system scan before dual-boot (RAID integrity, disk health, backup verification)
- [ ] Boot into Linux, verify CUDA/torch/pyannote stack
- [ ] Install TTS venvs natively (piper, kokoro, chatterbox)
- [ ] PipeWire virtual sink setup + test (replaces Voicemeeter/VB-Cable)
- [ ] End-to-end test: live call with Chatterbox/Muska voice on Linux
- [ ] Fix any platform-specific issues discovered
- [ ] Document Linux setup in README

### v2.6 — Windows-Native Build
- [ ] Windows Python environment (no WSL dependency)
- [ ] Windows-native paths, PowerShell playback (already proven)
- [ ] VB-Cable + Voicemeeter setup (already proven)
- [ ] End-to-end test on pure Windows
- [ ] Document Windows setup in README

### v2.7 — Packaging & Distribution
- [ ] Installer script approach (recommended over PyInstaller):
  - `install.sh` / `install.bat` — creates venvs, pip installs deps, downloads models
  - User clones repo, runs one script, ready to go
  - Why not PyInstaller: pyannote + torch + CUDA = ~4GB bundle, fragile, version-locked
  - Installer script = user gets latest torch for their GPU, we stay maintainable
- [ ] OR PyInstaller investigation if Kris wants single-file distribution:
  - Assess feasibility with torch+CUDA payload
  - Likely needs onefile + data folder, not true single-binary
- [ ] First-time setup wizard (dashboard-guided: pick LLM provider, test mic, etc.)

### v2.8 — Speaker Enrollment (v3.0 feature backfill)
- [ ] Record reference samples per known speaker (5-15s clean audio)
- [ ] Compute pyannote embeddings once at startup
- [ ] Per-utterance matching against enrolled profiles
- [ ] "SPEAKER_00" → "Dad" automatically, no manual labeling
- [ ] Bump rolling buffer 16→24s for more diarization context

### v2.9 — Polish & Hardening
- [ ] Echo suppression (TTS self-hear via audio loop)
- [ ] Error recovery (auto-restart failed workers, graceful degradation)
- [ ] Config validation on startup (missing venvs, bad paths, etc.)
- [ ] Logging to file with rotation
- [ ] Performance dashboard (latency graphs, GPU usage)

### v3.0 — Production Release
- [ ] Full documentation (README, setup guide, troubleshooting)
- [ ] GitHub release with install scripts for Windows + Linux
- [ ] Tag v3.0

---

## Repository Structure (proposed v2.4+)

```
Armchair/
├── armchair/              # Core Python package (platform-agnostic)
│   ├── __init__.py
│   ├── pipeline.py        # Main streaming pipeline
│   ├── vad.py             # Silero VAD
│   ├── transcriber.py     # faster-whisper streaming
│   ├── diarizer.py        # pyannote-audio
│   ├── thinker.py         # LLM client (provider-agnostic)
│   ├── speaker.py         # TTS dispatcher (multi-engine)
│   ├── audio_io.py        # AudioOutput / AudioCapture interfaces
│   ├── platform.py       # OS detection, path resolution
│   └── config.py         # Config loading/validation
├── tts_workers/           # Engine workers (cross-platform)
│   ├── kokoro_worker.py
│   └── chatterbox_worker.py
├── dashboard/             # Web UI
│   ├── server.py
│   ├── index.html
│   └── assets/
│       └── em-logo-grunge-dark.jpg
├── scripts/               # Platform launchers + installers
│   ├── start_armchair.bat
│   ├── start_armchair.sh
│   ├── install.bat
│   └── install.sh
├── config.example.toml    # User copies to config.toml
├── requirements.txt
├── README.md
└── STATUS.md
```

---

## Decision Log

1. **Linux-first** (Kris approved 2026-08-25) — friction disappears, validates abstraction layer cheaply
2. **WSL bridge version retired** — not worth maintaining tri-platform. Windows-native and Linux-native only. (Kris asked, Slater recommended retiring — see Q4 below)
3. **Branding**: em-logo-grunge-dark.jpg, executivemind.io link, version on dashboard
4. **LLM providers**: Ollama, OpenAI, Anthropic, TokenRa, OpenRouter — all configurable
5. **Packaging**: installer script recommended (pyannote+torch makes PyInstaller fragile). Final decision after v2.7 investigation.
6. **Pre-flight scan mandatory** before dual-boot (Kris's RAID incident history)

## Q&A from 2026-08-25 planning session

**Q1: Dual-boot safety (RAID incident history)**
A: Full system scan before crossing. Check RAID array status, disk health, verify /mnt/b mount on Linux side, confirm read-write test. No booting across until green.

**Q2: PyInstaller vs installer script**
A: Installer script = "clone repo, run install.sh, done". User gets correct torch for their GPU, we stay maintainable. PyInstaller with torch+CUDA = 4GB fragile bundle. Recommend installer script; investigate PyInstaller at v2.7 if Kris wants single-file.

**Q3: Branding**
A: em-logo-grunge-dark.jpg in dashboard header. CSS aesthetic overhaul. Version number. Link to executivemind.io. Logo is busy square — use small in corner, extract monogram later for cleaner look.

**Q4: Keep WSL bridged version?**
A: No. The WSL bridge is a development convenience, not a production target. Maintaining three platforms (WSL/Windows/Linux) triples test surface for zero user benefit. Two clean native builds > one compromised bridge. The bridge version stays in git history as v2.1.

**Q5: LLM settings**
A: Provider-agnostic LLMClient with dropdown: Ollama / OpenAI / Anthropic / TokenRa / OpenRouter. API keys in agent_config.json (gitignored). Timezone selector. Model field per provider. Config validation (test key on save).

---

## Verified Live (2026-08-25)

- Full call test with Chatterbox/Muska voice cloning — clear, perfect clone from 22s reference WAV
- Agent loaded with Muska's real workspace memory at call time
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

### v2.1 (multi-engine TTS) — CURRENT
- Three TTS engines: Piper / Kokoro / Chatterbox (voice cloning)
- Persistent workers in isolated venvs, JSON-over-stdin protocol
- Mid-call hot-swap, prewarm Activate button, worker pool
- Memory directory loading, Windows path normalization
- drvfs write-race fix, warning suppression

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
- **v2.3**: Refactor to provider-agnostic LLMClient (Ollama/OpenAI/Anthropic/TokenRa/OpenRouter)

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
- API: /api/status, /api/mode, /api/speaker-names, /api/agent-config, /api/tts-prewarm
- `dashboard.html` — live transcript, speaker naming, agent config, engine select, mode toggle
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
Agent TTS → PowerShell PlaySync → CABLE-A Input → CABLE-A Output → meeting + speakers
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

1. **Speaker recognition weak** — generic clustering mislabels/mixes speakers. Plan (v2.8): pyannote speaker enrollment.
2. **TTS echo** — agent's TTS picked up by mic capture (CABLE-A loop). Name-gate mostly handles it; echo suppression still needed.
3. **LLM latency** — ~1-2s for deepseek-v4-flash. Could be faster with a smaller model.
4. **Diarization on short utterances** — rapid speaker switches are hard. Real meetings are easier.
5. **GPU load** — Whisper + pyannote + parked TTS workers all share CUDA. Monitor VRAM when both engines activated.

## Git
- Repo: https://github.com/Roughn3ck/Armchair
- Local: `/mnt/b/Github/Armchair/`