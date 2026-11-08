"""Falcón Live Ratings API.

Función Python de Vercel servida en /api.
Toda la administración pasa por aquí; el navegador nunca ve la clave de Supabase.
"""

import hmac
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine import live as live_engine  # noqa: E402
from engine import state as st  # noqa: E402
from engine import tournaments as tm  # noqa: E402
from server import store  # noqa: E402

SERVICE = "falcon-live-ratings-api"
VERSION = "0.3.0"
MAX_BODY = 6_000_000


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class AuthError(ApiError):
    def __init__(self, message="Sesión no válida"):
        super().__init__(message, 401)


def _ensure_ids(state):
    ids = state.setdefault("next_ids", {})

    def max_id(items):
        return max([int(x.get("id", 0)) for x in items], default=0)

    ids["player"] = max(int(ids.get("player", 1) or 1), max_id(state.get("players", [])) + 1)
    ids["tournament"] = max(int(ids.get("tournament", 1) or 1), max_id(state.get("tournaments", [])) + 1)
    games = [g for t in state.get("tournaments", []) for g in t.get("games", [])]
    ids["game"] = max(int(ids.get("game", 1) or 1), max_id(games) + 1)
    ids["match"] = max(int(ids.get("match", 1) or 1), max_id(state.get("matches", [])) + 1)


def _dashboard(state, version):
    tournaments = state.get("tournaments", [])
    current = max(tournaments, key=lambda t: int(t["id"])) if tournaments else None
    players = {int(p["id"]): p for p in state.get("players", [])}
    matches = sorted(
        state.get("matches", []),
        key=lambda m: (str(m.get("fecha") or ""), int(m.get("id") or 0)),
        reverse=True,
    )[:20]
    return {
        "version": int(version),
        "players": state.get("players", []),
        "matches": [
            {
                "id": int(m.get("id") or 0),
                "ritmo": m.get("ritmo", ""),
                "fecha": m.get("fecha"),
                "np": int(m.get("n_partidas") or 0),
                "p1": (players.get(int(m.get("jugador1_id", -1))) or {}).get("name", "?"),
                "p2": (players.get(int(m.get("jugador2_id", -1))) or {}).get("name", "?"),
                "score1": float(m.get("score_p1") or 0.0),
                "score2": float(m.get("score_p2") or 0.0),
                "var1": int(round(float(m.get("var_p1") or 0))),
                "var2": int(round(float(m.get("var_p2") or 0))),
            }
            for m in matches
        ],
        "tournaments": [
            {
                "id": int(t["id"]),
                "name": t.get("name", ""),
                "type": int(t.get("type", 1)),
                "rhythm": t.get("rhythm", ""),
                "rounds_total": int(t.get("rounds_total") or 0),
                "round_current": int(t.get("round_current") or 1),
                "finished": bool(t.get("finished")),
                "date_start": t.get("date_start"),
            }
            for t in sorted(tournaments, key=lambda x: int(x["id"]), reverse=True)
        ],
        "current": tm.tournament_payload(state, current) if current else None,
    }


