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
from engine import state as st
from engine import live as lv
class FakeStore:
    def __init__(self):
        self.state=json.load(open(SEED)); self.state.pop('live',None)
        self.state.setdefault('next_ids',{}); self.live={}; self.version=1
        self.admin={"name":"Test","pin_hash":store.hash_pin("1234","sal"),"pin_salt":"sal"}
        self.sessions={"tok-test":{"token":"tok-test","last_seen":datetime.now(timezone.utc).isoformat()}}
    def get_state_row(self): return {"state":self.state,"version":self.version,"updated_at":"now"}
    def save_state_row(self,state,live,version): self.state=state; self.live=live; self.version=version+1; return {"version":self.version}
    def get_live(self):
        from engine import live as lvv
        return lvv.build_live(self.state)
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
profile=RESULT_DIR + '/chrome-pubdes'; shutil.rmtree(profile,ignore_errors=True)
c=Chrome(profile, window='412,915')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    c.navigate(base+'/'); time.sleep(5)
    c.evaluate("[...document.querySelectorAll('#tabs .tab-btn')].find(b=>b.dataset.v==='torneo')?.click()"); time.sleep(1.2)
    print('   DEBUG API torneo:', c.evaluate("fetch('/api?action=live').then(r=>r.json()).then(j=>JSON.stringify({c:j.torneo.criterios,d:j.torneo.jugadores[0].desempates,n:j.torneo.jugadores[0].n}))"))
    print('   DEBUG criterios:', c.evaluate("(()=>{const d=(typeof data!=='undefined')?data:null;return d&&d.torneo?JSON.stringify(d.torneo.criterios):'sin data'})()"))
    print('   DEBUG desempates:', c.evaluate("(()=>{const d=(typeof data!=='undefined')?data:null;return d&&d.torneo&&d.torneo.jugadores[0]?JSON.stringify(d.torneo.jugadores[0].desempates):'-'})()"))
    print('   DEBUG torneo actual API:', c.evaluate("fetch('/api?action=live').then(r=>r.json()).then(j=>j.torneo.nombre)"))
    print('   DEBUG torneo en pantalla:', c.evaluate("(()=>{const e=document.querySelector('#torneoWrap')?document.querySelector('#torneoWrap').previousElementSibling:null;return e?e.innerText.replace(/\\s+/g,' ').slice(0,90):'-'})()"))
    print('   DEBUG existe .trow-tb:', c.evaluate("!!document.querySelector('.trow-tb')"))
    print('   DEBUG html fila:', c.evaluate("(()=>{const r=document.querySelector('.trow');return r?r.innerHTML.includes('trow-tb')+' | '+r.innerHTML.slice(0,160):''})()"))
    print('   DEBUG fila:', c.evaluate("(()=>{const r=document.querySelector('.trow');return r?r.innerText.replace(/\\s+/g,' ').slice(0,140):'sin fila'})()"))
    line=c.evaluate("(()=>{const e=document.querySelector('.trow-tb');return e?e.innerText.replace(/\\s+/g,' ').trim():''})()")
    chk('la fila muestra los desempates', bool(line), line)
    chk('incluye DE y SB y W', 'DE' in line and 'SB' in line and 'W' in line, line)
    chk('no incluye Pts (ya está aparte)', 'Pts' not in line, line)
    shot=c.cmd('Page.captureScreenshot', format='png')['data']
    open(RESULT_DIR + '/publico_desempates.png','wb').write(base64.b64decode(shot))
    # deep link del atajo "Jugadores"
    c.navigate(base+'/?tab=ranking'); time.sleep(4)
    activa=c.evaluate("(()=>{const b=document.querySelector('#tabs .tab-btn.active');return b?b.dataset.v:''})()")
    chk('atajo ?tab=ranking abre el ranking', activa=='ranking', activa)
    chk('la URL se limpia', c.evaluate("location.search")=='', c.evaluate("location.search"))
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
