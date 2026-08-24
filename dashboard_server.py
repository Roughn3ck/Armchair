#!/usr/bin/env python3
"""Agent In The Armchair — Dashboard server (VTT + AI Agent)"""
import http.server
import json
import os
import time

TRANSCRIPT = '/tmp/armchair/transcript.txt'
LATENCY_FILE = '/tmp/armchair/latency.txt'
MODE_FILE = '/tmp/armchair/mode.txt'
SPEAKER_NAMES_FILE = '/tmp/armchair/speaker_names.json'
DETECTED_SPEAKERS_FILE = '/tmp/armchair/detected_speakers.json'
AGENT_CONFIG_FILE = '/tmp/armchair/agent_config.json'


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
            with open(os.path.join(os.path.dirname(__file__), 'dashboard.html'), 'rb') as f:
                self.wfile.write(f.read())
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
                'llm_model': 'deepseek-v3.2:cloud',
                'persona': 'You are {agent_name}, a strategic advisor. Speak only when directly addressed.'
            }, f)
    server = http.server.HTTPServer(('0.0.0.0', 8765), ArmchairHandler)
    print('[DASHBOARD] Agent In The Armchair on http://localhost:8765')
    print('[DASHBOARD] Mode: listen / talk')
    print('[DASHBOARD] Speaker naming and agent config via API')
    server.serve_forever()