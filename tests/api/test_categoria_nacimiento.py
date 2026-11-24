"""Categoría automática por año de nacimiento, vista desde la API.

Comprueba que el panel puede crear y editar jugadores mandando `birth_year`
en vez de `cat`, que el ranking público recibe la categoría calculada y que
un cambio de año regenera el snapshot guardado sin que nadie toque nada.

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
from engine import tournaments as tm

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:120]) if extra != "" else ""))


class FakeStore:
    def __init__(self, state):
        self.state = state
        self.live = {}
        self.version = 3
        self.guardados = []
        self.sessions = {"tok": {"token": "tok",
                                 "last_seen": datetime.now(timezone.utc).isoformat()}}

    def get_state_row(self):
        return {"state": self.state, "live": self.live,
                "version": self.version, "updated_at": "x"}

    def save_state_row(self, state, live, version):
        self.state = state
        self.live = live
        self.version = int(version) + 1
        self.guardados.append(live)
        return {"version": self.version}

    def get_live(self):
        return self.live

    def get_session(self, token):
        return self.sessions.get(token)

    def touch_session(self, token):
        pass


def estado():
    state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
    nacido = tm._anio_actual() - 14
    j1 = tm.create_player(state, "Ana", mun="Falcón", birth_year=nacido)
    j2 = tm.create_player(state, "Beto", mun="Falcón", birth_year=nacido)
    tm.create_match(state, j1["id"], j2["id"], "Rapid", [1.0], "2026-03-01 10:00:00")
    return state


def llamar(metodo, body):
    handler = api.handler.__new__(api.handler)
    handler.headers = {"x-token": "tok"}
    capturado = {}

    def fake_json(code, data, cache=None):
        capturado["code"] = code
        capturado["data"] = data
        return capturado

    handler._json = fake_json
    funcion = getattr(handler, metodo)
    if metodo == "_live":
        funcion()
    else:
        funcion(body)
    return capturado["code"], capturado["data"]


state = estado()
fake = FakeStore(state)
for nombre in ("get_state_row", "save_state_row", "get_live",
               "get_session", "touch_session"):
    setattr(store, nombre, getattr(fake, nombre))
store.session_is_valid = lambda s: bool(s)

anio = tm._anio_actual()
nacido = anio - 14  # 14 años -> Sub-14 con la regla de año simple

print("== 1. Crear jugador con año de nacimiento ==")
codigo, datos = llamar("_player_create", {"name": "Carla", "mun": "Coro", "birth_year": nacido,
                                          "cat": "Senior"})
chk("la API responde 200", codigo == 200, codigo)
jug = datos.get("player") or {}
chk("guarda el año", int(jug.get("birth_year") or 0) == nacido, jug.get("birth_year"))
chk("calcula la categoría (ignora la 'cat' vieja que pudiera llegar)",
    jug.get("cat") == tm.categoria_por_nacimiento(nacido), jug.get("cat"))
panel = {int(p["id"]): p for p in (datos.get("dashboard") or {}).get("players", [])}
chk("el panel recibe el año y la categoría",
    int(panel[3].get("birth_year") or 0) == nacido and panel[3].get("cat") == "Sub-14",
    (panel[3].get("birth_year"), panel[3].get("cat")))

print("== 2. El ranking público lleva la categoría ==")
cats = [row.get("cat") for row in (fake.live.get("ranking") or {}).get("Rapid", [])]
chk("los dos jugadores con partidas salen con su categoría", len(cats) == 2, cats)
chk("la categoría es la calculada", all(c == "Sub-14" for c in cats), cats)

print("== 3. Editar el año ==")
nacido2 = anio - 16  # 16 años -> Sub-16
codigo, datos = llamar("_player_update", {"player_id": 1, "birth_year": nacido2, "mun": "Punto Fijo"})
chk("la API responde 200", codigo == 200, codigo)
jug = datos.get("player") or {}
chk("recalcula la categoría", jug.get("cat") == "Sub-16", jug.get("cat"))
chk("el municipio también cambia", jug.get("mun") == "Punto Fijo", jug.get("mun"))
chk("el nombre no se toca", jug.get("name") == "Ana", jug.get("name"))
cats = [row.get("cat") for row in (fake.live.get("ranking") or {}).get("Rapid", [])]
chk("el snapshot público ya trae la categoría nueva", cats == ["Sub-16", "Sub-14"], cats)

print("== 4. Borrar el año conserva la categoría ==")
codigo, datos = llamar("_player_update", {"player_id": 1, "birth_year": "", "cat": "Senior"})
jug = datos.get("player") or {}
chk("sin año, queda la categoría que venga del panel", jug.get("cat") == "Senior", jug.get("cat"))
chk("el año queda vacío", jug.get("birth_year") is None, jug.get("birth_year"))

print("== 5. Cambio de año: el snapshot se regenera solo ==")
# Dejamos a Ana otra vez con año (Sub-14), como estaba antes de borrárselo.
llamar("_player_update", {"player_id": 1, "birth_year": nacido})
antes = len(fake.guardados)
anio_real = tm._anio_actual
tm._anio_actual = lambda: anio + 1
try:
    codigo, datos = llamar("_live", {})
    chk("la API responde 200", codigo == 200, codigo)
    chk("se regeneró el snapshot", len(fake.guardados) == antes + 1,
        len(fake.guardados) - antes)
    cats = [row.get("cat") for row in (datos.get("ranking") or {}).get("Rapid", [])]
    chk("categorías ya del año nuevo", all(c == "Sub-16" for c in cats), cats)
    chk("una segunda visita no vuelve a escribir", (llamar("_live", {}) or True) and
        len(fake.guardados) == antes + 1, len(fake.guardados) - antes)
finally:
    tm._anio_actual = anio_real

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
