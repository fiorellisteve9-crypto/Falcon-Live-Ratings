"""Acceso a Supabase (PostgREST) y utilidades de autenticación.

La clave `service_role` vive solo en las variables de entorno de Vercel.
Este módulo nunca la devuelve al navegador.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 210_000
SESSION_DAYS = 30
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


class StoreError(Exception):
    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status


class Conflict(StoreError):
    def __init__(self, message="Otra sesión cambió los datos. Recarga e inténtalo de nuevo."):
        super().__init__(message, 409)


def _env(name):
    return (os.environ.get(name) or "").strip()


def _base_url():
    url = _env("SUPABASE_URL")
    if not url:
        raise StoreError("Falta SUPABASE_URL en Vercel", 503)
    return url.rstrip("/")


def _key():
    key = _env("SUPABASE_KEY")
    if not key:
        raise StoreError("Falta SUPABASE_KEY en Vercel", 503)
    return key


def request(path, method="GET", body=None, prefer=None, timeout=25):
    url = _base_url() + path
    key = _key()
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "null"
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = raw[:500]
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise StoreError(f"No se pudo conectar con Supabase: {exc.reason}", 502)


# ── Estado ──────────────────────────────────────────────────────────

def get_state_row():
    status, data = request(
        "/rest/v1/falcon_state?id=eq.main&select=state,version,updated_at"
    )
    if status != 200:
        raise StoreError("No se pudo leer falcon_state", 502)
    if not data:
        raise StoreError("Falta la fila 'main' en falcon_state. Ejecuta supabase.sql", 503)
    return data[0]


def get_live():
    status, data = request("/rest/v1/falcon_state?id=eq.main&select=live")
    if status != 200:
        raise StoreError("No se pudo leer el snapshot público", 502)
    if not data:
        return {}
    return data[0].get("live") or {}


def save_state_row(state, live, version):
    body = {
        "state": state,
        "live": live,
        "version": int(version) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    status, data = request(
        f"/rest/v1/falcon_state?id=eq.main&version=eq.{int(version)}",
        method="PATCH",
        body=body,
        prefer="return=representation",
    )
    if status in (200, 201) and isinstance(data, list) and data:
        return data[0]
    if status in (200, 204) and (not data or data == []):
        raise Conflict()
    if status == 404:
        raise Conflict()
    raise StoreError("No se pudo guardar falcon_state", 502)


# ── Administrador y sesiones ────────────────────────────────────────

def hash_pin(pin, salt):
    dk = hashlib.pbkdf2_hmac(
        "sha512", str(pin).encode("utf-8"), str(salt).encode("utf-8"), PBKDF2_ITERATIONS
    )
    return dk.hex()


def verify_pin(pin, salt, expected):
    return hmac.compare_digest(hash_pin(pin, salt), str(expected))


def get_admin():
    status, data = request("/rest/v1/admin?id=eq.main&select=name,pin_hash,pin_salt")
    if status != 200:
        raise StoreError("No se pudo leer el administrador", 502)
    return data[0] if data else None


def create_admin(pin, name="Administrador"):
    salt = secrets.token_hex(16)
    body = {
        "id": "main",
        "name": str(name or "Administrador").strip() or "Administrador",
        "pin_hash": hash_pin(pin, salt),
        "pin_salt": salt,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    status, data = request(
        "/rest/v1/admin",
        method="POST",
        body=body,
        prefer="return=representation",
    )
    if status not in (200, 201):
        raise StoreError("Ya existe un administrador", 409)
    return data[0] if isinstance(data, list) and data else body


def update_admin_pin(pin):
    admin = get_admin()
    if not admin:
        raise StoreError("No hay administrador", 404)
    salt = secrets.token_hex(16)
    status, data = request(
        "/rest/v1/admin?id=eq.main",
        method="PATCH",
        body={"pin_hash": hash_pin(pin, salt), "pin_salt": salt,
              "updated_at": datetime.now(timezone.utc).isoformat()},
        prefer="return=minimal",
    )
    if status not in (200, 204):
        raise StoreError("No se pudo cambiar el PIN", 502)


def new_token():
    return secrets.token_urlsafe(32)


def create_session(token):
    now = datetime.now(timezone.utc).isoformat()
    status, _ = request(
        "/rest/v1/sessions",
        method="POST",
        body={"token": token, "created_at": now, "last_seen": now},
        prefer="return=minimal",
    )
    if status not in (200, 201, 204):
        raise StoreError("No se pudo crear la sesión", 502)


def get_session(token):
    if not token:
        return None
    q = urllib.parse.quote(str(token), safe="")
    status, data = request(f"/rest/v1/sessions?token=eq.{q}&select=token,last_seen")
    if status != 200:
        return None
    return data[0] if data else None


def touch_session(token):
    q = urllib.parse.quote(str(token), safe="")
    request(
        f"/rest/v1/sessions?token=eq.{q}",
        method="PATCH",
        body={"last_seen": datetime.now(timezone.utc).isoformat()},
        prefer="return=minimal",
    )


def delete_session(token):
    q = urllib.parse.quote(str(token), safe="")
    request(f"/rest/v1/sessions?token=eq.{q}", method="DELETE", prefer="return=minimal")


def session_is_valid(session):
    if not session:
        return False
    try:
        seen = datetime.fromisoformat(str(session.get("last_seen")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - seen < timedelta(days=SESSION_DAYS)


# ── Intentos de entrada ─────────────────────────────────────────────

def count_recent_failures(minutes=LOCK_MINUTES):
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    status, data = request(
        "/rest/v1/logins?ok=eq.false&at=gte." + urllib.parse.quote(since, safe="") + "&select=id"
    )
    if status != 200:
        return 0
    return len(data or [])


def add_failed_login():
    request(
        "/rest/v1/logins",
        method="POST",
        body={"ok": False, "at": datetime.now(timezone.utc).isoformat()},
        prefer="return=minimal",
    )


def clear_logins():
    request("/rest/v1/logins?ok=eq.false", method="DELETE", prefer="return=minimal")
