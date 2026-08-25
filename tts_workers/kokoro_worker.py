#!/home/krisr/.local/share/kokoro-venv/bin/python
"""Kokoro TTS worker — persistent process, JSON-over-stdin protocol.

Protocol: one JSON object per line on stdin:
  {"text": "...", "out": "/path/to/out.wav"}
Responds one JSON line on stdout:
  {"ok": true}  or  {"ok": false, "error": "..."}
"""
import sys
import json

KOKORO_VOICE_DEFAULT = "af_heart"  # warm, natural female US — swap freely


def main():
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(repo_id="hexgrad/Kokoro-82M", lang_code="a")  # 'a' = American English
    print(json.dumps({"ok": True, "event": "ready"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            text = req["text"]
            out = req["out"]
            voice = req.get("voice") or KOKORO_VOICE_DEFAULT

            chunks = []
            for _, _, audio in pipeline(text, voice=voice):
                chunks.append(audio)

            if not chunks:
                raise RuntimeError("no audio generated")

            full = chunks[0] if len(chunks) == 1 else __import__("numpy").concatenate(chunks)
            sf.write(out, full, 24000)
            print(json.dumps({"ok": True}), flush=True)
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)[:300]}), flush=True)


if __name__ == "__main__":
    main()
