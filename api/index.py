"""Falcón Live Ratings API.

Función Python de Vercel servida en /api.
Acciones actuales: ping y dbcheck (conexión con Supabase).
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse, parse_qs

SERVICE = "falcon-live-ratings-api"
VERSION = "0.2.0"


def _supabase_request(path, method="GET", body=None):
    """Llamada mínima a PostgREST. La clave nunca sale en la respuesta."""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not base or not key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en Vercel")

    data = None
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8") or "null"
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:300]
        return e.code, {"error": raw}


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

    def _dbcheck(self):
        try:
            status, rows = _supabase_request(
                "/rest/v1/falcon_state?id=eq.main&select=id,version,updated_at"
            )
        except RuntimeError as e:
            return self._json(503, {"ok": False, "error": str(e)})
        except Exception as e:
            return self._json(502, {
                "ok": False,
                "error": "No se pudo conectar con Supabase",
                "detail": str(e)[:200],
            })
        if status != 200:
            return self._json(502, {"ok": False, "status": status, "error": rows})
        row = rows[0] if isinstance(rows, list) and rows else None
        return self._json(200, {"ok": True, "table": "falcon_state", "row": row})

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        action = (query.get("action") or ["ping"])[0]
        if action == "ping":
            return self._json(200, self._ping())
        if action == "dbcheck":
            return self._dbcheck()
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
        if action == "dbcheck":
            return self._dbcheck()
        return self._json(404, {"error": "accion no reconocida", "action": action})

    def log_message(self, *args):
        pass
