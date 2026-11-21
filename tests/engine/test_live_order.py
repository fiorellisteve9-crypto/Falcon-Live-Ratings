"""La web pública debe ordenar la clasificación por los DESEMPATES, no por id.

Fallo real (21/11/2026, "Torneo de Ajedrez Rápido I"): Jheferson Dávila quedó
3.º por BH1 y la web pública lo mostraba 5.º. El motor ordenaba bien; el error
estaba en `engine/live.py`, que ordenaba a los participantes por puntos y luego
por id de jugador, ignorando BH1/BH/AROC1/DE.

Esta prueba construye un Suizo donde hay empate a puntos y el desempate manda:

  - 6 jugadores, 3 rondas, todas las partidas ganadas por las negras.
  - El motor ordena: 4, 6, 2 (los tres con 2 puntos) y luego 1, 3, 5.
  - Ordenar por (puntos, id) daría: 2, 4, 6 · 1, 3, 5.

Si alguien vuelve a ordenar por id, esta prueba falla.

No necesita navegador ni datos reales.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from engine import live as lv
from engine import state as st
from engine import tournaments as tm

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:120]) if extra != "" else ""))


def suizo_con_empate():
    """Suizo de 6 jugadores y 3 rondas, con las negras ganando siempre."""
    state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
    for i in range(1, 7):
        tm.create_player(state, f"Jugador {i}", mun="Falcón", cat="Sub-14",
                         rhythm="Rapid", rating=1500, rd=200)
    tm.create_tournament(state, "Suizo Empate", 1, "Rapid", 3,
                         player_ids=[1, 2, 3, 4, 5, 6],
                         date_start="2026-03-01 10:00:00")
    torneo = state["tournaments"][0]
    for ronda in range(1, 4):
        tm.pair_next_round(state, int(torneo["id"]))
        juegos = [g for g in torneo["games"]
                  if int(g["round"]) == ronda and not g.get("bye")]
        resultados = [{"game_id": int(g["id"]), "result": 0.0} for g in juegos]
        tm.save_results(state, int(torneo["id"]), resultados)
    return state, torneo


print("== 1. El motor ordena por desempate (BH1), no por id ==")
state, torneo = suizo_con_empate()
filas = st.standings(state, torneo, rating_mode="tournament_end")
orden_motor = [f.jugador_id for f in filas]
chk("el motor pone primero al de mejor BH1 entre los empatados",
    orden_motor[:3] == [4, 6, 2], orden_motor)
chk("los tres primeros empatan a puntos", len({filas[i].puntos for i in range(3)}) == 1,
    [filas[i].puntos for i in range(3)])
chk("el BH1 del primero es mayor que el del tercero",
    filas[0].buchholz_cut1 > filas[2].buchholz_cut1,
    [filas[i].buchholz_cut1 for i in range(3)])
chk("el orden NO coincide con el de solo id (es el bug de antes)",
    orden_motor[:3] != sorted(orden_motor[:3]), orden_motor[:3])

print("== 2. La web pública usa ese mismo orden ==")
live = lv.build_live(state)
t = live.get("torneo") or {}
ids_web = []
for j in t.get("jugadores", []):
    nombre = j.get("n", "")
    pid = next((f.jugador_id for f in filas if f.nombre == nombre), None)
    ids_web.append(pid)
chk("la web pública devuelve a todos los jugadores", len(ids_web) == 6, ids_web)
chk("la web pública respeta el orden del motor", ids_web == orden_motor, ids_web)
chk("los puestos (r) van 1..6 en orden", [j.get("r") for j in t.get("jugadores", [])] == [1, 2, 3, 4, 5, 6],
    [j.get("r") for j in t.get("jugadores", [])])
chk("cada jugador aparece una sola vez", len(set(ids_web)) == len(ids_web), ids_web)

print("== 3. Los desempates que se muestran son los del motor ==")
por_nombre = {f.nombre: f for f in filas}
ok_des = True
for j in t.get("jugadores", []):
    f = por_nombre.get(j.get("n"))
    de = j.get("desempates") or {}
    if f is None or abs(de.get("buchholz_cut1", -1) - f.buchholz_cut1) > 1e-9:
        ok_des = False
chk("el BH1 de cada fila coincide con el del motor", ok_des,
    [(j.get("n"), (j.get("desempates") or {}).get("buchholz_cut1")) for j in t.get("jugadores", [])][:3])

print("== 4. Un torneo vacío o sin filas no rompe la web ==")
vacio = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
live_vacio = lv.build_live(vacio)
chk("sin torneos la web sigue respondiendo", live_vacio.get("torneo") is None, live_vacio.get("torneo"))

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
