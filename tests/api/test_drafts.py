import sys, os, json, threading, urllib.request, urllib.error
from datetime import datetime, timezone

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from seed import seed_path
SEED = seed_path()
sys.path.insert(0, ROOT)
os.environ['SETUP_TOKEN']='setup123'
from server import store
import api.index as api
from engine import state as st
from engine import tournaments as tm
from engine import live as lv

ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")

print("== Motor: pre-registro ==")
s=st.new_state()
p1=tm.create_player(s,"Ana Pérez","Falcón","Sub-12")
p2=tm.create_player(s,"Luis Gómez","Falcón","Sub-14")
d=tm.create_draft(s,"Copa Navidad",2,"Blitz",date_start="2026-12-20")
chk('crea borrador', d.get('draft') is True and d['name']=="Copa Navidad")
chk('no hay torneo real', all(t.get('draft') for t in s['tournaments']))
t=tm.add_draft_entry(s,d['id'],player_id=p1['id'])
chk('agrega jugador existente', len(t['entries'])==1 and t['entries'][0]['player_id']==p1['id'])
t=tm.add_draft_entry(s,d['id'],name="María Nueva",cat="Sub-10",mun="Falcón")
chk('agrega nombre nuevo', len(t['entries'])==2 and t['entries'][1]['player_id'] is None)
try:
    tm.add_draft_entry(s,d['id'],name="maría nueva")
    chk('rechaza duplicado por nombre', False)
except tm.TournamentError as e:
    chk('rechaza duplicado por nombre', 'inscrito' in str(e).lower(), str(e))
try:
    tm.add_draft_entry(s,d['id'],name="luis gómez")
    chk('rechaza nombre de jugador existente', False)
except tm.TournamentError as e:
    chk('rechaza nombre de jugador existente', 'jugador' in str(e).lower(), str(e))
try:
    tm.create_draft(s,"copa navidad",1,"Blitz")
    chk('rechaza nombre repetido', False)
except tm.TournamentError as e:
    chk('rechaza nombre repetido', 'ya existe' in str(e).lower(), str(e))
live=lv.build_live(s)
chk('el borrador no sale en el JSON público', live['torneo'] is None, live['torneo'])
tourn=tm.activate_draft(s,d['id'])
chk('activa: torneo real', tourn.get('draft') is None and tourn.get('finished') is False)
chk('activa: 2 participantes', len(tourn['participants'])==2, len(tourn['participants']))
chk('activa: crea el jugador nuevo', any(p['name']=="María Nueva" for p in s['players']))
chk('activa: elimina el borrador', all(not x.get('draft') for x in s['tournaments']))
chk('activa: fecha prevista (pasada/futura)', tourn['date_start'][:10] in ('2026-12-20', datetime.now().strftime('%Y-%m-%d')), tourn['date_start'])
live=lv.build_live(s)
chk('tras activar ya aparece en el público', (live['torneo'] or {}).get('nombre')=="Copa Navidad")
chk('rating inicial desde el slot', all(p['rating_start']==1500.0 for p in tourn['participants']))
# borrar borrador
d2=tm.create_draft(s,"Otro futuro",1,"Rapid")
tm.delete_draft(s,d2['id'])
chk('elimina borrador', all(x['id']!=d2['id'] for x in s['tournaments']))

print("== API: pre-registro ==")
class FakeStore:
    def __init__(self):
        self.state=st.new_state(); self.live={}; self.version=1
        self.admin=None; self.sessions={}
    def get_state_row(self): return {"state":self.state,"version":self.version,"updated_at":"now"}
    def save_state_row(self,state,live,version):
        self.state=state; self.live=live; self.version=version+1; return {"version":self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self,pin,name="Admin"):
        self.admin={"name":name,"pin_hash":store.hash_pin(pin,"sal"),"pin_salt":"sal"}; return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok"
    def create_session(self,token): self.sessions[token]={"token":token,"last_seen":datetime.now(timezone.utc).isoformat()}
    def get_session(self,token): return self.sessions.get(token)
    def touch_session(self,token): pass
    def delete_session(self,token): pass
    def update_admin_pin(self,pin): pass
fake=FakeStore()
for n in ['get_state_row','save_state_row','get_live','get_admin','create_admin','count_recent_failures',
          'add_failed_login','clear_logins','new_token','create_session','get_session','touch_session',
          'delete_session','update_admin_pin']:
    setattr(store,n,getattr(fake,n))
store.MAX_FAILED_LOGINS=5
store.session_is_valid=lambda x: bool(x)
from http.server import HTTPServer
srv=HTTPServer(('127.0.0.1',0), api.handler); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
def post(action, token=None, **kw):
    body={"action":action, **kw}
    req=urllib.request.Request(f'http://127.0.0.1:{port}/api', data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json', **({'x-token':token} if token else {})}, method='POST')
    try:
        r=urllib.request.urlopen(req,timeout=25); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
post('setup', setup_token='setup123', pin='1234')
code,r=post('login', pin='1234'); token=r['token']
code,r=post('player_create', token=token, name='Base Uno'); 
code,r=post('player_create', token=token, name='Base Dos')
code,r=post('draft_create', token=token, name='Futuro API', type=2, rhythm='Rapid', date_start='2027-01-10')
chk('draft_create 200', code==200, (code, r.get('error')))
dash=r['dashboard']; did=dash['drafts'][0]['id']
chk('dashboard.drafts', len(dash['drafts'])==1 and dash['drafts'][0]['name']=='Futuro API')
chk('current no cambia con borrador', dash['current'] is None, dash['current'])
code,r=post('draft_entry_add', token=token, draft_id=did, name='Invitado Uno', cat='Sub-12', mun='Falcón')
chk('entry_add nuevo 200', code==200, r.get('error'))
players=[p['id'] for p in fake.state['players']]
code,r=post('draft_entry_add', token=token, draft_id=did, player_id=players[0])
chk('entry_add existente 200', code==200, r.get('error'))
chk('2 inscriptos', len(r['dashboard']['drafts'][0]['entries'])==2)
eid=r['dashboard']['drafts'][0]['entries'][0]['id']
code,r=post('draft_entry_remove', token=token, draft_id=did, entry_id=eid)
chk('entry_remove 200', code==200 and len(r['dashboard']['drafts'][0]['entries'])==1, r.get('error'))
code,r=post('draft_entry_add', token=token, draft_id=did, name='Invitado Dos')
chk('re-agrega para activar', code==200 and len(r['dashboard']['drafts'][0]['entries'])==2)
code,r=post('draft_activate', token=token, draft_id=did)
chk('draft_activate 200', code==200, r.get('error'))
chk('current es el torneo nuevo', (r['dashboard']['current'] or {}).get('name')=='Futuro API', (r['dashboard']['current'] or {}).get('nombre'))
chk('sin borradores', r['dashboard']['drafts']==[])
chk('se creó el jugador invitado', any(p['name']=='Invitado Dos' for p in fake.state['players']))
code,r=post('draft_create', token=token, name='X', type=1, rhythm='Blitz')
did2=r['dashboard']['drafts'][0]['id']
code,r=post('draft_delete', token=token, draft_id=did2)
chk('draft_delete 200', code==200 and r['dashboard']['drafts']==[], r.get('error'))
code,r=post('draft_create', name='Sin token', type=1, rhythm='Blitz')
chk('exige token', code==401, code)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
