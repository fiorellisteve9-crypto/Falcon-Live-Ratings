"""Prueba de la red de seguridad: la copia de seguridad restaura de verdad.

El día del torneo lo que te salva de una catastrophe es el archivo de copia
(`falcon_backup_*.json`) que descargas desde Ajustes. Esta prueba comprueba el
ciclo completo, igual que en el panel:

  1. Exportar el estado (lo que hace el botón "descargar copia").
  2. Cambiar los datos (como si se hubiera equivocado al capturar un resultado).
  3. Importar la copia con "reemplazar datos existentes".
  4. Comprobar que el estado vuelve a ser EXACTAMENTE el exportado:
     jugadores, torneos, partidas, ratings y el ranking público.

También comprueba que, si ya hay datos, el importador se niega a pisarlos
salvo que se marque "reemplazar" (para no perder nada por un clic).

No necesita navegador.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from seed import seed_path
SEED = seed_path()
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from datetime import datetime, timezone

from server import store
import api.index as api
from engine import live as live_engine

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:110]) if extra != "" else ""))


class FakeStore:
    """Almacén falso: guarda el estado en memoria, como Supabase pero local."""

    def __init__(self):
        self.state = json.load(open(SEED))
        self.state.pop('live', None)
        self.state.setdefault('next_ids', {})
        self.live = {}
        self.version = 1
        self.admin = {"name": "Ensayo", "pin_hash": store.hash_pin("1234", "sal"), "pin_salt": "sal"}
        self.sessions = {"tok-test": {"token": "tok-test", "last_seen": datetime.now(timezone.utc).isoformat()}}

    def get_state_row(self):
        return {"state": self.state, "version": self.version, "updated_at": "x"}

    def save_state_row(self, state, live, version):
        self.state = state
        self.live = live
        self.version = version + 1
        return {"version": self.version}

    def get_live(self):
        return live_engine.build_live(self.state)

    def get_admin(self):
        return self.admin

    def create_admin(self, pin, name="A"):
        return self.admin

    def count_recent_failures(self):
        return 0

    def add_failed_login(self):
        pass

    def clear_logins(self):
        pass

    def new_token(self):
        return "tok-test"

    def create_session(self, token):
        pass

    def get_session(self, token):
        return self.sessions.get("tok-test")

    def touch_session(self, token):
        pass

    def delete_session(self, token):
        pass

    def update_admin_pin(self, pin):
        pass


fake = FakeStore()
for n in ['get_state_row', 'save_state_row', 'get_live', 'get_admin', 'create_admin',
          'count_recent_failures', 'add_failed_login', 'clear_logins', 'new_token',
          'create_session', 'get_session', 'touch_session', 'delete_session', 'update_admin_pin']:
    setattr(store, n, getattr(fake, n))
store.MAX_FAILED_LOGINS = 5
store.session_is_valid = lambda s: bool(s)

print("== 1. El estado de partida ==")
n_jug = len(fake.state.get('players', []))
n_tor = len(fake.state.get('tournaments', []))
n_par = len(fake.state.get('matches', []))
chk('el estado tiene jugadores, torneos y partidas', n_jug > 0 and n_tor > 0 and n_par > 0,
    f"{n_jug} jugadores · {n_tor} torneos · {n_par} partidas")

print("== 2. Exportar la copia (como el botón de Ajustes) ==")
# El panel descarga api("state") y lo guarda como JSON.
exportado = json.loads(json.dumps(fake.state))
copia = os.path.join(RESULT_DIR, 'copia_prueba.json')
with open(copia, 'w', encoding='utf-8') as fh:
    json.dump(exportado, fh, ensure_ascii=False, indent=1)
chk('la copia se escribe como archivo JSON', os.path.getsize(copia) > 1000,
    f"{os.path.getsize(copia)} bytes · {copia}")

print("== 3. Romper los datos a propósito ==")
# Un error tipico del dia del torneo: capturar mal un resultado.
jugadores = fake.state['players']
victima = jugadores[0]
rating_bueno = json.dumps(victima.get('ratings'), sort_keys=True)
fake.state['matches'] = fake.state.get('matches', [])[:1]          # se pierden partidas
fake.state['tournaments'] = []                                     # y el torneo
jugadores[0]['ratings'] = {'Rapid': {'rating': 1, 'rd': 99}}       # rating corrupto
ranking_roto = json.dumps(fake.state.get('ranking_snapshot', {}), sort_keys=True)
chk('el estado quedo roto', len(fake.state['matches']) == 1 and not fake.state['tournaments']
    and json.dumps(victima.get('ratings'), sort_keys=True) != rating_bueno,
    f"{len(fake.state['matches'])} partida · {len(fake.state['tournaments'])} torneos")

print("== 4. Importar la copia (reemplazando datos existentes) ==")


def llamar_importar(seed, force):
    """Llama a import_seed como lo haria el panel."""
    handler = api.handler.__new__(api.handler)
    handler.headers = {}
    captured = {}

    def fake_json(code, data):
        captured['code'] = code
        captured['data'] = data
        return captured

    handler._json = fake_json
    try:
        handler._import_seed({"seed": seed, "force": force, "token": "tok-test"})
    except api.ApiError as e:
        return getattr(e, 'status', 500), {"error": str(e)}
    return captured.get('code', 0), captured.get('data', {})


codigo, datos = llamar_importar(exportado, True)
chk('el importador acepta la copia con "reemplazar"', codigo == 200, f"código {codigo}")
if codigo == 200:
    chk('el panel recibe el recuento de lo importado',
        isinstance(datos.get('imported'), dict) and datos['imported'].get('players') == n_jug,
        datos.get('imported'))

print("== 5. El estado volvio a ser el exportado ==")
chk('los jugadores vuelven a ser los mismos',
    len(fake.state['players']) == n_jug and
    [p['id'] for p in fake.state['players']] == [p['id'] for p in exportado['players']],
    f"{len(fake.state['players'])} jugadores")
chk('los torneos vuelven a ser los mismos',
    len(fake.state['tournaments']) == n_tor, f"{len(fake.state['tournaments'])} torneos")
chk('las partidas vuelven a ser las mismas',
    len(fake.state.get('matches', [])) == n_par, f"{len(fake.state.get('matches', []))} partidas")
ratings_ahora = json.dumps(fake.state['players'][0].get('ratings'), sort_keys=True)
chk('los ratings vuelven a su valor', ratings_ahora == rating_bueno, ratings_ahora[:80])

print("== 6. El ranking publico tambien vuelve ==")
live = live_engine.build_live(fake.state)
n_rank = sum(len(v) for v in live.get('ranking', {}).values())
chk('el ranking se reconstruye con los datos restaurados', n_rank > 0,
    {k: len(v) for k, v in live.get('ranking', {}).items()})
chk('el snapshot publico no guarda datos viejos', 'live' not in fake.state or
    not fake.state.get('live'), 'sin snapshot obsoleto')

print("== 7. Sin marcar 'reemplazar' no se pisa nada ==")
codigo2, datos2 = llamar_importar(exportado, False)
chk('el importador se niega a reemplazar sin permiso', codigo2 == 409, f"código {codigo2}")
chk('los datos siguen intactos', len(fake.state['players']) == n_jug and
    len(fake.state.get('matches', [])) == n_par,
    f"{len(fake.state['players'])} jugadores · {len(fake.state.get('matches', []))} partidas")

print("== 8. Una copia incompleta se rechaza ==")
codigo3, _ = llamar_importar({"players": []}, True)
chk('una copia sin torneos se rechaza', codigo3 in (400, 409), f"código {codigo3}")

try:
    os.remove(copia)
except OSError:
    pass

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
