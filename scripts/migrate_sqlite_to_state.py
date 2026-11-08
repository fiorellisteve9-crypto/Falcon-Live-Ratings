#!/usr/bin/env python3
"""Convierte la base SQLite de SwissManager al estado JSON de Falcón Live Ratings.

Uso:
  python3 scripts/migrate_sqlite_to_state.py \
      --db gestion_glicko2.db \
      --live falcon_live.json \
      --out seed_state.json

El resultado se importa una sola vez en Supabase (tabla falcon_state).
No se ejecuta en producción: es una migración de escritorio.
"""

from __future__ import annotations

import argparse
import json
import sqlite3

RHYTHMS = {"Rapid": "rapid", "Blitz": "blitz", "Bullet": "bullet"}


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate(db_path, live_path=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    state = {
        "schema": 1,
        "players": [],
        "tournaments": [],
        "matches": [],
        "next_ids": {"player": 1, "tournament": 1, "game": 1, "match": 1},
    }

    jug_cols = _columns(conn, "jugadores")
    for row in conn.execute("SELECT * FROM jugadores ORDER BY id"):
        ratings = {}
        for rhythm, key in RHYTHMS.items():
            ratings[rhythm] = {
                "rating": float(row[f"rating_{key}"] or 1500.0),
                "rd": float(row[f"rd_{key}"] or 500.0),
                "sigma": float(row[f"sigma_{key}"] or 0.09),
                "var": int(row[f"variacion_ultimo_{key}"] or 0),
                "last": row[f"ultima_actividad_{key}"],
            }
        state["players"].append({
            "id": int(row["id"]),
            "name": row["nombre"],
            "ratings": ratings,
            "mun": row["mun"] if "mun" in jug_cols else "-",
            "cat": row["cat"] if "cat" in jug_cols else "-",
            "foto_url": row["foto_url"] if "foto_url" in jug_cols else None,
        })

    for t in conn.execute("SELECT * FROM torneos ORDER BY id"):
        tid = int(t["id"])
        participants = []
        for p in conn.execute(
            "SELECT * FROM participantes_torneo WHERE torneo_id=? ORDER BY jugador_id",
            (tid,),
        ):
            participants.append({
                "player_id": int(p["jugador_id"]),
                "points": float(p["puntos"] or 0.0),
                "color_history": p["historial_colores"] or "",
                "withdrawn": int(p["retirado"] or 0),
                "rating_start": float(p["rating_inicial"] or 1500.0),
                "rd_start": float(p["rd_inicial"] or 500.0),
                "sigma_start": float(p["sigma_inicial"] or 0.09),
                "variation_total": p["variacion_total"],
            })

        games = []
        for g in conn.execute(
            "SELECT * FROM partidas WHERE torneo_id=? ORDER BY ronda, id",
            (tid,),
        ):
            games.append({
                "id": int(g["id"]),
                "round": int(g["ronda"]),
                "white_id": int(g["blancas_id"]) if g["blancas_id"] is not None else None,
                "black_id": int(g["negras_id"]) if g["negras_id"] is not None else None,
                "result": g["resultado"],
                "bye": int(g["es_bye"] or 0),
                "date": g["fecha_registro"],
                "var_white": g["variacion_blancas"],
                "var_black": g["variacion_negras"],
            })

        snapshots = []
        for s in conn.execute(
            "SELECT * FROM snapshot_clasificacion WHERE torneo_id=? "
            "ORDER BY ronda_snapshot, posicion",
            (tid,),
        ):
            snapshots.append({k: s[k] for k in s.keys()})

        state["tournaments"].append({
            "id": tid,
            "name": t["nombre"],
            "type": int(t["tipo_torneo"]),
            "rhythm": t["ritmo_juego"],
            "rounds_total": int(t["rondas_totales"]),
            "round_current": int(t["ronda_actual"] or 1),
            "finished": bool(t["finalizado"]),
            "date_start": t["fecha_inicio"],
            "date_end": t["fecha_fin"],
            "participants": participants,
            "games": games,
            "snapshots": snapshots,
        })

    for m in conn.execute("SELECT * FROM matches ORDER BY id"):
        state["matches"].append({k: m[k] for k in m.keys()})

    state["next_ids"] = {
        "player": max([p["id"] for p in state["players"]], default=0) + 1,
        "tournament": max([t["id"] for t in state["tournaments"]], default=0) + 1,
        "game": max([g["id"] for t in state["tournaments"] for g in t["games"]], default=0) + 1,
        "match": max([int(m["id"]) for m in state["matches"]], default=0) + 1,
    }

    if live_path:
        with open(live_path, encoding="utf-8") as fh:
            state["live"] = json.load(fh)

    conn.close()
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--live", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    state = migrate(args.db, args.live)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)

    print("Jugadores:", len(state["players"]))
    print("Torneos:", len(state["tournaments"]))
    print("Partidas:", sum(len(t["games"]) for t in state["tournaments"]))
    print("Matches:", len(state["matches"]))
    print("next_ids:", state["next_ids"])


if __name__ == "__main__":
    main()
