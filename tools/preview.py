#!/usr/bin/env python3
"""Loopback preview: exact public HTML/snapshot routes only; no source/cache exposure."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import argparse

ROOT = Path(__file__).absolute().parent.parent
ROUTES = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/mailbox-snapshot.json': ('mailbox-snapshot.json', 'application/json'),
          '/muse-grok-collaboration-monitor/': ('index.html', 'text/html; charset=utf-8'),
          '/muse-grok-collaboration-monitor/mailbox-snapshot.json': ('mailbox-snapshot.json', 'application/json')}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ROUTES:
            self.send_error(404)
            return
        name, media = ROUTES[self.path]
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            self.send_error(503)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_):
        pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=37574)
    args = parser.parse_args()
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    print('Loopback preview ready', flush=True)
    server.serve_forever()
