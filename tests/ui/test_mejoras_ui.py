import json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from seed import seed_path
SEED = seed_path()
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT)
os.chdir(ROOT)
from server import store
import api.index as api
from engine import state as st
from engine import tournaments as tm

class FakeStore:
    def __init__(self):
        self.state=json.load(open(SEED)); self.state.pop('live',None)
        self.state.setdefault('next_ids',{}); self.live={}; self.version=1
        self.admin={"name":"Test","pin_hash":store.hash_pin("1234","sal"),"pin_salt":"sal"}
        self.sessions={"tok-test":{"token":"tok-test","last_seen":datetime.now(timezone.utc).isoformat()}}
    def get_state_row(self): return {"state":self.state,"version":self.version,"updated_at":"now"}
    def save_state_row(self,state,live,version): self.state=state; self.live=live; self.version=version+1; return {"version":self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self,pin,name="A"): return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok-test"
    def create_session(self,token): pass
    def get_session(self,token): return self.sessions.get(token)
    def touch_session(self,token): pass
    def delete_session(self,token): pass
    def update_admin_pin(self,pin): pass
fake=FakeStore()
for n in ['get_state_row','save_state_row','get_live','get_admin','create_admin','count_recent_failures','add_failed_login','clear_logins','new_token','create_session','get_session','touch_session','delete_session','update_admin_pin']:
    setattr(store,n,getattr(fake,n))
store.MAX_FAILED_LOGINS=5; store.session_is_valid=lambda s: bool(s)

# torneo suizo (id alto) y round robin 2 vueltas (el último = "actual")
suizo=tm.create_tournament(fake.state,"Suizo X",1,"Blitz",player_ids=[p['id'] for p in fake.state['players'][:4]])
tm.pair_next_round(fake.state,suizo['id'])
r1=[g for g in suizo['games'] if int(g['round'])==1 and not g.get('bye')]
tm.save_results(fake.state,suizo['id'],[{"game_id":g["id"],"result":1.0 if i%2==0 else 0.0} for i,g in enumerate(r1)])
rr=tm.create_tournament(fake.state,"RR 2V X",3,"Blitz",player_ids=[p['id'] for p in fake.state['players'][4:8]])

class H(api.handler, SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'): return api.handler.do_GET(self)
        return SimpleHTTPRequestHandler.do_GET(self)
    def do_POST(self):
        if self.path.startswith('/api'): return api.handler.do_POST(self)
        self.send_error(501)
    def log_message(self,*a): pass
srv=ThreadingHTTPServer(('127.0.0.1',0),H); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{port}'
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from cdp import Chrome
ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")
profile=RESULT_DIR + '/chrome-mej'; shutil.rmtree(profile,ignore_errors=True)
c=Chrome(profile, window='412,915')
def heads(sel):
    return c.evaluate(f"(()=>{{const t=document.querySelector('{sel}');return t?[...t.querySelectorAll('thead th')].map(x=>x.textContent.trim()).join('|'):''}})()")
try:
    c.navigate(base+'/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Test');")
    c.cmd('Page.reload'); time.sleep(3)
    print("== Torneo actual: Round Robin 2 vueltas (Blitz) ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()"); time.sleep(0.8)
    h=heads('#app details table')
    print('   columnas:', h)
    chk('muestra DE, W y SB", solo los del RR 2V', 'DE' in h and 'W' in h and 'SB' in h, h)
    chk('NO muestra BH1/BH/AROC1/Koya', 'BH1' not in h and 'AROC1' not in h and 'Koya' not in h, h)
    chk('columna "Rend. est." en vez de TPR', 'Rend. est.' in h and 'TPR' not in h, h)
    chk('aviso de que son estimados', 'estimación' in c.evaluate("(()=>{const d=[...document.querySelectorAll('#app details')].find(x=>x.querySelector('table'));return d?d.textContent:''})()"))
    print("== Historial: el torneo Formation Suizo ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('hist'))?.click()"); time.sleep(0.8)
    c.evaluate("(()=>{const fila=[...document.querySelectorAll('#app .game')].find(g=>g.textContent.includes('Suizo X'));const b=fila&&[...fila.querySelectorAll('button')].find(x=>x.textContent.trim()==='Ver');if(b)b.click()})()"); time.sleep(1.5)
    h2=heads('#app details table')
    print('   columnas:', h2)
    chk('suizo muestra BH1, BH, AROC1 y DE', all(x in h2 for x in ('BH1','BH','AROC1','DE')), h2)
    chk('suizo NO muestra SB/W/Koya', 'SB' not in h2 and 'Koya' not in h2, h2)
    print("== Impresión ==")
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Imprimir')?.click()"); time.sleep(2.0)
    ph=c.evaluate("(()=>{const t=document.querySelector('#printArea table');return t?[...t.querySelectorAll('thead th')].map(x=>x.textContent.trim()).join('|'):''})()")
    print('   columnas impresas:', ph)
    chk('impresión con solo los criterios del torneo', 'BH1' in ph and 'DE' in ph and 'SB' not in ph, ph)
    chk('impresión con "Rend. est."', 'Rend. est.' in ph and 'TPR' not in ph, ph)
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
