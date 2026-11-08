"""Falcón Live Ratings API.

Función Python de Vercel servida en /api.
Por ahora solo responde a "ping" para comprobar el despliegue.
"""

from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import urlparse, parse_qs

SERVICE = "falcon-live-ratings-api"
VERSION = "0.1.0"


class handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _ping(self):
        return {"ok": True, "service": SERVICE, "version": VERSION}

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        action = (query.get("action") or ["ping"])[0]
        if action == "ping":
            return self._json(200, self._ping())
        return self._json(404, {"error": "accion no reconocida", "action": action})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
        except Exception:
            return self._json(400, {"error": "JSON invalido"})

        action = str(body.get("action") or "")
        if action == "ping":
            return self._json(200, self._ping())
        return self._json(404, {"error": "accion no reconocida", "action": action})

    def log_message(self, *args):
        pass
