"""Operaciones de dominio sobre el estado: jugadores y torneos.

No conoce HTTP ni Supabase: recibe el dict `state`, lo modifica y devuelve
resultados. La API se encarga de cargar/guardar y de reconstruir el JSON público.
"""

from __future__ import annotations

import math
from datetime import datetime

from . import core, state as st


class PendingResults(Exception):
    def __init__(self, games):
        self.games = games
        super().__init__("Hay partidas sin resultado en la ronda actual")


class TournamentError(Exception):
    pass


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def player_by_id(state, player_id):
    return next((p for p in state.get("players", []) if int(p["id"]) == int(player_id)), None)


def tournament_by_id(state, tournament_id):
    return next((t for t in state.get("tournaments", []) if int(t["id"]) == int(tournament_id)), None)


def participant(tournament, player_id):
    return next((p for p in tournament.get("participants", []) if int(p["player_id"]) == int(player_id)), None)


def _parse_result(value):
    if isinstance(value, str):
        value = value.strip()
        if value in ("1-0", "1", "blancas"):
            return 1.0
        if value in ("0-1", "0", "negras"):
            return 0.0
        if value in ("1/2", "0.5", "tablas"):
            return 0.5
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise TournamentError("Resultado inválido")
    if v not in (0.0, 0.5, 1.0):
        raise TournamentError("El resultado debe ser 1-0, 0-1 o 1/2")
    return v


def recompute_points(tournament):
    """Recalcula puntos e historial de colores desde las partidas."""
    for part in tournament.get("participants", []):
        part["points"] = 0.0
        part["color_history"] = ""
    for game in sorted(tournament.get("games", []), key=lambda g: (int(g["round"]), int(g["id"]))):
        if game.get("result") is None:
            continue
        if game.get("bye") or game.get("black_id") is None:
            part = participant(tournament, game["white_id"])
            if part:
                part["points"] = float(part.get("points") or 0.0) + 1.0
                part["color_history"] = str(part.get("color_history") or "") + "-"
            continue
        white = participant(tournament, game["white_id"])
        black = participant(tournament, game["black_id"])
        if not white or not black:
            continue
        res = float(game["result"])
        white["points"] = float(white.get("points") or 0.0) + res
        black["points"] = float(black.get("points") or 0.0) + (1.0 - res)
        white["color_history"] = str(white.get("color_history") or "") + "B"
        black["color_history"] = str(black.get("color_history") or "") + "N"


def create_player(state, name, mun="-", cat="-", foto_url=None):
    name = str(name or "").strip()
    if not name:
        raise TournamentError("El nombre es obligatorio")
    if any(str(p.get("name", "")).strip().lower() == name.lower() for p in state.get("players", [])):
        raise TournamentError("Ya existe un jugador con ese nombre")
    player = {
        "id": st.next_id(state, "player"),
        "name": name,
        "ratings": {
            rhythm: {"rating": core.DEFAULT_RATING, "rd": core.DEFAULT_RD,
                     "sigma": core.DEFAULT_SIGMA, "var": 0, "last": None}
            for rhythm in st.RHYTHMS
        },
        "mun": str(mun or "-").strip() or "-",
        "cat": str(cat or "-").strip() or "-",
        "foto_url": foto_url or None,
    }
    state.setdefault("players", []).append(player)
    return player


def update_player(state, player_id, fields):
    player = player_by_id(state, player_id)
    if not player:
        raise TournamentError("Jugador no encontrado")
    if "name" in fields:
        name = str(fields["name"] or "").strip()
        if not name:
            raise TournamentError("El nombre es obligatorio")
        if any(int(p["id"]) != int(player_id) and str(p.get("name", "")).lower() == name.lower()
               for p in state.get("players", [])):
            raise TournamentError("Ya existe otro jugador con ese nombre")
        player["name"] = name
    for key in ("mun", "cat", "foto_url"):
        if key in fields:
            value = fields[key]
            if key == "foto_url":
                player[key] = value or None
            else:
                player[key] = str(value or "-").strip() or "-"
    return player


