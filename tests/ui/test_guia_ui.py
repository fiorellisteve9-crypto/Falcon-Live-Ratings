import json, os, sys, threading, time, shutil, base64
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
# torneo en curso para que la guía salga con contenido
t=tm.create_tournament(fake.state,"Suizo Demo",1,"Blitz",player_ids=[p['id'] for p in fake.state['players'][:6]])
tm.pair_next_round(fake.state,t['id'])
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
profile=RESULT_DIR + '/chrome-guia'; shutil.rmtree(profile,ignore_errors=True)
c=Chrome(profile, window='412,915')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    c.navigate(base+'/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Test');")
    c.cmd('Page.reload'); time.sleep(3)
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()"); time.sleep(0.8)
    chk('la guía está en la pestaña Torneo', c.evaluate("!!document.getElementById('guiaTorneo')") is True)
    chk('empieza plegada', c.evaluate("document.getElementById('guiaTorneo').open") is False)
    txt=c.evaluate("document.getElementById('guiaTorneo').textContent")
    for k in ["trampa del orden","Descargar copia","Emparejar ronda","Cada toque guarda solo","Faltan","Cerrar torneo","tarjeta de imagen","Imprimir","no recalcula los ratings"]:
        chk(f"contiene: {k}", k.lower() in txt.lower())
    # abrir la guía
    c.evaluate("document.querySelector('#guiaTorneo summary').click()"); time.sleep(0.6)
    chk('se abre al tocarla', c.evaluate("document.getElementById('guiaTorneo').open") is True)
    shot=c.cmd('Page.captureScreenshot', format='png')['data']
    open(RESULT_DIR + '/guia_torneo.png','wb').write(base64.b64decode(shot))
    # desde Ajustes
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('ajus'))?.click()"); time.sleep(0.7)
    chk('botón en Ajustes', c.evaluate("[...document.querySelectorAll('#app button')].some(b=>b.textContent.includes('Guía del torneo'))") is True)
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.includes('Guía del torneo')).click()"); time.sleep(1.0)
    chk('vuelve a Torneo con la guía abierta', c.evaluate("document.getElementById('guiaTorneo') && document.getElementById('guiaTorneo').open") is True)
    # sin desbordes
    sw=c.evaluate("document.documentElement.scrollWidth")
    chk('sin desborde horizontal', sw<=392, sw)
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
