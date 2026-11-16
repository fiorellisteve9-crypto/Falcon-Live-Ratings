import json, os, sys, threading, time, shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from cdp import Chrome
REPO=ROOT; os.chdir(REPO)
LIVE={"timestamp":"2026-11-08T12:00:00",
 "ranking":{"Rapid":[{"e":1500,"n":"Jugador Prueba","p":3,"r":1,"v":12,"dr":0,"sp":[1490,1500],"cat":"Sub-12","mun":"Falcón","flag":"🇻🇪"}],"Blitz":[],"Bullet":[]},
 "torneo":None,"torneo_partidas":[],"matches":[],"historial":[]}
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'):
            b=json.dumps(LIVE).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        return SimpleHTTPRequestHandler.do_GET(self)
    def log_message(self,*a): pass
srv=ThreadingHTTPServer(('127.0.0.1',0),H); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{port}'
profile=RESULT_DIR + '/chrome-pub-cdp'; shutil.rmtree(profile,ignore_errors=True)
ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")
c=Chrome(profile, window='1400,1000')
try:
    c.cmd('Runtime.enable'); c.cmd('Log.enable')
    c.navigate(base+'/')
    time.sleep(4)
    chk('titulo', c.evaluate("document.title")=='Falcón Live Ratings')
    chk('Chart.js local cargado', c.evaluate("typeof Chart !== 'undefined'") is True)
    c.evaluate("document.querySelector('#rankingWrap .prow').click()")
    time.sleep(2)
    chk('el perfil del jugador abre', 'RATINGS POR RITMO' in c.evaluate("document.body.innerText"), c.evaluate("document.body.innerText.slice(0,60).replace(String.fromCharCode(10),' ')"))
    c.evaluate("history.back()")
    chk('ranking pintado', c.evaluate("document.querySelectorAll('#rankingWrap .prow, #rankingWrap table tbody tr').length")>0)
    chk('sin Google Fonts', 'fonts.googleapis.com' not in c.evaluate("document.documentElement.innerHTML"))
    chk('sin jsDelivr', 'cdn.jsdelivr.net' not in c.evaluate("document.documentElement.innerHTML"))
    chk('manifest enlazado', c.evaluate("!!document.querySelector('link[rel=manifest]')"))
    chk('sw registrado', c.evaluate("navigator.serviceWorker.getRegistration('/').then(r=>!!r)") is True)
    errs=c.evaluate("window.__errs ? window.__errs.length : 0")
    chk('sin errores JS globales', errs==0, errs)
finally:
    c.close(); shutil.rmtree(profile,ignore_errors=True)
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
