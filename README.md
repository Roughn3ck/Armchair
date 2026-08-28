# 🪑 Agent In The Armchair

**Real-time streaming Voice-to-Text + AI Agent for any call app** — Signal, Teams, Zoom, Meet. Invisible. Local. Free.

Agent In The Armchair sits in your calls, listens, transcribes with speaker labels, and speaks when directly addressed — in real time, on your hardware, with zero per-hour costs. No bot joins the call. The app doesn't know it's there.

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

**Windows (Python 3.12+):**
```powershell
cd C:\path\to\Armchair\Armchair
.\install.bat
```
`install.bat` creates all venvs (Whisper/Kokoro/Chatterbox), downloads **ffmpeg** automatically into the project folder if it isn't on PATH, downloads the **Piper** binary, and offers to install **VB-Audio Virtual Cable**.

**Piper voices:** starter voices ship in the repo's `voices\` folder and work out of the box. For more, browse the [Piper Voices catalog](https://github.com/rhasspy/piper/blob/master/VOICES.md) — you need BOTH files per voice (`<voice>.onnx` + `<voice>.onnx.json`) — and drop them into the repo's `voices\` folder. Recommended extra: **en_US-lessac-medium**.

### GPU: NVIDIA with CUDA support

Any CUDA GPU from the last decade works. **RTX 50-series (Blackwell, sm_120) owners:** you need torch built with CUDA 12.8 — `install.bat` handles this automatically (it installs from the cu128 index and verifies `torch.cuda.is_available()` after install). Older GPUs (Ampere/Ada, sm_80–sm_90) also run fine on cu128 wheels.

If you ever install torch manually, always install `torch` and `torchaudio` together from the same index URL — version mismatches between them cause cryptic DLL entry-point errors.

**HuggingFace (for speaker diarization):**

Speaker labels ("[MUM]", "[DAD]" in the transcript) come from [pyannote-audio](https://github.com/pyannote/pyannote-audio) (installed by `install.bat`), whose models are hosted on HuggingFace. It's **gated** — you need a free HF account to unlock it. One-time, ~2 minutes:

1. Create a free account at [huggingface.co](https://huggingface.co/join)
2. Visit and click **"Agree to run repository or access repository"** on both models:
   - [pyannote/speaker-diarization-3.1](https://hf.co/pyannote/speaker-diarization-3.1)
   - [pyannote/segmentation-3.0](https://hf.co/pyannote/segmentation-3.0)
3. Create a token at [hf.co/settings/tokens](https://hf.co/settings/tokens) — choose **Read** access
4. Put it in your `.env` file: `HF_TOKEN=hf_xxxx...`

Without this the agent still runs — you just get `[UNKNOWN]` instead of named speakers.

**Ollama (for Talk mode):** Running on localhost:11434

### Audio Routing (One-Time)

![The Voicemeeter Mess](assets/voicemeeter-mess.jpg)

*Yes, audio routing is a mess. Here's how to tame it.*

Run `setup_audio.ps1` to automate most of this, or follow the manual steps below.

#### Option A — Voicemeeter Banana (recommended, full control)

The verified-working configuration for calls (e.g. Signal):

| Element | Setting |
|---------|---------|
| Hardware Input 1 (your mic) | → **A1** + **B1**, mono |
| CABLE-A Output strip | → **A1** + **B1** |
| A1 output device | Your speakers/headphones |
| B1 | Virtual — this is what the call app sees as "mic" |

Then in your call app:
- **Microphone:** `Voicemeeter Output (VB-Audio Voicemeeter VAIO)` (= B1)
- **Speaker:** your normal speakers/headphones

And in Windows Sound settings:
- **Default playback device:** `CABLE-A Input` — critical. TTS rides into B1 through this.

Signal flow: your mic and the agent's TTS both land on B1 (the caller hears both); A1 lets you hear everything locally.

#### Option B — No Voicemeeter (simpler, listen-only + TTS)
1. Run `setup_audio.bat` for a guided walkthrough
2. Set Windows default playback → CABLE-A Input
3. Enable "Listen to this device" on CABLE-A Output → your stereo speakers
4. Call app mic → your normal microphone

### Running the Pipeline

One-click from PowerShell:
```powershell
.\start_armchair.bat
```
Opens audio capture, dashboard (`http://localhost:8765`), browser, and pipeline in one window. Ctrl+C stops and saves the session.

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

### Piper (built-in voices)

See `voices/README.md` for the full list of sample voices.

| Voice | Accent | Recommended |
|-------|--------|:-----------:|
| **Alan** | British RP | ⭐ |
| Aru | British | |
| Northern English Male | Northern UK | |
| Norman | US, deep | |

Download more from [Piper Voices](https://github.com/rhasspy/piper/blob/master/VOICES.md).

### Chatterbox (voice cloning)

Chatterbox speaks in **any voice you give it** — clone yourself, a character, your agent's persona. Zero-shot, no training.

**1. Record a reference sample:**
- 10–25 seconds of clean solo speech
- Mono WAV (24kHz or 48kHz), consistent mic distance
- No music, no cross-talk — conversational energy works better than reading

**2. Place it in the repo voices folder** (single voices dir for ALL engines — Piper models, chatterbox refs, kokoro assets):
```
C:\armchair\Armchair\voices\muska-reference.wav
```

**3. Point Armchair at it (two ways):**
- **Dashboard** — TTS Engine → `chatterbox`, paste the path into **Ref WAV**, save. Swaps in on the next utterance, no restart.
- Or set it before launch and hit ⚡Activate on the dashboard to pre-warm the model (~8s cold-start first utterance, ~2.4s warm after).

**Tips for a good clone:**
- Longer + cleaner > shorter + noisy. 20s of quiet-room speech beats 10s with fan noise
- Match the delivery you want: if the agent should sound calm, record calm
- One speaker per sample — no overlaps

### Kokoro (premium built-in voices)

Kokoro sits between Piper and Chatterbox: **studio-quality voices with zero setup** — no samples to record, no files to download. ~1.6s generation warm.

**Using it:**
- Dashboard → TTS Engine → `kokoro` → save. That's it.
- Default voice is `af_heart` (warm, natural female US).

**Voices:** Kokoro ships 40+ voice packs across accents and styles. The pipeline runs American English (`lang_code="a"`); British English (`"b"`), Japanese, Chinese, and more are supported by the model itself — see the [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M) for the full voice list (`af_*` = American female, `bm_*` = British male, etc.).

**Choosing an engine:**

| Engine | Latency | Setup | Best for |
|--------|---------|-------|----------|
| Piper | ~1s | download one .onnx pair | fastest responses, low VRAM |
| Kokoro | ~1.6s | none | best quality-to-effort ratio |
| Chatterbox | ~2.4s | reference WAV | a specific voice/persona |

All three hot-swap mid-call from the dashboard; the worker pool keeps used engines loaded so switching back is instant.

## License

MIT — See [LICENSE](LICENSE)

---

*Agent In The Armchair.* 🪑