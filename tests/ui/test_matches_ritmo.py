import base64, json, os, sys, threading, time, shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from seed import seed_path
SEED = seed_path()
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
from cdp import Chrome
REPO=ROOT; os.chdir(REPO)
def side(n,score,ei,ef,v): return {"n":n,"cat":"Absoluta","mun":"Falcón","score":score,"ei":ei,"ef":ef,"v":v}
LIVE={"timestamp":"2026-11-09T12:00:00",
 "ranking":{"Rapid":[{"e":2212,"n":"Elvis Urbina","r":1,"v":26,"p":24,"dr":0,"sp":[2100,2200,2212],"cat":"Absoluta","mun":"Falcón","flag":"🇻🇪"}],"Blitz":[],"Bullet":[]},
 "torneo":None,"torneo_partidas":[],
 "matches":[
   {"ritmo":"Blitz","np":12,"fecha":"2026-08-09 18:00:00","j1":side("Elvis Urbina",7,2000,2040,40),"j2":side("Joaquín Guanipa",5,1900,1880,-20)},
   {"ritmo":"Rapid","np":2,"fecha":"2026-07-25 20:00:00","j1":side("Elvis Urbina",1,2050,2030,-20),"j2":side("Natasha Perozo",1,1700,1720,20)},
   {"ritmo":"Bullet","np":3,"fecha":"2026-06-10 21:00:00","j1":side("Jimena Guanipa",2,1400,1425,25),"j2":side("Elvis Urbina",1,2100,2075,-25)}
 ],
 "historial":{"Elvis Urbina":{"torneos":[],"partidas":[],"oponentes":[],"totales":[{"ritmo":"General","w":20,"d":5,"l":11,"total":36,"pct":"63%"}]}}}
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'):
            b=json.dumps(LIVE).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        return SimpleHTTPRequestHandler.do_GET(self)
    def log_message(self,*a): pass
srv=ThreadingHTTPServer(('127.0.0.1',0),H); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{port}'
profile=RESULT_DIR + '/chrome-mritmo'; shutil.rmtree(profile,ignore_errors=True)
ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")
c=Chrome(profile, window='412,915')
try:
    c.navigate(base+'/'); time.sleep(5)
    c.evaluate("document.querySelector('.prow').click()"); time.sleep(3)
    chk('perfil abierto', 'MATCHES JUGADOS' in c.evaluate("document.body.innerText").upper())
    heads=c.evaluate("Array.from(document.querySelectorAll('#matchesTable thead th')).map(t=>t.textContent.trim()).join('|')")
    chk('columna Ritmo en la cabecera', 'Ritmo' in heads, heads)
    rows=c.evaluate("Array.from(document.querySelectorAll('#matchesTable tbody tr.match-row')).map(tr=>Array.from(tr.querySelectorAll('td')).map(td=>td.textContent.trim()).join(' | '))")
    print('   filas:', rows)
    chk('3 matches listados', len(rows)==3, len(rows))
    chk('muestra Blitz', any('Blitz' in r for r in rows))
    chk('muestra Rapid', any('Rapid' in r for r in rows))
    chk('muestra Bullet', any('Bullet' in r for r in rows))
    chk('cada fila trae fecha y ritmo y partidas', all(len(r.split('|'))>=6 for r in rows), [len(r.split('|')) for r in rows])
    # color de la etiqueta
    col=c.evaluate("(()=>{const s=document.querySelector('#matchesTable .mtag-ritmo');return s?getComputedStyle(s).color:''})()")
    chk('etiqueta con color del ritmo', col not in ('', 'rgb(154, 154, 154)'), col)
    # captura del perfil desplazado a la sección
    c.evaluate("document.getElementById('matchesTable').scrollIntoView({block:'center'})")
    time.sleep(0.8)
    shot=c.cmd('Page.captureScreenshot', format='png')['data']
    open(RESULT_DIR + '/matches_ritmo.png','wb').write(base64.b64decode(shot))
finally:
    c.close(); shutil.rmtree(profile,ignore_errors=True)
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
