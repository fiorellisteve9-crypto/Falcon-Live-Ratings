import sys, os, json, threading, urllib.request, urllib.error
from datetime import datetime, timezone

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
os.environ['SETUP_TOKEN'] = 'setup123'

from server import store
import api.index as api
from engine import state as st

class FakeStore:
    def __init__(self):
        self.state = st.new_state(); self.live = {}; self.version = 1
        self.admin = None; self.sessions = {}
    def get_state_row(self):
        return {"state": self.state, "live": self.live, "version": self.version, "updated_at": "now"}
    def save_state_row(self, state, live, version):
        self.state = state; self.live = live; self.version = version + 1
        return {"version": self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self, pin, name="Administrador"):
        self.admin = {"name": name, "pin_hash": store.hash_pin(pin, "sal"), "pin_salt": "sal"}
        return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok-test"
    def create_session(self, token):
        self.sessions[token] = {"token": token, "last_seen": datetime.now(timezone.utc).isoformat()}
    def get_session(self, token): return self.sessions.get(token)
    def touch_session(self, token): pass
    def delete_session(self, token): self.sessions.pop(token, None)
    def update_admin_pin(self, pin):
        self.admin["pin_hash"] = store.hash_pin(pin, self.admin["pin_salt"])

fake = FakeStore()
for name in ['get_state_row','save_state_row','get_live','get_admin','create_admin','count_recent_failures',
             'add_failed_login','clear_logins','new_token','create_session','get_session','touch_session',
             'delete_session','update_admin_pin']:
    setattr(store, name, getattr(fake, name))
store.MAX_FAILED_LOGINS = 5
store.session_is_valid = lambda s: bool(s)

from http.server import HTTPServer
srv = HTTPServer(('127.0.0.1', 0), api.handler); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

def post(action, token=None, **kw):
    body = {"action": action, **kw}
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api', data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', **({'x-token': token} if token else {})}, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=20); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

ok = True
def chk(label, cond, extra=""):
    global ok
    if not cond: ok = False
    print(("  OK  " if cond else " FALLA") + f" {label} {extra}")

post('setup', setup_token='setup123', pin='1234')
code, r = post('login', pin='1234'); token = r['token']
seed = json.load(open(SEED))
post('import_seed', token=token, seed=seed)

print("== match_update ==")
code, r = post('match_create', token=token, player1_id=2, player2_id=5, rhythm='Blitz',
               results=[1, 0, 0.5], date='2026-08-09')
mid = r['match']['id']
chk('match creado', code == 200, code)
r0 = r['match']['rating_final_p1']
code, r = post('match_update', token=token, match_id=mid, results=[0, 1, 1], date='2026-08-09')
chk('match_update 200', code == 200, (code, r.get('error')))
chk('marcador corregido', r['match']['score_p1'] == 1.0 and r['match']['score_p2'] == 2.0,
    (r['match']['score_p1'], r['match']['score_p2']))
chk('rating recalculado', abs(r['match']['rating_final_p1'] - r0) > 0.001, (r0, r['match']['rating_final_p1']))
chk('guarda el detalle de partidas', r['match'].get('resultados') == [0.0, 1.0, 1.0], r['match'].get('resultados'))
code, r = post('match_update', token=token, match_id=mid, results=[1, 0], date='2026-12-01')
chk('rechaza fecha futura', code == 400 and 'futura' in str(r.get('error')), r.get('error'))
code, r = post('match_update', token=token, match_id=99999, results=[1])
chk('rechaza match inexistente', code == 400 and 'no encontrado' in str(r.get('error')), r.get('error'))
code, r = post('match_update', match_id=mid, results=[1])
chk('exige token', code == 401, code)

print("== match_delete ==")
code, r = post('match_create', token=token, player1_id=2, player2_id=5, rhythm='Blitz',
               results=[1, 1, 1], date='2026-08-20')
mid2 = r['match']['id']
code, r = post('match_delete', token=token, match_id=mid2)
chk('match_delete 200', code == 200, (code, r.get('error')))
ids = [m['id'] for m in fake.state['matches']]
chk('match eliminado del estado', mid2 not in ids, ids)
code, r = post('match_delete', token=token, match_id=mid2)
chk('rechaza borrar dos veces', code == 400, code)

print("== player_update rating/RD ==")
code, r = post('player_create', token=token, name='Editable', mun='Falcón', cat='-',
               rhythm='Blitz', rating=1500, rd=500)
pid = r['player']['id']
chk('jugador creado', code == 200, code)
code, r = post('player_update', token=token, player_id=pid, name='Editable', mun='Falcón', cat='-',
               rhythm='Blitz', rating=2186, rd=99.23)
chk('player_update 200', code == 200, (code, r.get('error')))
chk('rating corregido', abs(r['player']['ratings']['Blitz']['rating'] - 2186) < 1e-9, r['player']['ratings']['Blitz']['rating'])
chk('RD corregido', abs(r['player']['ratings']['Blitz']['rd'] - 99.23) < 1e-9, r['player']['ratings']['Blitz']['rd'])
chk('variación reiniciada', r['player']['ratings']['Blitz']['var'] == 0, r['player']['ratings']['Blitz']['var'])
code, r = post('player_update', token=token, player_id=pid, name='Editable', rhythm='Blitz', rating=500)
chk('rechaza rating fuera de rango', code == 400 and '600' in str(r.get('error')), r.get('error'))
code, r = post('player_update', token=token, player_id=pid, name='Editable', rating=2000)
chk('rechaza rating sin ritmo', code == 400 and 'ritmo' in str(r.get('error')), r.get('error'))
code, r = post('player_update', token=token, player_id=pid, name='Editable', rhythm='Rapid', rating=1800)
chk('acepta corregir solo un ritmo', code == 200 and abs(r['player']['ratings']['Rapid']['rating'] - 1800) < 1e-9
    and abs(r['player']['ratings']['Blitz']['rating'] - 2186) < 1e-9,
    (r.get('player',{}).get('ratings',{}).get('Rapid',{}).get('rating'), r.get('player',{}).get('ratings',{}).get('Blitz',{}).get('rating')))

code, r = post('player_update', token=token, player_id=pid, name='Editable Solo Nombre', mun='Falcón', cat='-')
chk('editar solo nombre no manda rating', code == 200, (code, r.get('error')))

print("== dashboard con datos nuevos ==")
code, r = post('dashboard', token=token)
p = [x for x in r['players'] if x['id'] == pid]
chk('dashboard incluye partidas por jugador', p and 'partidas' in p[0] and 'partidas_total' in p[0], (p or [{}])[0].get('partidas'))
m = [x for x in r['matches'] if x['id'] == mid]
chk('dashboard incluye detalle de partidas', m and 'resultados' in m[0], (m or [{}])[0].get('resultados'))
chk('dashboard incluye ids de jugadores', m and m[0].get('jugador1_id') == 2, (m or [{}])[0].get('jugador1_id'))

srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
