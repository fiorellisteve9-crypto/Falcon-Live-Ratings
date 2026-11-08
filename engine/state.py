"""Estado del club y operaciones sobre el JSON almacenado en Supabase.

El estado completo vive en `falcon_state.state` (JSONB). Aquí no hay SQL:
solo diccionarios y las funciones puras de `engine.core`.

Esquema (resumen):

state = {
  "schema": 1,
  "players": [
    {"id": 1, "name": "...", "ratings": {"Rapid": {...}, "Blitz": {...}, "Bullet": {...}},
     "mun": "-", "cat": "-", "foto_url": null}
  ],
  "tournaments": [
    {"id": 1, "name": "...", "type": 1, "rhythm": "Rapid",
     "rounds_total": 5, "round_current": 5, "finished": true,
     "date_start": "...", "date_end": "...",
     "participants": [
       {"player_id": 1, "points": 0.0, "color_history": "", "withdrawn": 0,
        "rating_start": 1500.0, "rd_start": 500.0, "sigma_start": 0.09,
        "variation_total": null}
     ],
     "games": [
       {"id": 1, "round": 1, "white_id": 1, "black_id": 2, "result": 1.0,
        "bye": 0, "date": "...", "var_white": null, "var_black": null}
     ],
     "snapshots": []
    }
  ],
  "matches": [ ... ],
  "next_ids": {"player": 21, "tournament": 10, "game": 134, "match": 16}
}
"""

from __future__ import annotations

from datetime import datetime

from . import core

RHYTHMS = ("Rapid", "Blitz", "Bullet")


def new_state():
    return {
        "schema": 1,
        "players": [],
        "tournaments": [],
        "matches": [],
        "next_ids": {"player": 1, "tournament": 1, "game": 1, "match": 1},
    }


def player_index(state):
    return {int(p["id"]): p for p in state.get("players", [])}


def tournament_index(state):
    return {int(t["id"]): t for t in state.get("tournaments", [])}


def participant_index(tournament):
    return {int(p["player_id"]): p for p in tournament.get("participants", [])}


def game_index(tournament):
    return {int(g["id"]): g for g in tournament.get("games", [])}


def _rating_slot(player, rhythm):
    ratings = player.setdefault("ratings", {})
    slot = ratings.setdefault(rhythm, {})
    slot.setdefault("rating", core.DEFAULT_RATING)
    slot.setdefault("rd", core.DEFAULT_RD)
    slot.setdefault("sigma", core.DEFAULT_SIGMA)
    slot.setdefault("var", 0)
    slot.setdefault("last", None)
    return slot


def build_players_dict(state, tournament, round_until=None, rating_mode="current"):
    """Construye el dict que espera `engine.core` para un torneo.

    rating_mode:
      - "current": rating actual del jugador (lo que usa el CLI mientras se juega).
      - "tournament_end": rating_start + variacion_total (para tablas históricas).
      - "tournament_start": rating_start.
    """
    players = player_index(state)
    p_index = participant_index(tournament)
    rhythm = tournament["rhythm"]
    games = [g for g in tournament.get("games", []) if g.get("result") is not None]
    if round_until is not None:
        games = [g for g in games if int(g["round"]) <= int(round_until)]
    games.sort(key=lambda g: (int(g["round"]), int(g["id"])))

    jugadores = {}
    for pid, part in p_index.items():
        player = players.get(pid)
        if not player:
            continue
        slot = _rating_slot(player, rhythm)
        if rating_mode == "tournament_end":
            rating = float(part.get("rating_start", core.DEFAULT_RATING)) + float(part.get("variation_total") or 0.0)
        elif rating_mode == "tournament_start":
            rating = float(part.get("rating_start", core.DEFAULT_RATING))
        else:
            rating = float(slot.get("rating", core.DEFAULT_RATING))
        jugadores[player["name"]] = {
            "id": pid,
            "puntos": 0.0,
            "rating": rating,
            "rd": float(slot.get("rd", core.DEFAULT_RD)),
            "sigma": float(slot.get("sigma", core.DEFAULT_SIGMA)),
            "historial": [],
            "colores": [],
            "enfrentamientos": {},
            "retirado": int(part.get("withdrawn") or 0),
            "mun": player.get("mun") or "-",
            "cat": player.get("cat") or "-",
        }

    id_to_name = {v["id"]: n for n, v in jugadores.items()}
    for game in games:
        white_id = game.get("white_id")
        black_id = game.get("black_id")
        if game.get("bye") or black_id is None:
            name = id_to_name.get(white_id)
            if name:
                jugadores[name]["historial"].append("BYE")
                jugadores[name]["colores"].append("-")
                jugadores[name]["puntos"] += 1.0
            continue
        white = id_to_name.get(white_id)
        black = id_to_name.get(black_id)
        if not white or not black:
            continue
        result = float(game["result"])
        jugadores[white]["historial"].append(black)
        jugadores[black]["historial"].append(white)
        jugadores[white]["colores"].append("B")
        jugadores[black]["colores"].append("N")
        jugadores[white]["enfrentamientos"].setdefault(black, []).append(result)
        jugadores[black]["enfrentamientos"].setdefault(white, []).append(1.0 - result)
        jugadores[white]["puntos"] += result
        jugadores[black]["puntos"] += 1.0 - result

    return jugadores


