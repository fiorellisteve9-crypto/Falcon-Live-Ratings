"""Operaciones de dominio sobre el estado: jugadores y torneos.

No conoce HTTP ni Supabase: recibe el dict `state`, lo modifica y devuelve
resultados. La API se encarga de cargar/guardar y de reconstruir el JSON público.
"""

from __future__ import annotations

import math
import re
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


def _normalize_match_date(value):
    """Acepta AAAA-MM-DD o AAAA-MM-DD HH:MM:SS; devuelve timestamp completo."""
    if not value:
        return now_str()
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            dt = dt.replace(hour=12, minute=0, second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    raise TournamentError("Fecha del match inválida (usa AAAA-MM-DD)")


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


def create_player(state, name, mun="-", cat="-", foto_url=None,
                  rhythm=None, rating=None, rd=None):
    name = str(name or "").strip()
    if not name:
        raise TournamentError("El nombre es obligatorio")
    if any(str(p.get("name", "")).strip().lower() == name.lower() for p in state.get("players", [])):
        raise TournamentError("Ya existe un jugador con ese nombre")

    rhythm = str(rhythm or "").strip()
    if rating is not None:
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            raise TournamentError("Rating inicial inválido")
        if not (core.MIN_RATING <= rating <= core.MAX_RATING):
            raise TournamentError(
                f"El rating debe estar entre {int(core.MIN_RATING)} y {int(core.MAX_RATING)}"
            )
    if rd is not None:
        try:
            rd = float(rd)
        except (TypeError, ValueError):
            raise TournamentError("RD inicial inválido")
        if not (core.MIN_RD <= rd <= core.MAX_RD):
            raise TournamentError(
                f"El RD debe estar entre {int(core.MIN_RD)} y {int(core.MAX_RD)}"
            )

    targets = []
    if rhythm:
        if rhythm.lower() == "todos":
            targets = list(st.RHYTHMS)
        elif rhythm in st.RHYTHMS:
            targets = [rhythm]
        else:
            raise TournamentError("Ritmo inválido")
    elif rating is not None or rd is not None:
        raise TournamentError("Elige un ritmo para el rating inicial")

    player = {
        "id": st.next_id(state, "player"),
        "name": name,
        "ratings": {
            r: {"rating": core.DEFAULT_RATING, "rd": core.DEFAULT_RD,
                "sigma": core.DEFAULT_SIGMA, "var": 0, "last": None}
            for r in st.RHYTHMS
        },
        "mun": str(mun or "-").strip() or "-",
        "cat": str(cat or "-").strip() or "-",
        "foto_url": foto_url or None,
    }
    for target in targets:
        if rating is not None:
            player["ratings"][target]["rating"] = rating
        if rd is not None:
            player["ratings"][target]["rd"] = rd
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
    rating = fields.get("rating")
    rd = fields.get("rd")
    if rating is not None or rd is not None:
        rhythm = str(fields.get("rhythm") or "").strip()
        if not rhythm:
            raise TournamentError("Elige el ritmo del rating a corregir")
        if rhythm.lower() == "todos":
            targets = list(st.RHYTHMS)
        elif rhythm in st.RHYTHMS:
            targets = [rhythm]
        else:
            raise TournamentError("Ritmo inválido")
        if rating is not None:
            rating = float(rating)
            if rating < 600 or rating > 4000:
                raise TournamentError("El rating debe estar entre 600 y 4000")
        if rd is not None:
            rd = float(rd)
            if rd < 45 or rd > 500:
                raise TournamentError("El RD debe estar entre 45 y 500")
        for target in targets:
            slot = st._rating_slot(player, target)
            if rating is not None:
                slot["rating"] = rating
            if rd is not None:
                slot["rd"] = rd
            slot["var"] = 0
    return player


def create_tournament(state, name, type_, rhythm, rounds_total=None, player_ids=None,
                     date_start=None, replace_draft=None):
    name = str(name or "").strip()
    if not name:
        raise TournamentError("El nombre del torneo es obligatorio")
    skip_id = int(replace_draft.get("id", -1)) if replace_draft else None
    for other in state.get("tournaments", []):
        if skip_id is not None and int(other.get("id", -1)) == skip_id:
            continue
        if str(other.get("name", "")).strip().lower() == name.lower():
            raise TournamentError("Ya existe un torneo con ese nombre")
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
        "date_start": str(date_start or "").strip() or now_str(),
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
    if replace_draft is not None:
        state["tournaments"] = [
            t for t in state.get("tournaments", [])
            if int(t.get("id", -1)) != int(replace_draft.get("id", -2))
        ]
    state.setdefault("tournaments", []).append(tournament)
    return tournament


# ── Pre-registro (torneo futuro en borrador) ───────────────────────

def _draft_by_id(state, draft_id):
    draft = tournament_by_id(state, draft_id)
    if not draft or not draft.get("draft"):
        raise TournamentError("Pre-registro no encontrado")
    return draft


def _validate_type_rhythm(type_, rhythm):
    try:
        type_ = int(type_)
    except (TypeError, ValueError):
        raise TournamentError("Sistema de juego inválido")
    if type_ not in (1, 2, 3):
        raise TournamentError("Sistema de juego inválido")
    rhythm = str(rhythm or "").strip()
    if rhythm not in st.RHYTHMS:
        raise TournamentError("Ritmo inválido")
    return type_, rhythm


def _normalize_date(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        raise TournamentError("La fecha prevista debe ser YYYY-MM-DD")
    return raw


def _check_draft_name(state, name, ignore_id=None):
    low = name.strip().lower()
    for other in state.get("tournaments", []):
        if ignore_id is not None and int(other.get("id", -1)) == int(ignore_id):
            continue
        if str(other.get("name", "")).strip().lower() == low:
            raise TournamentError("Ya existe un torneo o pre-registro con ese nombre")


def create_draft(state, name, type_, rhythm, rounds_total=None, date_start=None):
    name = str(name or "").strip()
    if not name:
        raise TournamentError("Pon un nombre al pre-registro")
    type_, rhythm = _validate_type_rhythm(type_, rhythm)
    _check_draft_name(state, name)
    rounds = None
    if type_ == 1 and rounds_total not in (None, ""):
        try:
            rounds = max(1, min(99, int(rounds_total)))
        except (TypeError, ValueError):
            raise TournamentError("Rondas inválidas")
    draft = {
        "id": st.next_id(state, "tournament"),
        "draft": True,
        "name": name,
        "type": type_,
        "rhythm": rhythm,
        "rounds_total": rounds,
        "date_start": _normalize_date(date_start),
        "entries": [],
        "created_at": now_str(),
    }
    state.setdefault("tournaments", []).append(draft)
    return draft


def update_draft(state, draft_id, fields):
    draft = _draft_by_id(state, draft_id)
    if "name" in fields:
        name = str(fields.get("name") or "").strip()
        if not name:
            raise TournamentError("Pon un nombre al pre-registro")
        _check_draft_name(state, name, ignore_id=draft["id"])
        draft["name"] = name
    if "type" in fields or "rhythm" in fields:
        type_, rhythm = _validate_type_rhythm(
            fields.get("type", draft.get("type")), fields.get("rhythm", draft.get("rhythm"))
        )
        draft["type"] = type_
        draft["rhythm"] = rhythm
    if "date_start" in fields:
        draft["date_start"] = _normalize_date(fields.get("date_start"))
    if "rounds_total" in fields:
        raw = fields.get("rounds_total")
        if raw in (None, ""):
            draft["rounds_total"] = None
        else:
            try:
                draft["rounds_total"] = max(1, min(99, int(raw)))
            except (TypeError, ValueError):
                raise TournamentError("Rondas inválidas")
    return draft


def add_draft_entry(state, draft_id, player_id=None, name=None, cat="-", mun="-"):
    draft = _draft_by_id(state, draft_id)
    entries = draft.setdefault("entries", [])
    if player_id not in (None, ""):
        try:
            pid = int(player_id)
        except (TypeError, ValueError):
            raise TournamentError("Jugador inválido")
        player = player_by_id(state, pid)
        if not player:
            raise TournamentError("Jugador no encontrado")
        if any(int(e.get("player_id") or 0) == pid for e in entries):
            raise TournamentError(f"{player.get('name')} ya está inscrito")
        entry = {
            "id": st.next_id(state, "draft_entry"),
            "player_id": pid,
            "name": player.get("name", "?"),
            "cat": player.get("cat") or "-",
            "mun": player.get("mun") or "-",
        }
    else:
        clean = str(name or "").strip()
        if not clean:
            raise TournamentError("Escribe el nombre del inscrito")
        if any(str(e.get("name", "")).strip().lower() == clean.lower() for e in entries):
            raise TournamentError(f"{clean} ya está inscrito")
        if any(str(p.get("name", "")).strip().lower() == clean.lower()
               for p in state.get("players", [])):
            raise TournamentError(
                f"Ya existe un jugador llamado {clean}: agrégalo desde la lista"
            )
        entry = {
            "id": st.next_id(state, "draft_entry"),
            "player_id": None,
            "name": clean,
            "cat": str(cat or "-").strip() or "-",
            "mun": str(mun or "-").strip() or "-",
        }
    entries.append(entry)
    return draft


def remove_draft_entry(state, draft_id, entry_id):
    draft = _draft_by_id(state, draft_id)
    before = len(draft.get("entries", []))
    draft["entries"] = [
        e for e in draft.get("entries", []) if int(e.get("id", -1)) != int(entry_id)
    ]
    if len(draft["entries"]) == before:
        raise TournamentError("Ese inscrito no está en la lista")
    return draft


def delete_draft(state, draft_id):
    draft = _draft_by_id(state, draft_id)
    state["tournaments"] = [
        t for t in state.get("tournaments", []) if int(t.get("id", -1)) != int(draft["id"])
    ]
    return draft


def activate_draft(state, draft_id, rounds_total=None):
    """Convierte el borrador en torneo real: crea los jugadores que falten."""
    draft = _draft_by_id(state, draft_id)
    entries = draft.get("entries") or []
    if len(entries) < 2:
        raise TournamentError("Necesitas al menos 2 inscritos para activar el torneo")
    player_ids = []
    for entry in entries:
        pid = entry.get("player_id")
        if not pid:
            player = create_player(
                state, entry.get("name"), entry.get("mun") or "-", entry.get("cat") or "-"
            )
            pid = player["id"]
        if int(pid) not in player_ids:
            player_ids.append(int(pid))
    if len(player_ids) < 2:
        raise TournamentError("Necesitas al menos 2 jugadores distintos")
    planned = str(draft.get("date_start") or "")
    today = datetime.now().strftime("%Y-%m-%d")
    date_start = planned if planned and planned[:10] <= today else None
    rounds = rounds_total if rounds_total not in (None, "") else draft.get("rounds_total")
    tournament = create_tournament(
        state,
        draft.get("name"),
        draft.get("type"),
        draft.get("rhythm"),
        rounds_total=rounds,
        player_ids=player_ids,
        date_start=date_start,
        replace_draft=draft,
    )
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
        # Calendario estable: se genera con la lista inicial de participantes,
        # no con los activos del momento. Así un retiro no rebaraja las rondas.
        lista = sorted(jugadores.keys())
        todas = core.generar_round_robin(lista, dos_vueltas=int(tournament["type"]) == 3)
        if round_number > len(todas):
            raise TournamentError("La ronda supera el calendario Round Robin")
        parejas = []
        bye = None
        for white, black in todas[round_number - 1]:
            if white not in jugadores or jugadores[white]["retirado"] == 1:
                continue
            if black == "BYE":
                bye = white
                continue
            if black not in jugadores or jugadores[black]["retirado"] == 1:
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


def _recompute_last_activity(state):
    """Deja `last` en la fecha del último evento que queda (sin tocar ratings)."""
    for player in state.get("players", []):
        pid = int(player["id"])
        for rhythm in st.RHYTHMS:
            dates = []
            for t in state.get("tournaments", []):
                if t.get("rhythm") != rhythm:
                    continue
                if any(int(p["player_id"]) == pid for p in t.get("participants", [])):
                    if t.get("date_start"):
                        dates.append(str(t["date_start"]))
            for m in state.get("matches", []):
                if m.get("ritmo") != rhythm:
                    continue
                if int(m.get("jugador1_id", -1)) == pid or int(m.get("jugador2_id", -1)) == pid:
                    if m.get("fecha"):
                        dates.append(str(m["fecha"]))
            slot = st._rating_slot(player, rhythm)
            slot["last"] = max(dates) if dates else None


def delete_tournament(state, tournament_id):
    """Elimina un torneo del estado. No recalcula los ratings actuales.

    Es el mismo criterio que el gestor anterior: se borra el torneo y sus
    partidas, pero los ratings ya calculados se conservan. El panel descarga
    una copia antes de borrar para poder restaurar.
    """
    tournament = tournament_by_id(state, tournament_id)
    if not tournament:
        raise TournamentError("Torneo no encontrado")
    state["tournaments"] = [
        t for t in state.get("tournaments", []) if int(t["id"]) != int(tournament_id)
    ]
    _recompute_last_activity(state)
    return tournament


def create_match(state, player1_id, player2_id, rhythm, results, match_date=None):
    """Registra un match 1v1 y actualiza los ratings Glicko-2.

    `results` es la lista de resultados de cada partida DESDE LAS BLANCAS
    (1-0, 0-1 o tablas). Los colores alternan: partida 1 P1 blancas,
    partida 2 P2 blancas, etc.
    """
    if int(player1_id) == int(player2_id):
        raise TournamentError("No puedes emparejar a un jugador consigo mismo")
    p1 = player_by_id(state, player1_id)
    p2 = player_by_id(state, player2_id)
    if not p1 or not p2:
        raise TournamentError("Jugador no encontrado")
    rhythm = str(rhythm or "").strip()
    if rhythm not in st.RHYTHMS:
        raise TournamentError("Ritmo inválido")
    if not results:
        raise TournamentError("El match necesita al menos una partida")
    if len(results) > 999:
        raise TournamentError("Demasiadas partidas (máximo 999)")
    parsed = [_parse_result(r) for r in results]
    match_date = _normalize_match_date(match_date)
    if match_date[:10] > datetime.now().strftime("%Y-%m-%d"):
        raise TournamentError("La fecha del match no puede ser futura")

    vals = _apply_series(p1, p2, rhythm, parsed, match_date)
    match = {
        "id": st.next_id(state, "match"),
        "jugador1_id": int(player1_id),
        "jugador2_id": int(player2_id),
        "ritmo": rhythm,
        "n_partidas": len(parsed),
        "score_p1": vals["p1"]["score"],
        "score_p2": vals["p2"]["score"],
        "rating_inicial_p1": vals["p1"]["r0"],
        "rd_inicial_p1": vals["p1"]["rd0"],
        "sigma_inicial_p1": vals["p1"]["sigma0"],
        "rating_final_p1": vals["p1"]["r"],
        "rd_final_p1": vals["p1"]["rd"],
        "sigma_final_p1": vals["p1"]["sigma"],
        "var_p1": vals["p1"]["var"],
        "rating_inicial_p2": vals["p2"]["r0"],
        "rd_inicial_p2": vals["p2"]["rd0"],
        "sigma_inicial_p2": vals["p2"]["sigma0"],
        "rating_final_p2": vals["p2"]["r"],
        "rd_final_p2": vals["p2"]["rd"],
        "sigma_final_p2": vals["p2"]["sigma"],
        "var_p2": vals["p2"]["var"],
        "fecha": match_date,
        "resultados": list(parsed),
    }
    state.setdefault("matches", []).append(match)
    _persist_slots(p1, p2, rhythm, vals, match_date)
    return match


def _apply_series(p1, p2, rhythm, parsed, fecha):
    """Calcula el efecto Glicko-2 de una serie de partidas. No muta el estado."""
    slot1 = st._rating_slot(p1, rhythm)
    slot2 = st._rating_slot(p2, rhythm)
    r1, rd1, s1 = float(slot1["rating"]), float(slot1["rd"]), float(slot1["sigma"])
    r2, rd2, s2 = float(slot2["rating"]), float(slot2["rd"]), float(slot2["sigma"])
    last1, last2 = slot1.get("last"), slot2.get("last")
    if last1 and fecha[:10] < str(last1)[:10]:
        raise TournamentError(
            f"La fecha es anterior a la última actividad de {p1['name']} ({str(last1)[:10]})"
        )
    if last2 and fecha[:10] < str(last2)[:10]:
        raise TournamentError(
            f"La fecha es anterior a la última actividad de {p2['name']} ({str(last2)[:10]})"
        )
    prev_last1, prev_last2 = last1, last2
    r1_init, rd1_init, s1_init = r1, rd1, s1
    r2_init, rd2_init, s2_init = r2, rd2, s2
    score1 = 0.0
    score2 = 0.0

    for i, res in enumerate(parsed):
        elapsed1 = core.elapsed_rating_periods(last1, fecha) if i == 0 else 0.0
        elapsed2 = core.elapsed_rating_periods(last2, fecha) if i == 0 else 0.0
        if i % 2 == 0:  # P1 blancas
            (r1, rd1, s1), (r2, rd2, s2) = core.glicko2_match_update_pair(
                r1, rd1, s1, r2, rd2, s2, res, elapsed1, elapsed2
            )
            score1 += res
            score2 += 1.0 - res
        else:  # P2 blancas
            (r2, rd2, s2), (r1, rd1, s1) = core.glicko2_match_update_pair(
                r2, rd2, s2, r1, rd1, s1, res, elapsed2, elapsed1
            )
            score2 += res
            score1 += 1.0 - res
        last1 = last2 = fecha

    return {
        "p1": {
            "r": r1, "rd": rd1, "sigma": s1,
            "r0": r1_init, "rd0": rd1_init, "sigma0": s1_init,
            "var": int(round(r1 - r1_init)), "score": score1,
        },
        "p2": {
            "r": r2, "rd": rd2, "sigma": s2,
            "r0": r2_init, "rd0": rd2_init, "sigma0": s2_init,
            "var": int(round(r2 - r2_init)), "score": score2,
        },
        "prev_last1": prev_last1,
        "prev_last2": prev_last2,
    }


def _persist_slots(p1, p2, rhythm, vals, fecha):
    """Escribe en los slots de los jugadores el resultado de la serie."""
    slot1 = st._rating_slot(p1, rhythm)
    slot2 = st._rating_slot(p2, rhythm)
    new_last1 = max(str(vals["prev_last1"] or ""), fecha) or fecha
    new_last2 = max(str(vals["prev_last2"] or ""), fecha) or fecha
    slot1.update({"rating": vals["p1"]["r"], "rd": vals["p1"]["rd"], "sigma": vals["p1"]["sigma"],
                  "var": vals["p1"]["var"], "last": new_last1})
    slot2.update({"rating": vals["p2"]["r"], "rd": vals["p2"]["rd"], "sigma": vals["p2"]["sigma"],
                  "var": vals["p2"]["var"], "last": new_last2})


def _write_match_values(match, vals, parsed, fecha):
    """Actualiza en el registro los valores derivados de la serie."""
    match.update({
        "n_partidas": len(parsed),
        "score_p1": vals["p1"]["score"],
        "score_p2": vals["p2"]["score"],
        "rating_inicial_p1": vals["p1"]["r0"],
        "rd_inicial_p1": vals["p1"]["rd0"],
        "sigma_inicial_p1": vals["p1"]["sigma0"],
        "rating_final_p1": vals["p1"]["r"],
        "rd_final_p1": vals["p1"]["rd"],
        "sigma_final_p1": vals["p1"]["sigma"],
        "var_p1": vals["p1"]["var"],
        "rating_inicial_p2": vals["p2"]["r0"],
        "rd_inicial_p2": vals["p2"]["rd0"],
        "sigma_inicial_p2": vals["p2"]["sigma0"],
        "rating_final_p2": vals["p2"]["r"],
        "rd_final_p2": vals["p2"]["rd"],
        "sigma_final_p2": vals["p2"]["sigma"],
        "var_p2": vals["p2"]["var"],
        "fecha": fecha,
        "resultados": list(parsed),
    })


def _match_results(match):
    """Resultados por partida de un match. Los antiguos se reconstruyen."""
    saved = match.get("resultados")
    if isinstance(saved, list) and saved:
        return [_parse_result(r) for r in saved]
    n = int(match.get("n_partidas") or 0)
    score1 = float(match.get("score_p1") or 0.0)
    puntos = int(round(score1 * 2))
    tablas = puntos % 2
    gana1 = (puntos - tablas) // 2
    gana2 = max(0, n - gana1 - tablas)
    res = []
    for i in range(n):
        if i < gana1:
            res.append(1.0 if i % 2 == 0 else 0.0)
        elif i < gana1 + tablas:
            res.append(0.5)
        else:
            res.append(0.0 if i % 2 == 0 else 1.0)
    return res


def _prev_activity_date(state, player_id, rhythm, before_date, exclude_match_id=None):
    """Última actividad del jugador en ese ritmo anterior a `before_date`."""
    dates = []
    limite = str(before_date or "")[:10]
    for t in state.get("tournaments", []):
        if t.get("rhythm") != rhythm:
            continue
        if not any(int(p["player_id"]) == player_id for p in t.get("participants", [])):
            continue
        d = str(t.get("date_start") or "")[:10]
        if d and d < limite:
            dates.append(d)
    for m in state.get("matches", []):
        if m.get("ritmo") != rhythm:
            continue
        if exclude_match_id is not None and int(m.get("id", -1)) == int(exclude_match_id):
            continue
        if int(m.get("jugador1_id", -1)) != player_id and int(m.get("jugador2_id", -1)) != player_id:
            continue
        d = str(m.get("fecha") or "")[:10]
        if d and d < limite:
            dates.append(d)
    return max(dates) if dates else None


def _restore_slot(player, rhythm, rating, rd, sigma, last):
    """Devuelve el slot del jugador a un estado previo conocido."""
    slot = st._rating_slot(player, rhythm)
    slot.update({
        "rating": float(rating),
        "rd": float(rd),
        "sigma": float(sigma),
        "var": 0,
        "last": last,
    })


def _replay_later(state, affected_ids, rhythm, desde, exclude_id):
    """Reaplica los matches posteriores de los jugadores afectados."""
    affected = set(int(x) for x in affected_ids)
    later = []
    for m in state.get("matches", []):
        if int(m.get("id", -1)) == int(exclude_id):
            continue
        if m.get("ritmo") != rhythm:
            continue
        if str(m.get("fecha") or "") < str(desde):
            continue
        if int(m.get("jugador1_id", -1)) in affected or int(m.get("jugador2_id", -1)) in affected:
            later.append(m)
    later.sort(key=lambda m: (str(m.get("fecha") or ""), int(m.get("id", 0))))
    for m in later:
        a = player_by_id(state, m.get("jugador1_id"))
        b = player_by_id(state, m.get("jugador2_id"))
        if not a or not b:
            continue
        fecha = str(m.get("fecha") or now_str())
        parsed = _match_results(m)
        for pl, side in ((a, 1), (b, 2)):
            pid = int(pl["id"])
            if pid not in affected:
                prev = _prev_activity_date(state, pid, rhythm, fecha, exclude_match_id=int(m.get("id", -1)))
                _restore_slot(pl, rhythm, m.get(f"rating_inicial_p{side}"), m.get(f"rd_inicial_p{side}"),
                              m.get(f"sigma_inicial_p{side}"), prev)
        vals = _apply_series(a, b, rhythm, parsed, fecha)
        _write_match_values(m, vals, parsed, fecha)
        _persist_slots(a, b, rhythm, vals, fecha)


def update_match(state, match_id, results=None, match_date=None):
    """Corrige un match ya registrado y recalcula los ratings afectados.

    Devuelve el match actualizado. Los matches posteriores de esos jugadores
    se reaplican en orden cronologico para que los ratings sigan siendo
    coherentes.
    """
    match = next((m for m in state.get("matches", []) if int(m.get("id", -1)) == int(match_id)), None)
    if not match:
        raise TournamentError("Match no encontrado")
    p1 = player_by_id(state, match.get("jugador1_id"))
    p2 = player_by_id(state, match.get("jugador2_id"))
    if not p1 or not p2:
        raise TournamentError("Jugador no encontrado")
    rhythm = match.get("ritmo")
    fecha = _normalize_match_date(match_date) if match_date else str(match.get("fecha") or now_str())
    if fecha[:10] > datetime.now().strftime("%Y-%m-%d"):
        raise TournamentError("La fecha del match no puede ser futura")
    if results is None:
        parsed = _match_results(match)
    else:
        if not results:
            raise TournamentError("El match necesita al menos una partida")
        if len(results) > 999:
            raise TournamentError("Demasiadas partidas (máximo 999)")
        parsed = [_parse_result(r) for r in results]
    match_id_int = int(match.get("id"))
    prev1 = _prev_activity_date(state, int(p1["id"]), rhythm, fecha, exclude_match_id=match_id_int)
    prev2 = _prev_activity_date(state, int(p2["id"]), rhythm, fecha, exclude_match_id=match_id_int)
    _restore_slot(p1, rhythm, match.get("rating_inicial_p1"), match.get("rd_inicial_p1"),
                  match.get("sigma_inicial_p1"), prev1)
    _restore_slot(p2, rhythm, match.get("rating_inicial_p2"), match.get("rd_inicial_p2"),
                  match.get("sigma_inicial_p2"), prev2)
    vals = _apply_series(p1, p2, rhythm, parsed, fecha)
    _write_match_values(match, vals, parsed, fecha)
    _persist_slots(p1, p2, rhythm, vals, fecha)
    _replay_later(state, [int(p1["id"]), int(p2["id"])], rhythm, fecha, match_id_int)
    return match


def delete_match(state, match_id):
    """Elimina un match y recalcula los ratings de los jugadores afectados."""
    match = next((m for m in state.get("matches", []) if int(m.get("id", -1)) == int(match_id)), None)
    if not match:
        raise TournamentError("Match no encontrado")
    p1 = player_by_id(state, match.get("jugador1_id"))
    p2 = player_by_id(state, match.get("jugador2_id"))
    if not p1 or not p2:
        raise TournamentError("Jugador no encontrado")
    rhythm = match.get("ritmo")
    fecha = str(match.get("fecha") or now_str())
    match_id_int = int(match.get("id"))
    prev1 = _prev_activity_date(state, int(p1["id"]), rhythm, fecha, exclude_match_id=match_id_int)
    prev2 = _prev_activity_date(state, int(p2["id"]), rhythm, fecha, exclude_match_id=match_id_int)
    _restore_slot(p1, rhythm, match.get("rating_inicial_p1"), match.get("rd_inicial_p1"),
                  match.get("sigma_inicial_p1"), prev1)
    _restore_slot(p2, rhythm, match.get("rating_inicial_p2"), match.get("rd_inicial_p2"),
                  match.get("sigma_inicial_p2"), prev2)
    state["matches"] = [m for m in state.get("matches", []) if int(m.get("id", -1)) != match_id_int]
    _replay_later(state, [int(p1["id"]), int(p2["id"])], rhythm, fecha, match_id_int)
    return match


def tournament_payload(state, tournament):
    """Vista de un torneo para el panel (nombres, standings y partidas)."""
    if not tournament:
        return None
    players = {int(p["id"]): p for p in state.get("players", [])}
    participants_by_player = {int(p["player_id"]): p for p in tournament.get("participants", [])}
    filas = st.standings(state, tournament, rating_mode=("tournament_end" if tournament.get("finished") else "current"))
    standings = []
    for pos, f in enumerate(filas, 1):
        part = participants_by_player.get(int(f.jugador_id), {})
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
            "v": int(round(float(part.get("variation_total") or 0))),
            "withdrawn": bool(part.get("withdrawn")),
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
