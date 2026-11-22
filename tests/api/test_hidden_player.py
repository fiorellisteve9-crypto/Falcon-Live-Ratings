"""Ocultar un jugador desde el panel (API): `player_update` con `hidden`.

La prueba hace la llamada real del panel (acción `player_update` con
`{player_id, hidden: true}`) y comprueba las dos caras:

  1. El panel sigue recibiendo al jugador, marcado con `hidden: 1`, y el resto
     de sus datos (nombre, categoría, rating, partidas) queda intacto.
  2. El ranking público (`live`) deja de incluir al jugador oculto, y vuelve
     cuando se manda `hidden: false`.

No necesita navegador.
"""
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
from engine import tournaments as tm

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:120]) if extra != "" else ""))


class FakeStore:
    """Almacén falso en memoria, con sesión de administrador ya abierta."""

    def __init__(self, state):
        self.state = state
        self.live = {}
        self.version = 4
        self.sessions = {"tok": {"token": "tok",
                                 "last_seen": datetime.now(timezone.utc).isoformat()}}

    def get_state_row(self):
        return {"state": self.state, "live": self.live,
                "version": self.version, "updated_at": "x"}

    def save_state_row(self, state, live, version):
        self.state = state
        self.live = live
        self.version = int(version) + 1
        return {"version": self.version}

    def get_live(self):
        return self.live

    def get_session(self, token):
        return self.sessions.get(token)

    def touch_session(self, token):
        pass


def estado():
    state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
    for i, nombre in enumerate(["Ana", "Beto", "Carla"]):
        tm.create_player(state, nombre, mun="Falcón", cat="Sub-14",
                         rhythm="Rapid", rating=1500 + i * 25, rd=200)
    for j1, j2, r in [(1, 2, 1.0), (2, 3, 0.5), (3, 1, 0.0)]:
        tm.create_match(state, j1, j2, "Rapid", [r], "2026-03-01 10:00:00")
    return state


def llamar_player_update(body):
    handler = api.handler.__new__(api.handler)
    handler.headers = {"x-token": "tok"}
    capturado = {}

    def fake_json(code, data, cache=None):
        capturado["code"] = code
        capturado["data"] = data
        return capturado

    handler._json = fake_json
    handler._player_update(body)
    return capturado["code"], capturado["data"]


state = estado()
fake = FakeStore(state)
for nombre in ("get_state_row", "save_state_row", "get_live",
               "get_session", "touch_session"):
    setattr(store, nombre, getattr(fake, nombre))
store.session_is_valid = lambda s: bool(s)

beto_antes = dict(tm.player_by_id(state, 2))
rating_antes = lv._rating(beto_antes, "Rapid")

print("== 1. Ocultar a Beto desde el panel ==")
codigo, datos = llamar_player_update({"player_id": 2, "hidden": True})
chk("la API responde 200", codigo == 200, codigo)
jug = datos.get("player") or {}
chk("el jugador vuelve marcado como oculto", int(jug.get("hidden") or 0) == 1, jug.get("hidden"))

panel = {int(p["id"]): p for p in (datos.get("dashboard") or {}).get("players", [])}
chk("sigue en el panel (no se borra)", 2 in panel, sorted(panel.keys()))
chk("el panel lo marca como oculto", int(panel[2].get("hidden") or 0) == 1, panel[2].get("hidden"))
chk("el nombre no cambia", panel[2].get("name") == beto_antes.get("name"), panel[2].get("name"))
chk("la categoría no cambia", panel[2].get("cat") == beto_antes.get("cat"), panel[2].get("cat"))
chk("las partidas siguen contadas", int(panel[2].get("partidas_total") or 0) == 2,
    panel[2].get("partidas_total"))
chk("el rating no cambia",
    abs(lv._rating(panel[2], "Rapid") - rating_antes) < 1e-9,
    lv._rating(panel[2], "Rapid"))

print("== 2. El ranking público ya no lo incluye ==")
live = fake.live
nombres = [row["n"] for row in (live.get("ranking") or {}).get("Rapid", [])]
chk("Beto no sale en el ranking público", "Beto" not in nombres, nombres)
chk("los demás sí salen", sorted(nombres) == ["Ana", "Carla"], nombres)
chk("los puestos van 1..2 sin huecos",
    [row["r"] for row in live["ranking"]["Rapid"]] == [1, 2],
    [row["r"] for row in live["ranking"]["Rapid"]])

print("== 3. Volver a mostrarlo ==")
codigo, datos = llamar_player_update({"player_id": 2, "hidden": False})
chk("la API responde 200", codigo == 200, codigo)
chk("el jugador queda visible", int((datos.get("player") or {}).get("hidden") or 0) == 0,
    (datos.get("player") or {}).get("hidden"))
nombres = [row["n"] for row in (fake.live.get("ranking") or {}).get("Rapid", [])]
chk("Beto vuelve al ranking público", "Beto" in nombres, nombres)

print("== 4. Editar el jugador sin tocar `hidden` lo deja como está ==")
llamar_player_update({"player_id": 2, "hidden": True})
codigo, datos = llamar_player_update({"player_id": 2, "mun": "Coro"})
jug = datos.get("player") or {}
chk("el municipio sí cambia", jug.get("mun") == "Coro", jug.get("mun"))
chk("sigue oculto (editar no lo destapa)", int(jug.get("hidden") or 0) == 1, jug.get("hidden"))

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