def _event_dates(state, player_id, rhythm):
    """Fechas de torneos y matches del jugador en un ritmo."""
    out = []
    for t in state.get("tournaments", []):
        if t.get("rhythm") != rhythm:
            continue
        if any(int(p["player_id"]) == int(player_id) for p in t.get("participants", [])):
            if t.get("date_start"):
                out.append((str(t["date_start"]), int(t["id"])))
    for m in state.get("matches", []):
        if m.get("rhythm") != rhythm:
            continue
        if int(m.get("player1_id", -1)) == int(player_id) or int(m.get("player2_id", -1)) == int(player_id):
            if m.get("date"):
                out.append((str(m["date"]), None))
    return out


def last_activity_before(state, player_id, rhythm, date, current_tournament_id=None):
    """Última actividad estrictamente anterior a `date` (ISO), o None."""
    date = str(date) if date else ""
    candidates = []
    for d, tid in _event_dates(state, player_id, rhythm):
        if current_tournament_id is not None and tid == int(current_tournament_id):
            continue
        if d < date:
            candidates.append(d)
    return max(candidates) if candidates else None


def recompute_ratings(state, tournament, round_until=None, persist=True):
    """Recalcula Glicko-2 de un torneo desde sus ratings iniciales.

    Replica `_procesar_rating_torneo_impl` del motor original:
    - aplica la decadencia de RD desde la última actividad hasta el torneo,
    - procesa las partidas en orden (ronda, id) de forma pairwise,
    - guarda variación por partida y variación total por jugador.

    Devuelve {player_id: variacion_total}.
    """
    players = player_index(state)
    p_index = participant_index(tournament)
    g_index = game_index(tournament)
    rhythm = tournament["rhythm"]
    date = tournament.get("date_start") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    estado = {}
    rating_inicial = {}
    for pid, part in p_index.items():
        r0 = float(part.get("rating_start", core.DEFAULT_RATING))
        rd0 = float(part.get("rd_start", core.DEFAULT_RD))
        s0 = float(part.get("sigma_start", core.DEFAULT_SIGMA))
        player = players.get(pid)
        slot = _rating_slot(player, rhythm) if player else {}
        last = slot.get("last")
        elapsed = core.elapsed_rating_periods(last, date)
        base_rd = core.convert_rd_to_original_scale(
            core.calculate_new_rd(core.convert_rd_to_glicko2_scale(rd0), s0, elapsed)
        )
        estado[pid] = {"rating": r0, "rd": base_rd, "sigma": s0}
        rating_inicial[pid] = r0

    games = [
        g for g in tournament.get("games", [])
        if not g.get("bye") and g.get("result") is not None
        and g.get("white_id") is not None and g.get("black_id") is not None
    ]
    if round_until is not None:
        games = [g for g in games if int(g["round"]) <= int(round_until)]
    games.sort(key=lambda g: (int(g["round"]), int(g["id"])))

    variaciones_partida = {}
    for game in games:
        b_id = int(game["white_id"])
        n_id = int(game["black_id"])
        if b_id not in estado or n_id not in estado:
            continue
        b = estado[b_id]
        n = estado[n_id]
        score_b = float(game["result"])
        score_n = 1.0 - score_b
        new_b = core.glicko2_update(
            b["rating"], b["rd"], b["sigma"],
            [(n["rating"], n["rd"], score_b)], elapsed_rating_periods=0.0,
        )
        new_n = core.glicko2_update(
            n["rating"], n["rd"], n["sigma"],
            [(b["rating"], b["rd"], score_n)], elapsed_rating_periods=0.0,
        )
        variaciones_partida[int(game["id"])] = (new_b[0] - b["rating"], new_n[0] - n["rating"])
        estado[b_id] = {"rating": new_b[0], "rd": new_b[1], "sigma": new_b[2]}
        estado[n_id] = {"rating": new_n[0], "rd": new_n[1], "sigma": new_n[2]}

    variaciones = {
        pid: int(round(estado[pid]["rating"] - rating_inicial[pid]))
        for pid in estado
    }

    if persist:
        for pid, var_total in variaciones.items():
            part = p_index.get(pid)
            if part is not None:
                part["variation_total"] = var_total
        for gid, (vb, vn) in variaciones_partida.items():
            game = g_index.get(gid)
            if game is not None:
                game["var_white"] = vb
                game["var_black"] = vn
        for pid, vals in estado.items():
            player = players.get(pid)
            if not player:
                continue
            slot = _rating_slot(player, rhythm)
            slot["rating"] = vals["rating"]
            slot["rd"] = vals["rd"]
            slot["sigma"] = vals["sigma"]
            slot["var"] = variaciones[pid]
            slot["last"] = date

    return variaciones


def standings(state, tournament, round_until=None, rating_mode="current"):
    """Clasificación ordenada con los desempates del motor."""
    jugadores = build_players_dict(state, tournament, round_until=round_until, rating_mode=rating_mode)
    filas = [
        core.construir_fila_posiciones(name, data, jugadores, len(jugadores))
        for name, data in jugadores.items()
    ]
    tipo = core.TipoTorneo.desde_valor(int(tournament.get("type", 1)))
    return core.ordenar_tabla_posiciones(filas, tipo, tournament.get("rhythm", ""))


def current_tournament(state):
    tournaments = state.get("tournaments", [])
    return max(tournaments, key=lambda t: int(t["id"])) if tournaments else None


def next_id(state, kind):
    ids = state.setdefault("next_ids", {})
    value = int(ids.get(kind, 1))
    ids[kind] = value + 1
    return value