class handler(BaseHTTPRequestHandler):
    # ── HTTP helpers ────────────────────────────────────────────────
    def _json(self, code, payload, cache="no-store"):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError("Content-Length inválido")
        if length > MAX_BODY:
            raise ApiError("El cuerpo es demasiado grande", 413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError("JSON inválido")
        if not isinstance(data, dict):
            raise ApiError("Se esperaba un objeto JSON")
        return data

    def _token(self, body):
        return str(self.headers.get("x-token") or (body or {}).get("token") or "").strip()

    def _auth(self, body):
        token = self._token(body)
        if not token:
            raise AuthError("Falta el token de administración")
        session = store.get_session(token)
        if not store.session_is_valid(session):
            raise AuthError()
        try:
            store.touch_session(token)
        except store.StoreError:
            pass
        return token

    def _load(self):
        row = store.get_state_row()
        state = row.get("state") or {}
        if not isinstance(state, dict):
            state = st.new_state()
        state.setdefault("schema", 1)
        state.setdefault("players", [])
        state.setdefault("tournaments", [])
        state.setdefault("matches", [])
        state.setdefault("ranking_snapshot", {})
        _ensure_ids(state)
        return state, row.get("live") or {}, int(row.get("version") or 1)

    def _commit(self, state, version):
        live = live_engine.build_live(state)
        state["ranking_snapshot"] = live_engine.new_ranking_snapshot(state, live)
        row = store.save_state_row(state, live, version)
        return int(row.get("version") or (int(version) + 1)), live

    # ── Acciones públicas ───────────────────────────────────────────
    def _ping(self):
        return self._json(200, {"ok": True, "service": SERVICE, "version": VERSION})

    def _dbcheck(self):
        row = store.get_state_meta()
        return self._json(200, {
            "ok": True,
            "row": {
                "id": "main",
                "version": row.get("version"),
                "updated_at": row.get("updated_at"),
            },
        })

    def _live(self):
        live = store.get_live()
        return self._json(
            200, live,
            cache="public, max-age=0, s-maxage=10, stale-while-revalidate=30",
        )

    def _status(self):
        admin = store.get_admin()
        return self._json(200, {"configured": bool(admin), "service": SERVICE, "version": VERSION})

    # ── Autenticación ───────────────────────────────────────────────
    def _setup(self, body):
        if store.get_admin():
            raise ApiError("Ya existe un administrador", 409)
        expected = (os.environ.get("SETUP_TOKEN") or "").strip()
        if not expected:
            raise ApiError("Configura SETUP_TOKEN en Vercel para el primer arranque", 503)
        if not hmac.compare_digest(str(body.get("setup_token") or ""), expected):
            raise AuthError("Token de configuración incorrecto")
        pin = str(body.get("pin") or "")
        if len(pin) < 4:
            raise ApiError("El PIN debe tener al menos 4 caracteres")
        if len(pin) > 128:
            raise ApiError("El PIN es demasiado largo")
        store.create_admin(pin, body.get("name") or "Administrador")
        return self._json(200, {"ok": True})

    def _login(self, body):
        admin = store.get_admin()
        if not admin:
            raise ApiError("Falta configurar el PIN inicial", 409)
        fallos = store.count_recent_failures()
        if fallos >= store.MAX_FAILED_LOGINS:
            raise ApiError("Demasiados intentos. Espera 15 minutos.", 429)
        pin = str(body.get("pin") or "")
        if not store.verify_pin(pin, admin["pin_salt"], admin["pin_hash"]):
            store.add_failed_login()
            quedan = store.MAX_FAILED_LOGINS - (fallos + 1)
            mensaje = (
                f"PIN incorrecto. Te quedan {quedan} intentos"
                if quedan > 0 else "Cuenta bloqueada 15 minutos"
            )
            raise AuthError(mensaje)
        store.clear_logins()
        token = store.new_token()
        store.create_session(token)
        return self._json(200, {"token": token, "name": admin.get("name") or "Administrador"})

    def _logout(self, body):
        token = self._auth(body)
        store.delete_session(token)
        return self._json(200, {"ok": True})

    # ── Acciones de administración ──────────────────────────────────
    def _dashboard_action(self, body):
        self._auth(body)
        state, _, version = self._load()
        return self._json(200, _dashboard(state, version))

    def _state_action(self, body):
        self._auth(body)
        state, _, version = self._load()
        return self._json(200, {"version": version, "state": state})

    def _import_seed(self, body):
        self._auth(body)
        seed = body.get("seed")
        if not isinstance(seed, dict):
            raise ApiError("Falta el estado a importar")
        if not isinstance(seed.get("players"), list) or not isinstance(seed.get("tournaments"), list):
            raise ApiError("El estado no tiene players/tournaments válidos")
        state, _, version = self._load()
        if (state.get("players") or state.get("tournaments")) and not body.get("force"):
            raise ApiError("Ya hay datos. Envía force=true para reemplazarlos", 409)
        new_state = dict(seed)
        new_state.pop("live", None)
        new_state.setdefault("schema", 1)
        new_state.setdefault("players", [])
        new_state.setdefault("tournaments", [])
        new_state.setdefault("matches", [])
        new_state["ranking_snapshot"] = {}
        _ensure_ids(new_state)
        version, _ = self._commit(new_state, version)
        payload = _dashboard(new_state, version)
        payload["imported"] = {
            "players": len(new_state["players"]),
            "tournaments": len(new_state["tournaments"]),
        }
        return self._json(200, payload)

    def _player_create(self, body):
        self._auth(body)
        state, _, version = self._load()
        player = tm.create_player(
            state,
            body.get("name"),
            body.get("mun"),
            body.get("cat"),
            body.get("foto_url"),
        )
        version, _ = self._commit(state, version)
        return self._json(200, {"player": player, "dashboard": _dashboard(state, version)})

    def _player_update(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            player_id = int(body.get("player_id"))
        except (TypeError, ValueError):
            raise ApiError("Falta player_id")
        player = tm.update_player(state, player_id, body)
        version, _ = self._commit(state, version)
        return self._json(200, {"player": player, "dashboard": _dashboard(state, version)})

    def _tournament_create(self, body):
        self._auth(body)
        state, _, version = self._load()
        tournament = tm.create_tournament(
            state,
            body.get("name"),
            body.get("type"),
            body.get("rhythm"),
            body.get("rounds_total"),
            body.get("player_ids"),
        )
        version, _ = self._commit(state, version)
        return self._json(200, {
            "tournament": {
                "id": int(tournament["id"]),
                "name": tournament["name"],
                "type": int(tournament["type"]),
                "rhythm": tournament["rhythm"],
                "rounds_total": int(tournament["rounds_total"]),
            },
            "dashboard": _dashboard(state, version),
        })

    def _round_pair(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            tournament_id = int(body.get("tournament_id"))
        except (TypeError, ValueError):
            raise ApiError("Falta tournament_id")
        pairing = tm.pair_next_round(state, tournament_id)
        version, _ = self._commit(state, version)
        return self._json(200, {"pairing": pairing, "dashboard": _dashboard(state, version)})

    def _result_save(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            tournament_id = int(body.get("tournament_id"))
        except (TypeError, ValueError):
            raise ApiError("Falta tournament_id")
        tm.save_results(state, tournament_id, body.get("results") or [])
        version, _ = self._commit(state, version)
        return self._json(200, {"dashboard": _dashboard(state, version)})

    def _player_withdraw(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            tournament_id = int(body.get("tournament_id"))
            player_id = int(body.get("player_id"))
        except (TypeError, ValueError):
            raise ApiError("Faltan tournament_id o player_id")
        tm.withdraw_player(state, tournament_id, player_id)
        version, _ = self._commit(state, version)
        return self._json(200, {"dashboard": _dashboard(state, version)})

    def _tournament_close(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            tournament_id = int(body.get("tournament_id"))
        except (TypeError, ValueError):
            raise ApiError("Falta tournament_id")
        tm.close_tournament(state, tournament_id)
        version, _ = self._commit(state, version)
        return self._json(200, {"dashboard": _dashboard(state, version)})

    def _tournament_delete(self, body):
        self._auth(body)
        if not body.get("confirm"):
            raise ApiError("Falta confirmación para eliminar", 400)
        state, _, version = self._load()
        try:
            tournament_id = int(body.get("tournament_id"))
        except (TypeError, ValueError):
            raise ApiError("Falta tournament_id")
        tournament = tm.delete_tournament(state, tournament_id)
        version, _ = self._commit(state, version)
        return self._json(200, {
            "deleted": {"id": int(tournament["id"]), "name": tournament.get("name", "")},
            "dashboard": _dashboard(state, version),
        })

    def _match_create(self, body):
        self._auth(body)
        state, _, version = self._load()
        try:
            p1 = int(body.get("player1_id"))
            p2 = int(body.get("player2_id"))
        except (TypeError, ValueError):
            raise ApiError("Faltan los jugadores")
        match = tm.create_match(state, p1, p2, body.get("rhythm"), body.get("results") or [])
        version, _ = self._commit(state, version)
        return self._json(200, {"match": match, "dashboard": _dashboard(state, version)})

    def _pin_change(self, body):
        self._auth(body)
        admin = store.get_admin()
        if not admin:
            raise ApiError("No hay administrador", 404)
        if not store.verify_pin(str(body.get("current_pin") or ""), admin["pin_salt"], admin["pin_hash"]):
            raise AuthError("El PIN actual no es correcto")
        new_pin = str(body.get("new_pin") or "")
        if len(new_pin) < 4:
            raise ApiError("El PIN nuevo debe tener al menos 4 caracteres")
        store.update_admin_pin(new_pin)
        return self._json(200, {"ok": True})

    # ── Router ──────────────────────────────────────────────────────
    def _route_get(self, action):
        if action == "ping":
            return self._ping()
        if action == "dbcheck":
            return self._dbcheck()
        if action == "live":
            return self._live()
        if action == "status":
            return self._status()
        if action == "dashboard":
            return self._dashboard_action({})
        if action == "state":
            return self._state_action({})
        raise ApiError("Acción no reconocida", 404)

    def _route_post(self, body):
        action = str(body.get("action") or "")
        if action == "ping":
            return self._ping()
        if action == "dbcheck":
            return self._dbcheck()
        if action == "live":
            return self._live()
        if action == "setup":
            return self._setup(body)
        if action == "login":
            return self._login(body)
        if action == "logout":
            return self._logout(body)

        # A partir de aquí, todo exige sesión.
        self._auth(body)
        if action == "dashboard":
            return self._dashboard_action(body)
        if action == "state":
            return self._state_action(body)
        if action == "tournament_get":
            state, _, _ = self._load()
            try:
                tournament_id = int(body.get("tournament_id"))
            except (TypeError, ValueError):
                raise ApiError("Falta tournament_id")
            tournament = tm.tournament_by_id(state, tournament_id)
            if not tournament:
                raise ApiError("Torneo no encontrado", 404)
            return self._json(200, {"tournament": tm.tournament_payload(state, tournament)})
        if action == "import_seed":
            return self._import_seed(body)
        if action == "player_create":
            return self._player_create(body)
        if action == "player_update":
            return self._player_update(body)
        if action == "tournament_create":
            return self._tournament_create(body)
        if action == "round_pair":
            return self._round_pair(body)
        if action == "result_save":
            return self._result_save(body)
        if action == "player_withdraw":
            return self._player_withdraw(body)
        if action == "tournament_close":
            return self._tournament_close(body)
        if action == "tournament_delete":
            return self._tournament_delete(body)
        if action == "match_create":
            return self._match_create(body)
        if action == "pin_change":
            return self._pin_change(body)
        raise ApiError("Acción no reconocida", 404)

    # ── Puntos de entrada HTTP ──────────────────────────────────────
    def _handle(self, fn):
        try:
            return fn()
        except tm.PendingResults as exc:
            return self._json(409, {"error": str(exc), "pending": exc.games})
        except tm.TournamentError as exc:
            return self._json(400, {"error": str(exc)})
        except store.Conflict as exc:
            return self._json(409, {"error": str(exc)})
        except store.StoreError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except AuthError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except ApiError as exc:
            return self._json(exc.status, {"error": str(exc)})
        except Exception:
            traceback.print_exc()
            return self._json(500, {"error": "Error interno del servidor"})

    def do_GET(self):
        def run():
            query = parse_qs(urlparse(self.path).query)
            action = (query.get("action") or ["ping"])[0]
            return self._route_get(action)
        return self._handle(run)

    def do_POST(self):
        def run():
            body = self._body()
            return self._route_post(body)
        return self._handle(run)

    def do_HEAD(self):
        query = parse_qs(urlparse(self.path).query)
        action = (query.get("action") or ["ping"])[0]
        code = 200 if action in ("ping", "status", "dbcheck", "live") else 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "public, max-age=0" if action == "live" else "no-store")
        self.end_headers()

    def log_message(self, *args):
        pass
