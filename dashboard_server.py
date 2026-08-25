#!/usr/bin/env python3
"""Agent In The Armchair — Dashboard server (VTT + AI Agent)"""
import http.server
import json
import os
import time

TRANSCRIPT = '/tmp/armchair/transcript.txt'
LATENCY_FILE = '/tmp/armchair/latency.txt'
MODE_FILE = '/tmp/armchair/mode.txt'
PREWARM_FILE = '/tmp/armchair/tts_prewarm.txt'
SPEAKER_NAMES_FILE = '/tmp/armchair/speaker_names.json'
DETECTED_SPEAKERS_FILE = '/tmp/armchair/detected_speakers.json'
AGENT_CONFIG_FILE = '/tmp/armchair/agent_config.json'

# Serve static files (dashboard assets) from the script directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class ArmchairHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _read_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(content_length)

    def do_GET(self):
        if self.path == '/api/status':
            transcript = ''
            latency = ''
            try:
                with open(TRANSCRIPT, 'r') as f:
                    transcript = f.read()
            except: pass
            try:
                with open(LATENCY_FILE, 'r') as f:
                    latency = f.read().strip()
            except: pass
            try:
                with open(MODE_FILE, 'r') as f:
                    current_mode = f.read().strip()
            except:
                current_mode = 'listen'

            speaker_names = {}
            try:
                with open(SPEAKER_NAMES_FILE, 'r') as f:
                    speaker_names = json.load(f)
            except: pass

            detected_speakers = []
            try:
                with open(DETECTED_SPEAKERS_FILE, 'r') as f:
                    detected_speakers = json.load(f)
            except: pass

            agent_config = {}
            try:
                with open(AGENT_CONFIG_FILE, 'r') as f:
                    agent_config = json.load(f)
            except: pass

            self._send_json({
                'transcript': transcript,
                'latency': latency,
                'mode': current_mode,
                'speaker_names': speaker_names,
                'detected_speakers': detected_speakers,
                'agent_config': agent_config,
                'time': time.strftime('%H:%M:%S')
            })

        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            with open(os.path.join(_SCRIPT_DIR, 'dashboard.html'), 'rb') as f:
                self.wfile.write(f.read())
        elif self.path.startswith('/dashboard/assets/'):
            # Serve branded assets (logo, etc.) from dashboard/assets/
            asset_path = os.path.join(_SCRIPT_DIR, self.path.lstrip('/'))
            if os.path.isfile(asset_path):
                ext = os.path.splitext(asset_path)[1].lower()
                ctype = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
                         'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml'}.get(ext.lstrip('.'), 'application/octet-stream')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.end_headers()
                with open(asset_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/mode':
            body = self._read_body()
            try:
                data = json.loads(body)
                mode = data.get('mode', 'listen')
                with open(MODE_FILE, 'w') as f:
                    f.write(mode)
                print(f'[DASHBOARD] Mode: {mode}')
                self._send_json({'status': 'ok', 'mode': mode})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)

        elif self.path == '/api/speaker-names':
            body = self._read_body()
            try:
                data = json.loads(body)
                names = data.get('names', {})
                with open(SPEAKER_NAMES_FILE, 'w') as f:
                    json.dump(names, f)
                print(f'[DASHBOARD] Speaker names updated: {names}')
                self._send_json({'status': 'ok', 'names': names})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)

        elif self.path == '/api/agent-config':
            body = self._read_body()
            try:
                data = json.loads(body)
                # Merge with existing config
                existing = {}
                try:
                    with open(AGENT_CONFIG_FILE, 'r') as f:
                        existing = json.load(f)
                except: pass
                existing.update(data)
                with open(AGENT_CONFIG_FILE, 'w') as f:
                    json.dump(existing, f)
                print(f'[DASHBOARD] Agent config updated: {data}')
                self._send_json({'status': 'ok', 'config': existing})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)

        elif self.path == '/api/save-api-key':
            body = self._read_body()
            try:
                data = json.loads(body)
                provider = data.get('provider', '')
                key = data.get('key', '')
                key_map = {
                    'openai': 'OPENAI_API_KEY',
                    'anthropic': 'ANTHROPIC_API_KEY',
                    'openrouter': 'OPENROUTER_API_KEY',
                    'tokenra': 'TOKENRA_API_KEY',
                }
                env_key = key_map.get(provider, '')
                if not env_key:
                    self._send_json({'error': f'Unknown provider: {provider}'}, 400)
                    return
                # Append/update .env file
                env_path = os.path.join(os.path.dirname(__file__), '.env')
                lines = []
                found = False
                if os.path.exists(env_path):
                    with open(env_path, 'r') as f:
                        lines = f.readlines()
                for i, line in enumerate(lines):
                    if line.strip().startswith(f'{env_key}=') or line.strip().startswith(f'# {env_key}='):
                        lines[i] = f"{env_key}={key}\n"
                        found = True
                        break
                if not found:
                    lines.append(f"{env_key}={key}\n")
                with open(env_path, 'w') as f:
                    f.writelines(lines)
                print(f'[DASHBOARD] API key saved for {provider} -> {env_key}')
                self._send_json({'ok': True})
            except Exception as e:
                self._send_json({'error': str(e)}, 500)

        elif self.path == '/api/test-llm':
            body = self._read_body()
            try:
                import urllib.request as ur
                import urllib.error
                data = json.loads(body)
                provider = data.get('provider', 'ollama')
                api_key = data.get('api_key', '')
                model = data.get('model', '')

                # Quick test: send a minimal request to the provider
                if provider == 'ollama':
                    host = data.get('host', 'localhost')
                    port = data.get('port', '11434')
                    test_payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "Say OK"}], "stream": False, "think": False}).encode()
                    req = ur.Request(f"http://{host}:{port}/api/chat", data=test_payload, headers={"Content-Type": "application/json"})
                    try:
                        with ur.urlopen(req, timeout=10) as resp:
                            result = json.loads(resp.read().decode())
                            ok = bool(result.get("message", {}).get("content"))
                            self._send_json({"ok": ok, "message": "Ollama connection successful"})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)[:200]})
                elif provider == 'anthropic':
                    test_payload = json.dumps({"model": model, "max_tokens": 10, "messages": [{"role": "user", "content": "Say OK"}]}).encode()
                    req = ur.Request("https://api.anthropic.com/v1/messages", data=test_payload,
                                     headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"})
                    try:
                        with ur.urlopen(req, timeout=10) as resp:
                            self._send_json({"ok": True, "message": "Anthropic connection successful"})
                    except urllib.error.HTTPError as e:
                        self._send_json({"ok": False, "error": f"HTTP {e.code}: {e.reason}"})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)[:200]})
                else:
                    # OpenAI-compatible: openai, openrouter, tokenra
                    endpoints = {
                        'openai': 'https://api.openai.com/v1/chat/completions',
                        'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
                        'tokenra': 'https://api.tokenra.ai/v1/chat/completions',
                    }
                    endpoint = endpoints.get(provider, '')
                    if not endpoint:
                        self._send_json({"ok": False, "error": f"Unknown provider: {provider}"})
                        return
                    test_payload = json.dumps({"model": model, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 10}).encode()
                    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                    if provider == 'openrouter':
                        headers['HTTP-Referer'] = 'https://executivemind.io'
                        headers['X-Title'] = 'Armchair Test'
                    req = ur.Request(endpoint, data=test_payload, headers=headers)
                    try:
                        with ur.urlopen(req, timeout=10) as resp:
                            self._send_json({"ok": True, "message": f"{provider} connection successful"})
                    except urllib.error.HTTPError as e:
                        self._send_json({"ok": False, "error": f"HTTP {e.code}: {e.reason}"})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)[:200]})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif self.path == '/api/tts-prewarm':
            body = self._read_body()
            try:
                data = json.loads(body)
                engine = data.get('engine', '')
                if engine in ('piper', 'kokoro', 'chatterbox'):
                    with open(PREWARM_FILE, 'w') as f:
                        f.write(engine)
                    print(f'[DASHBOARD] TTS prewarm requested: {engine}')
                    self._send_json({'status': 'ok', 'prewarming': engine})
                else:
                    self._send_json({'error': 'unknown engine'}, 400)
            except Exception as e:
                self._send_json({'error': str(e)}, 500)

        else:
            self._send_json({'error': 'unknown endpoint'}, 404)


if __name__ == '__main__':
    os.makedirs('/tmp/armchair', exist_ok=True)
    if not os.path.exists(MODE_FILE):
        with open(MODE_FILE, 'w') as f:
            f.write('listen')
    if not os.path.exists(AGENT_CONFIG_FILE):
        with open(AGENT_CONFIG_FILE, 'w') as f:
            json.dump({
                'name': 'Agricola',
                'voice': 'en_GB-alan-medium',
                'llm_model': 'deepseek-v4-flash:cloud',
                'persona': 'You are {agent_name}, a strategic advisor. Speak only when directly addressed.'
            }, f)
    server = http.server.HTTPServer(('0.0.0.0', 8765), ArmchairHandler)
    print('[DASHBOARD] Agent In The Armchair on http://localhost:8765')
    print('[DASHBOARD] Mode: listen / talk')
    print('[DASHBOARD] Speaker naming and agent config via API')
    server.serve_forever()