def create_tournament(state, name, type_, rhythm, rounds_total=None, player_ids=None):
    name = str(name or "").strip()
    if not name:
        raise TournamentError("El nombre del torneo es obligatorio")
    try:
        type_ = int(type_)
    except (TypeError, ValueError):
        raise TournamentError("Sistema de juego inválido")
    if type_ not in (1, 2, 3):
        raise TournamentError("Sistema de juego inválido")
    rhythm = str(rhythm or "").strip()
    if rhythm not in st.RHYTHMS:
        raise TournamentError("Ritmo inválido")

    ids = []
    for raw in player_ids or []:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid not in ids:
            ids.append(pid)
    if len(ids) < 2:
        raise TournamentError("Se necesitan al menos 2 jugadores")
    players = []
    for pid in ids:
        player = player_by_id(state, pid)
        if not player:
            raise TournamentError(f"Jugador {pid} no encontrado")
        players.append(player)

    n = len(players)
    if type_ == 1:
        try:
            rounds = int(rounds_total) if rounds_total else max(1, math.ceil(math.log2(max(2, n))))
        except (TypeError, ValueError):
            rounds = max(1, math.ceil(math.log2(max(2, n))))
        rounds = max(1, min(99, rounds))
    elif type_ == 2:
        rounds = n - 1 if n % 2 == 0 else n
    else:
        rounds = (n - 1) * 2 if n % 2 == 0 else n * 2

    tournament = {
        "id": st.next_id(state, "tournament"),
        "name": name,
        "type": type_,
        "rhythm": rhythm,
        "rounds_total": rounds,
        "round_current": 1,
        "finished": False,
        "date_start": now_str(),
        "date_end": None,
        "participants": [],
        "games": [],
        "snapshots": [],
    }
    for player in players:
        slot = (player.get("ratings") or {}).get(rhythm) or {}
        tournament["participants"].append({
            "player_id": int(player["id"]),
            "points": 0.0,
            "color_history": "",
            "withdrawn": 0,
            "rating_start": float(slot.get("rating", core.DEFAULT_RATING)),
            "rd_start": float(slot.get("rd", core.DEFAULT_RD)),
            "sigma_start": float(slot.get("sigma", core.DEFAULT_SIGMA)),
            "variation_total": None,
        })
    state.setdefault("tournaments", []).append(tournament)
    return tournament


def _check_round_complete(tournament, round_number):
    pending = [
        g for g in tournament.get("games", [])
        if int(g["round"]) == int(round_number) and not g.get("bye") and g.get("result") is None
    ]
    if pending:
        raise PendingResults([int(g["id"]) for g in pending])


def pair_next_round(state, tournament_id):
    tournament = tournament_by_id(state, tournament_id)
    if not tournament:
        raise TournamentError("Torneo no encontrado")
    if tournament.get("finished"):
        raise TournamentError("El torneo ya está finalizado")

    current = int(tournament.get("round_current") or 1)
    has_current = any(int(g["round"]) == current for g in tournament.get("games", []))
    if has_current:
        _check_round_complete(tournament, current)
        round_number = current + 1
    else:
        round_number = current

    if round_number > int(tournament["rounds_total"]):
        raise TournamentError("No quedan rondas por jugar. Cierra el torneo")

    jugadores = st.build_players_dict(state, tournament)
    viva = [n for n, d in jugadores.items() if int(d.get("retirado") or 0) == 0]
    if len(viva) < 2:
        raise TournamentError("Quedan menos de 2 jugadores activos")

    if int(tournament["type"]) == 1:
        parejas, bye = core.emparejamiento_suizo(viva, jugadores)
    else:
        lista = sorted(viva)
        todas = core.generar_round_robin(lista, dos_vueltas=int(tournament["type"]) == 3)
        if round_number > len(todas):
            raise TournamentError("La ronda supera el calendario Round Robin")
        parejas = []
        bye = None
        for white, black in todas[round_number - 1]:
            if black == "BYE":
                bye = white
                continue
            if white not in jugadores or black not in jugadores:
                continue
            if jugadores[white]["retirado"] == 1 or jugadores[black]["retirado"] == 1:
                continue
            parejas.append((white, black))

    if not parejas and not bye:
        raise TournamentError("No se pudieron generar emparejamientos")

    created = []
    for white, black in parejas:
        gid = st.next_id(state, "game")
        tournament["games"].append({
            "id": gid, "round": int(round_number),
            "white_id": int(jugadores[white]["id"]), "black_id": int(jugadores[black]["id"]),
            "result": None, "bye": 0, "date": now_str(),
            "var_white": None, "var_black": None,
        })
        created.append({"game_id": gid, "white": white, "black": black, "bye": False})
    if bye:
        gid = st.next_id(state, "game")
        tournament["games"].append({
            "id": gid, "round": int(round_number),
            "white_id": int(jugadores[bye]["id"]), "black_id": None,
            "result": 1.0, "bye": 1, "date": now_str(),
            "var_white": None, "var_black": None,
        })
        created.append({"game_id": gid, "white": bye, "black": None, "bye": True})

    tournament["round_current"] = int(round_number)
    recompute_points(tournament)
    return {"round": int(round_number), "games": created, "bye": bye}


