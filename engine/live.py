"""Construye el JSON público que consume `index.html`.

Porta `sync_to_firebase.exportar_datos_a_json` al estado JSONB, sin SQL.
El resultado mantiene el mismo formato que la web actual.
"""

from __future__ import annotations

from datetime import datetime

RHYTHMS = ("Rapid", "Blitz", "Bullet")
FLAG = "🇻🇪"


def _players_by_id(state):
    return {int(p["id"]): p for p in state.get("players", [])}


def _rating_slot(player, rhythm):
    return (player.get("ratings") or {}).get(rhythm) or {}


def _rating(player, rhythm):
    return float(_rating_slot(player, rhythm).get("rating", 1500.0))


def _variation(player, rhythm):
    return int(round(float(_rating_slot(player, rhythm).get("var", 0) or 0)))


def _meta(player):
    return {
        "cat": player.get("cat") or "-",
        "mun": player.get("mun") or "-",
        "foto": player.get("foto_url") or None,
    }


def _partidas_por_ritmo(state, player_id, rhythm):
    count = 0
    for t in state.get("tournaments", []):
        if t.get("rhythm") != rhythm:
            continue
        for g in t.get("games", []):
            if g.get("result") is None:
                continue
            if g.get("white_id") == player_id or g.get("black_id") == player_id:
                count += 1
    for m in state.get("matches", []):
        if m.get("ritmo") == rhythm and (
            int(m.get("jugador1_id", -1)) == player_id
            or int(m.get("jugador2_id", -1)) == player_id
        ):
            count += int(m.get("n_partidas") or 0)
    return count


def _historial_rating(state, player_id, rhythm, current_rating, max_puntos=10):
    points = []
    for m in state.get("matches", []):
        if m.get("ritmo") != rhythm:
            continue
        if int(m.get("jugador1_id", -1)) == player_id:
            points.append((m.get("fecha") or "", m.get("rating_final_p1")))
        elif int(m.get("jugador2_id", -1)) == player_id:
            points.append((m.get("fecha") or "", m.get("rating_final_p2")))

    for t in state.get("tournaments", []):
        if t.get("rhythm") != rhythm:
            continue
        part = next((p for p in t.get("participants", []) if int(p["player_id"]) == player_id), None)
        if not part:
            continue
        rating_run = float(part.get("rating_start", 1500.0))
        points.append((t.get("date_start") or "", rating_run))
        games = [
            g for g in t.get("games", [])
            if not g.get("bye") and g.get("result") is not None
            and (g.get("white_id") == player_id or g.get("black_id") == player_id)
        ]
        games.sort(key=lambda g: (int(g["round"]), int(g["id"])))
        for g in games:
            delta = g.get("var_white") if g.get("white_id") == player_id else g.get("var_black")
            if delta is None:
                continue
            rating_run += float(delta)
            points.append((g.get("date") or "", rating_run))

    points.sort(key=lambda x: x[0])
    serie = [int(round(p[1])) for p in points if p[1] is not None]
    serie.append(int(round(current_rating)))
    if len(serie) < 2:
        return [int(round(current_rating))] * 2
    return serie[-max_puntos:]


def _posicion(tournament, player_id):
    part = next((p for p in tournament.get("participants", []) if int(p["player_id"]) == player_id), None)
    if not part:
        return "-/-"
    pts = float(part.get("points") or 0.0)
    adelante = sum(1 for p in tournament.get("participants", []) if float(p.get("points") or 0.0) > pts)
    return f"{adelante + 1}/{len(tournament.get('participants', []))}"


def _match_side(players, match, side):
    pid = int(match.get(f"jugador{side}_id", -1))
    player = players.get(pid) or {"name": "?", "cat": "-", "mun": "-", "foto_url": None}
    meta = _meta(player)
    entry = {
        "n": player.get("name", "?"),
        "cat": meta["cat"],
        "mun": meta["mun"],
        "score": float(match.get(f"score_p{side}") or 0.0),
        "ei": int(round(float(match.get(f"rating_inicial_p{side}") or 1500.0))),
        "ef": int(round(float(match.get(f"rating_final_p{side}") or 1500.0))),
        "v": int(round(float(match.get(f"var_p{side}") or 0))),
    }
    if meta["foto"]:
        entry["foto"] = meta["foto"]
    return entry


