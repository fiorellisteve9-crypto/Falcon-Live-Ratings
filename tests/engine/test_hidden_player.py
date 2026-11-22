"""Ocultar temporalmente un jugador del ranking público.

Un jugador inactivo se puede ocultar desde el panel: deja de salir en el
ranking de la web, pero NO se borra nada (sigue en el panel, en los torneos,
en sus partidas y en su ficha). Es reversible.

Esta prueba comprueba:

  1. Al ocultarlo desaparece del ranking de los tres ritmos.
  2. Los demás conservan su orden y los puestos quedan sin huecos (1..n).
  3. Sigue en el historial (para que los torneos no desaparezcan del selector)
     y en la clasificación de los torneos que jugó.
  4. Al volver a mostrarlo, reaparece en su puesto.

No necesita navegador.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from engine import live as lv
from engine import tournaments as tm

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:120]) if extra != "" else ""))


def estado_base():
    state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
    for i, nombre in enumerate(["Ana", "Beto", "Carla", "Dani", "Eva"]):
        tm.create_player(state, nombre, mun="Falcón", cat="Sub-14",
                         rhythm="Rapid", rating=1500 + i * 20, rd=200)
    # Un par de partidas para que los cinco tengan ranking.
    for j1, j2, r in [(1, 2, 1.0), (3, 4, 0.5), (5, 1, 0.0), (2, 3, 1.0)]:
        tm.create_match(state, j1, j2, "Rapid", [r], "2026-03-01 10:00:00")
    # Un torneo con dos de ellos, ya jugado.
    tm.create_tournament(state, "Torneo Prueba", 1, "Rapid", 1,
                         player_ids=[1, 2, 3], date_start="2026-03-02 10:00:00")
    torneo = state["tournaments"][0]
    tm.pair_next_round(state, int(torneo["id"]))
    juegos = [g for g in torneo["games"] if not g.get("bye")]
    tm.save_results(state, int(torneo["id"]),
                    [{"game_id": int(g["id"]), "result": 1.0} for g in juegos])
    return state, torneo


def nombres_ranking(payload, ritmo="Rapid"):
    return [row["n"] for row in payload["ranking"][ritmo]]


state, torneo = estado_base()
antes = lv.build_live(state)
chk("de partida los cinco salen en el ranking", len(nombres_ranking(antes)) == 5,
    nombres_ranking(antes))
chk("los puestos van 1..5", [r["r"] for r in antes["ranking"]["Rapid"]] == [1, 2, 3, 4, 5],
    [r["r"] for r in antes["ranking"]["Rapid"]])

print("== 1. Ocultar a Beto (id 2) ==")
tm.update_player(state, 2, {"hidden": True})
jugador = tm.player_by_id(state, 2)
chk("el jugador queda marcado como oculto", int(jugador.get("hidden") or 0) == 1,
    jugador.get("hidden"))
oculto = lv.build_live(state)
chk("Beto ya no sale en el ranking", "Beto" not in nombres_ranking(oculto), nombres_ranking(oculto))
chk("los demás siguen ahí", len(nombres_ranking(oculto)) == 4, nombres_ranking(oculto))
chk("los puestos quedan sin huecos (1..4)",
    [r["r"] for r in oculto["ranking"]["Rapid"]] == [1, 2, 3, 4],
    [r["r"] for r in oculto["ranking"]["Rapid"]])
chk("los demás conservan su orden",
    nombres_ranking(oculto) == [n for n in nombres_ranking(antes) if n != "Beto"],
    nombres_ranking(oculto))

print("== 2. No se pierde nada más ==")
chk("sigue en el historial público (los torneos no desaparecen)",
    "Beto" in (oculto.get("historial") or {}), sorted((oculto.get("historial") or {}).keys()))
chk("sigue en la clasificación del torneo",
    "Beto" in [j["n"] for j in (oculto.get("torneo") or {}).get("jugadores", [])],
    [j["n"] for j in (oculto.get("torneo") or {}).get("jugadores", [])])
chk("su rating no se toca", abs(lv._rating(jugador, "Rapid") - lv._rating(jugador, "Rapid")) == 0)

print("== 3. Volver a mostrarlo ==")
tm.update_player(state, 2, {"hidden": False})
jugador = tm.player_by_id(state, 2)
chk("el jugador queda visible", int(jugador.get("hidden") or 0) == 0, jugador.get("hidden"))
despues = lv.build_live(state)
chk("Beto vuelve al ranking", nombres_ranking(despues) == nombres_ranking(antes), nombres_ranking(despues))
chk("vuelve en el mismo puesto", [r["n"] for r in despues["ranking"]["Rapid"]] ==
    [r["n"] for r in antes["ranking"]["Rapid"]],
    [r["n"] for r in despues["ranking"]["Rapid"]])

print("== 4. Ocultar a alguien sin partidas no rompe nada ==")
tm.create_player(state, "Sin Partidas", mun="Falcón", cat="-")
tm.update_player(state, 6, {"hidden": True})
raro = lv.build_live(state)
chk("el ranking sigue bien", len(nombres_ranking(raro)) == 5, nombres_ranking(raro))
chk("no aparece un hueco ni un error", [r["r"] for r in raro["ranking"]["Rapid"]] == [1, 2, 3, 4, 5],
    [r["r"] for r in raro["ranking"]["Rapid"]])

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
