"""El snapshot público guardado se regenera cuando cambia el formato.

La web pública no calcula el JSON en cada visita: `/api?action=live` sirve el
snapshot que quedó guardado en Supabase la última vez que se guardó el estado.
Por eso, si se arregla algo en `engine/live.py` pero no se sube `LIVE_SCHEMA`,
la web sigue mostrando el resultado viejo (fue justo lo que pasó con el orden
de la clasificación: el código estaba arreglado y la web seguía igual).

Esta prueba comprueba las dos caras:

  1. Snapshot con `_schema` viejo  -> la API lo regenera desde el estado, lo
     guarda y devuelve el bueno (con el orden por desempates).
  2. Snapshot ya al día            -> no se regenera ni se escribe nada.

No necesita navegador.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from server import store
import api.index as api
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
        tm.save_results(state, int(torneo["id"]),
                        [{"game_id": int(g["id"]), "result": 0.0} for g in juegos])
    return state


class FakeStore:
    """Almacén falso en memoria, como Supabase pero local."""

    def __init__(self, state, live):
        self.state = state
        self.live = live
        self.version = 7
        self.guardados = []

    def get_state_row(self):
        return {"state": self.state, "version": self.version, "updated_at": "x"}

    def save_state_row(self, state, live, version):
        self.guardados.append(live)
        self.live = live
        self.version = int(version) + 1
        return {"version": self.version}

    def get_live(self):
        return self.live


def parchear_store(fake):
    for nombre in ("get_state_row", "save_state_row", "get_live"):
        setattr(store, nombre, getattr(fake, nombre))


def llamar_live():
    handler = api.handler.__new__(api.handler)
    handler.headers = {}
    capturado = {}

    def fake_json(code, data, cache=None):
        capturado["code"] = code
        capturado["data"] = data
        return capturado

    handler._json = fake_json
    handler._live()
    return capturado["code"], capturado["data"]


def orden_del_payload(payload):
    t = payload.get("torneo") or {}
    return [j.get("n") for j in t.get("jugadores", [])]


state = suizo_con_empate()
torneo = state["tournaments"][0]
filas = st.standings(state, torneo, rating_mode="tournament_end")
orden_bueno = [f.nombre for f in filas]

print("== 1. Snapshot viejo: la API lo regenera ==")
chk("el formato actual del snapshot es el nuevo", lv.LIVE_SCHEMA >= 3, lv.LIVE_SCHEMA)
viejo = {"_schema": lv.LIVE_SCHEMA - 1, "torneo": {"nombre": "viejo", "jugadores": []},
         "ranking": {}, "matches": []}
fake = FakeStore(state, viejo)
parchear_store(fake)
codigo, datos = llamar_live()
chk("la API responde 200", codigo == 200, codigo)
chk("el snapshot vuelve con el formato nuevo", int(datos.get("_schema") or 0) == lv.LIVE_SCHEMA,
    datos.get("_schema"))
chk("la clasificación sale en el orden del motor (desempates)", orden_del_payload(datos) == orden_bueno,
    orden_del_payload(datos))
chk("el snapshot regenerado se guarda en la base", len(fake.guardados) == 1,
    len(fake.guardados))
chk("lo guardado es lo mismo que se sirve", fake.live is datos, "mismo objeto")

print("== 2. Snapshot al día: no se toca ==")
al_dia = lv.build_live(state)
fake2 = FakeStore(state, al_dia)
parchear_store(fake2)
codigo2, datos2 = llamar_live()
chk("la API responde 200", codigo2 == 200, codigo2)
chk("no se regenera ni se escribe nada", len(fake2.guardados) == 0, len(fake2.guardados))
chk("se sirve el snapshot guardado tal cual", datos2 is al_dia, "mismo objeto")

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