def build_live(state, now=None):
    players = _players_by_id(state)
    payload = {
        "timestamp": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "ranking": {r: [] for r in RHYTHMS},
        "torneo": None,
        "torneo_partidas": {},
        "matches": [],
        "historial": {},
    }

    prev_ranks = state.get("ranking_snapshot") or {}

    # ── Rankings por ritmo ──────────────────────────────────────────
    for rhythm in RHYTHMS:
        ordered = sorted(
            state.get("players", []),
            key=lambda p: (-_rating(p, rhythm), int(p["id"])),
        )
        for player in ordered:
            pid = int(player["id"])
            partidas = _partidas_por_ritmo(state, pid, rhythm)
            if partidas == 0:
                continue
            rank = len(payload["ranking"][rhythm]) + 1
            meta = _meta(player)
            prev = (prev_ranks.get(rhythm) or {}).get(str(pid))
            entry = {
                "r": rank,
                "n": player.get("name", "?"),
                "e": int(round(_rating(player, rhythm))),
                "v": _variation(player, rhythm),
                "p": partidas,
                "cat": meta["cat"],
                "mun": meta["mun"],
                "flag": FLAG,
                "dr": (int(prev) - rank) if prev is not None else 0,
                "sp": _historial_rating(state, pid, rhythm, _rating(player, rhythm)),
            }
            if meta["foto"]:
                entry["foto"] = meta["foto"]
            payload["ranking"][rhythm].append(entry)

    # ── Torneo actual (el último creado) ───────────────────────────
    tournaments = state.get("tournaments", [])
    current = max(tournaments, key=lambda t: int(t["id"])) if tournaments else None
    if current:
        tid = int(current["id"])
        parts = sorted(
            current.get("participants", []),
            key=lambda p: (-float(p.get("points") or 0.0), int(p["player_id"])),
        )
        payload["torneo"] = {
            "id": tid,
            "nombre": current.get("name", ""),
            "ritmo": current.get("rhythm", ""),
            "ronda": int(current.get("round_current") or 1),
            "rondas_totales": int(current.get("rounds_total") or 0),
            "finalizado": int(bool(current.get("finished"))),
            "jugadores": [],
        }
        for rank, part in enumerate(parts, 1):
            pid = int(part["player_id"])
            player = players.get(pid) or {"name": "?", "cat": "-", "mun": "-", "foto_url": None}
            meta = _meta(player)
            var = int(round(float(part.get("variation_total") or 0)))
            rating_end = int(round(float(part.get("rating_start", 1500.0)) + float(part.get("variation_total") or 0)))
            rj = sum(
                1 for g in current.get("games", [])
                if g.get("result") is not None
                and (g.get("white_id") == pid or g.get("black_id") == pid)
            )
            entry = {
                "r": rank,
                "n": player.get("name", "?"),
                "pts": float(part.get("points") or 0.0),
                "rj": rj,
                "e": rating_end,
                "v": var,
                "cat": meta["cat"],
                "mun": meta["mun"],
                "flag": FLAG,
            }
            if meta["foto"]:
                entry["foto"] = meta["foto"]
            payload["torneo"]["jugadores"].append(entry)
            payload["torneo_partidas"][player.get("name", "?")] = []

        for game in sorted(current.get("games", []), key=lambda g: (int(g["round"]), int(g["id"]))):
            if game.get("result") is None:
                continue
            white = players.get(int(game["white_id"])) if game.get("white_id") is not None else None
            black = players.get(int(game["black_id"])) if game.get("black_id") is not None else None
            wname = (white or {}).get("name")
            bname = (black or {}).get("name")
            if game.get("bye") or black is None:
                if wname in payload["torneo_partidas"]:
                    payload["torneo_partidas"][wname].append({
                        "ronda": int(game["round"]), "c": "B", "res": "1-0",
                        "opp": "BYE", "v": 0, "bye": True,
                    })
                continue
            if not wname or not bname:
                continue
            res = float(game["result"])
            res_b = "1-0" if res == 1.0 else ("0-1" if res == 0.0 else "1/2")
            res_n = "0-1" if res == 1.0 else ("1-0" if res == 0.0 else "1/2")
            if wname in payload["torneo_partidas"]:
                payload["torneo_partidas"][wname].append({
                    "ronda": int(game["round"]), "c": "B", "res": res_b, "opp": bname,
                    "v": int(round(float(game.get("var_white") or 0))), "bye": False,
                })
            if bname in payload["torneo_partidas"]:
                payload["torneo_partidas"][bname].append({
                    "ronda": int(game["round"]), "c": "N", "res": res_n, "opp": wname,
                    "v": int(round(float(game.get("var_black") or 0))), "bye": False,
                })

    # ── Matches 1v1 ────────────────────────────────────────────────
    matches = sorted(
        state.get("matches", []),
        key=lambda m: (str(m.get("fecha") or ""), int(m.get("id") or 0)),
        reverse=True,
    )
    for m in matches:
        payload["matches"].append({
            "ritmo": m.get("ritmo", ""),
            "np": int(m.get("n_partidas") or 0),
            "fecha": m.get("fecha"),
            "j1": _match_side(players, m, 1),
            "j2": _match_side(players, m, 2),
        })

    # ── Historial por jugador ──────────────────────────────────────
    for player in state.get("players", []):
        pid = int(player["id"])
        name = player.get("name", "?")
        meta = _meta(player)
        entry = {
            "cat": meta["cat"],
            "mun": meta["mun"],
            "torneos": [],
            "partidas": [],
            "oponentes": [],
            "totales": [],
        }
        if meta["foto"]:
            entry["foto"] = meta["foto"]

        # Torneos jugados
        jug_torneos = sorted(
            [t for t in tournaments if any(int(p["player_id"]) == pid for p in t.get("participants", []))],
            key=lambda t: int(t["id"]),
            reverse=True,
        )
        for t in jug_torneos:
            part = next(p for p in t["participants"] if int(p["player_id"]) == pid)
            var = int(round(float(part.get("variation_total") or 0)))
            ei = int(round(float(part.get("rating_start") or 1500.0))) if part.get("rating_start") is not None else None
            entry["torneos"].append({
                "fecha": (t.get("date_start") or "N/A")[:10],
                "pos": _posicion(t, pid),
                "pts": f"{float(part.get('points') or 0.0):.1f}",
                "nombre": t.get("name", ""),
                "ritmo": t.get("rhythm", ""),
                "v": var,
                "ei": ei,
                "ef": (ei + var) if ei is not None else None,
                "rating_inicial": float(part.get("rating_start") or 1500.0),
                "rondas_totales": int(t.get("rounds_total") or 0),
                "finalizado": int(bool(t.get("finished"))),
            })

        # Partidas del historial (id descendente)
        hist_games = []
        for t in tournaments:
            for g in t.get("games", []):
                if g.get("result") is None:
                    continue
                if g.get("white_id") == pid or g.get("black_id") == pid:
                    hist_games.append((t, g))
        hist_games.sort(key=lambda tg: int(tg[1]["id"]), reverse=True)
        for t, g in hist_games:
            fecha = (t.get("date_start") or "N/A")[:10]
            if g.get("bye") or g.get("black_id") is None:
                entry["partidas"].append({
                    "fecha": fecha, "c": "B", "res": "1-0", "opp": "BYE", "v": 0,
                    "torneo": t.get("name", ""), "ritmo": t.get("rhythm", ""),
                    "ronda": int(g["round"]), "bye": True,
                })
                continue
            es_blancas = g.get("white_id") == pid
            opp_id = g.get("black_id") if es_blancas else g.get("white_id")
            opp = (players.get(int(opp_id)) or {}).get("name", "?")
            res_val = float(g["result"]) if es_blancas else (1.0 - float(g["result"]))
            res_str = "1-0" if res_val == 1.0 else ("0-1" if res_val == 0.0 else "1/2")
            var_raw = g.get("var_white") if es_blancas else g.get("var_black")
            entry["partidas"].append({
                "fecha": fecha,
                "c": "B" if es_blancas else "N",
                "res": res_str,
                "opp": opp,
                "v": int(round(float(var_raw))) if var_raw is not None else None,
                "torneo": t.get("name", ""),
                "ritmo": t.get("rhythm", ""),
                "ronda": int(g["round"]),
                "bye": False,
            })

        # Oponentes frecuentes + totales por ritmo (solo partidas de torneo)
        opp_stats = {}
        ritmo_stats = {r: {"w": 0, "d": 0, "l": 0} for r in RHYTHMS}
        for t in tournaments:
            for g in t.get("games", []):
                if g.get("result") is None or g.get("bye"):
                    continue
                if not (g.get("white_id") == pid or g.get("black_id") == pid):
                    continue
                es_blancas = g.get("white_id") == pid
                opp_id = g.get("black_id") if es_blancas else g.get("white_id")
                opp = (players.get(int(opp_id)) or {}).get("name", "?")
                res = float(g["result"]) if es_blancas else (1.0 - float(g["result"]))
                bucket = opp_stats.setdefault(opp, {"w": 0, "d": 0, "l": 0})
                rkey = "w" if res == 1.0 else ("l" if res == 0.0 else "d")
                bucket[rkey] += 1
                if t.get("rhythm") in ritmo_stats:
                    ritmo_stats[t["rhythm"]][rkey] += 1

        for opp, st in sorted(opp_stats.items(), key=lambda kv: kv[1]["w"] + kv[1]["d"] + kv[1]["l"], reverse=True):
            total = st["w"] + st["d"] + st["l"]
            score = round((st["w"] + 0.5 * st["d"]) / total * 100) if total else 0
            entry["oponentes"].append({
                "nombre": opp, "w": st["w"], "d": st["d"], "l": st["l"],
                "total": total, "score": f"{score}%",
            })

        general = {"w": 0, "d": 0, "l": 0}
        for rhythm in RHYTHMS:
            st = ritmo_stats[rhythm]
            total = st["w"] + st["d"] + st["l"]
            pct = f"{(st['w'] + 0.5 * st['d']) / total * 100:.0f}%" if total else "-"
            entry["totales"].append({
                "ritmo": rhythm, "w": st["w"], "d": st["d"], "l": st["l"],
                "total": total, "pct": pct,
            })
            for k in ("w", "d", "l"):
                general[k] += st[k]
        total_g = general["w"] + general["d"] + general["l"]
        pct_g = f"{(general['w'] + 0.5 * general['d']) / total_g * 100:.0f}%" if total_g else "-"
        entry["totales"].append({
            "ritmo": "General", "w": general["w"], "d": general["d"], "l": general["l"],
            "total": total_g, "pct": pct_g,
        })

        payload["historial"][name] = entry

    return payload


def new_ranking_snapshot(state, payload):
    """Snapshot de rangos (por id de jugador) para calcular 'dr' la próxima vez."""
    name_to_id = {p.get("name"): int(p["id"]) for p in state.get("players", [])}
    out = {rhythm: {} for rhythm in RHYTHMS}
    for rhythm in RHYTHMS:
        for row in payload.get("ranking", {}).get(rhythm, []):
            pid = name_to_id.get(row.get("n"))
            if pid is not None:
                out[rhythm][str(pid)] = int(row["r"])
    return out