def save_results(state, tournament_id, results):
    tournament = tournament_by_id(state, tournament_id)
    if not tournament:
        raise TournamentError("Torneo no encontrado")
    if tournament.get("finished"):
        raise TournamentError("El torneo ya está finalizado")
    by_id = {int(g["id"]): g for g in tournament.get("games", [])}
    changed = 0
    for item in results or []:
        try:
            game_id = int(item.get("game_id"))
        except (TypeError, ValueError):
            raise TournamentError("Partida inválida")
        game = by_id.get(game_id)
        if not game:
            raise TournamentError(f"La partida {game_id} no existe en este torneo")
        if game.get("bye"):
            raise TournamentError("No se puede cambiar el resultado de un bye")
        game["result"] = _parse_result(item.get("result"))
        game["var_white"] = None
        game["var_black"] = None
        changed += 1
    if changed == 0:
        raise TournamentError("No hay resultados para guardar")
    recompute_points(tournament)
    st.recompute_ratings(state, tournament, round_until=None, persist=True)
    return tournament


def withdraw_player(state, tournament_id, player_id):
    tournament = tournament_by_id(state, tournament_id)
    if not tournament:
        raise TournamentError("Torneo no encontrado")
    if tournament.get("finished"):
        raise TournamentError("El torneo ya está finalizado")
    part = participant(tournament, player_id)
    if not part:
        raise TournamentError("El jugador no participa en este torneo")
    part["withdrawn"] = 1
    return part


def close_tournament(state, tournament_id):
    tournament = tournament_by_id(state, tournament_id)
    if not tournament:
        raise TournamentError("Torneo no encontrado")
    if tournament.get("finished"):
        return tournament
    pending = [
        g for g in tournament.get("games", [])
        if not g.get("bye") and g.get("result") is None
    ]
    if pending:
        raise PendingResults([int(g["id"]) for g in pending])
    tournament["finished"] = True
    tournament["date_end"] = now_str()
    rounds = [int(g["round"]) for g in tournament.get("games", [])]
    if rounds:
        tournament["round_current"] = max(int(tournament.get("round_current") or 1), max(rounds))
    recompute_points(tournament)
    st.recompute_ratings(state, tournament, round_until=None, persist=True)
    return tournament


def tournament_payload(state, tournament):
    """Vista de un torneo para el panel (nombres, standings y partidas)."""
    if not tournament:
        return None
    players = {int(p["id"]): p for p in state.get("players", [])}
    filas = st.standings(state, tournament, rating_mode=("tournament_end" if tournament.get("finished") else "current"))
    standings = []
    for pos, f in enumerate(filas, 1):
        standings.append({
            "pos": pos,
            "player_id": int(f.jugador_id),
            "name": f.nombre,
            "points": float(f.puntos),
            "de": float(f.direct_encounter),
            "bh1": float(f.buchholz_cut1),
            "bh": float(f.buchholz_total),
            "sb": float(f.sonneborn_berger),
            "wins": int(f.victorias),
            "koya": float(f.koya),
            "aroc1": float(f.aroc1),
            "rating": int(round(f.rating)),
            "tpr": int(f.tpr),
        })
    games = []
    for g in sorted(tournament.get("games", []), key=lambda x: (int(x["round"]), int(x["id"]))):
        white = players.get(int(g["white_id"])) if g.get("white_id") is not None else None
        black = players.get(int(g["black_id"])) if g.get("black_id") is not None else None
        games.append({
            "id": int(g["id"]),
            "round": int(g["round"]),
            "white_id": int(g["white_id"]) if g.get("white_id") is not None else None,
            "black_id": int(g["black_id"]) if g.get("black_id") is not None else None,
            "white": (white or {}).get("name") if white else None,
            "black": (black or {}).get("name") if black else None,
            "result": g.get("result"),
            "bye": bool(g.get("bye")),
            "var_white": g.get("var_white"),
            "var_black": g.get("var_black"),
        })
    participants = []
    for part in tournament.get("participants", []):
        player = players.get(int(part["player_id"])) or {}
        participants.append({
            "player_id": int(part["player_id"]),
            "name": player.get("name", "?"),
            "points": float(part.get("points") or 0.0),
            "withdrawn": int(part.get("withdrawn") or 0),
            "rating_start": float(part.get("rating_start") or 0.0),
            "variation_total": int(round(float(part.get("variation_total") or 0))),
        })
    pending = [g for g in tournament.get("games", []) if not g.get("bye") and g.get("result") is None]
    return {
        "id": int(tournament["id"]),
        "name": tournament.get("name", ""),
        "type": int(tournament.get("type", 1)),
        "rhythm": tournament.get("rhythm", ""),
        "rounds_total": int(tournament.get("rounds_total") or 0),
        "round_current": int(tournament.get("round_current") or 1),
        "finished": bool(tournament.get("finished")),
        "date_start": tournament.get("date_start"),
        "date_end": tournament.get("date_end"),
        "standings": standings,
        "games": games,
        "participants": participants,
        "pending": len(pending),
    }
