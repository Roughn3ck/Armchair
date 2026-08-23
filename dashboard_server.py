#!/usr/bin/env python3
"""Agent In The Armchair — Dashboard server (VTT only)"""
import http.server
import json
import os
import time

TRANSCRIPT = '/tmp/armchair/transcript.txt'
LATENCY_FILE = '/tmp/armchair/latency.txt'


class ArmchairHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress access logs

    def do_GET(self):
        if self.path == '/api/status':
            transcript = ''
            latency = ''
            try:
                with open(TRANSCRIPT, 'r') as f:
                    transcript = f.read()
            except:
                pass
            try:
                with open(LATENCY_FILE, 'r') as f:
                    latency = f.read().strip()
            except:
                pass

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                'transcript': transcript,
                'latency': latency,
                'time': time.strftime('%H:%M:%S')
            }).encode())
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), 'dashboard.html'), 'rb') as f:
                self.wfile.write(f.read())
        else:
            super().do_GET()


if __name__ == '__main__':
    os.makedirs('/tmp/armchair', exist_ok=True)
    server = http.server.HTTPServer(('0.0.0.0', 8765), ArmchairHandler)
    print('[DASHBOARD] Agent In The Armchair on http://localhost:8765')
    print('[DASHBOARD] VTT mode — live transcription only')
    server.serve_forever()