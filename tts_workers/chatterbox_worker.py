#!/home/krisr/.local/share/chatterbox-venv/bin/python
"""Chatterbox TTS worker — persistent process, JSON-over-stdin protocol.

Protocol: one JSON object per line on stdin:
  {"text": "...", "out": "/path/to/out.wav"}
Responds one JSON line on stdout:
  {"ok": true}  or  {"ok": false, "error": "..."}
"""
import sys
import json


def main():
    import sys, os, json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Silence all non-JSON output on stdout — protocol channel must stay clean
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    import torch
    import soundfile as sf
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(json.dumps({"ok": True, "event": "ready", "device": device}), flush=True)

    model = ChatterboxTTS.from_pretrained(device=device)
    print(json.dumps({"ok": True, "event": "loaded"}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            text = req["text"]
            out = req["out"]
            ref = req.get("ref")

            kwargs = {}
            if ref:
                kwargs["audio_prompt_path"] = ref

            wav = model.generate(text, **kwargs)
            # torchaudio.save needs torchcodec in this env — use soundfile instead
            import soundfile as sf
            sf.write(out, wav.squeeze(0).detach().cpu().numpy(), model.sr)
            print(json.dumps({"ok": True}), flush=True)
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)[:300]}), flush=True)


if __name__ == "__main__":
    main()
