import base64, json, os, sys, threading, time, shutil
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
profile=RESULT_DIR + '/chrome-club'; shutil.rmtree(profile,ignore_errors=True)
c=Chrome(profile, window='412,915')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    c.navigate(base+'/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Test');")
    c.cmd('Page.reload'); time.sleep(3)
    # capturar descargas
    c.evaluate("""window.__dl=[];const oc=HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click=function(){window.__dl.push({name:this.download,href:this.href})};
      window.__dlText=async(u)=>{const r=await fetch(u);return await r.text()};const ot=URL.createObjectURL;
      URL.createObjectURL=function(b){window.__blob=b;return ot.call(URL,b)};""")

    print("== 1. Ordenar la tabla de jugadores ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()"); time.sleep(0.8)
    nombres0=c.evaluate("Array.from(document.querySelectorAll('#playerTable tr')).map(r=>r.dataset.name)")
    chk('la lista existe', len(nombres0)>3, len(nombres0))
    sel=c.evaluate("(()=>{const s=document.querySelector('select[aria-label=\"Ordenar la tabla de jugadores\"]');return s?s.getAttribute('aria-label'):''})()")
    chk('hay selector de orden', bool(sel), sel)
    c.evaluate("(()=>{const s=document.querySelector('select[aria-label=\"Ordenar la tabla de jugadores\"]');s.value='rapid';s.dispatchEvent(new Event('change',{bubbles:true}))})()")
    time.sleep(0.7)
    nombres1=c.evaluate("Array.from(document.querySelectorAll('#playerTable tr')).map(r=>r.dataset.name)")
    ratings = c.evaluate("Array.from(document.querySelectorAll('#playerTable tr')).map(r => { const b = r.querySelectorAll('td')[3] ? r.querySelectorAll('td')[3].querySelector('b') : null; return b ? parseFloat(b.textContent) || 0 : 0; })")
    chk('queda de mayor a menor rating', all(ratings[i]>=ratings[i+1] for i in range(len(ratings)-1)), ratings[:6])
    c.evaluate("(()=>{const b=[...document.querySelectorAll('#app button')].find(x=>x.getAttribute('aria-label')==='Cambiar el sentido del orden');if(b)b.click()})()")
    time.sleep(0.7)
    ratings2 = c.evaluate("Array.from(document.querySelectorAll('#playerTable tr')).map(r => { const b = r.querySelectorAll('td')[3] ? r.querySelectorAll('td')[3].querySelector('b') : null; return b ? parseFloat(b.textContent) || 0 : 0; })")

    print("== 2. Exportar a CSV ==")
    c.evaluate("exportarJugadoresCSV()"); time.sleep(0.6)
    d=c.evaluate("window.__dl[window.__dl.length-1]||null")
    chk('descarga un archivo CSV', bool(d) and d['name'].endswith('.csv'), d)
    bom=c.evaluate("(async()=>{const r=await fetch(window.__dl[window.__dl.length-1].href);const b=new Uint8Array(await r.arrayBuffer());return Array.from(b.slice(0,3))})()")
    chk('lleva BOM (Excel en español)', bom==[239,187,191], bom)
    txt=c.evaluate("window.__dlText(window.__dl[window.__dl.length-1].href)")
    chk('separador ";"', txt.count(';')>10)
    chk('cabeceras de jugadores', 'Nombre;Categoría;Municipio' in txt, txt.split('\r\n')[0][:80])
    chk('columnas de los 3 ritmos', 'Rapid rating' in txt and 'Bullet partidas' in txt)
    chk('una fila por jugador', len([l for l in txt.split('\r\n') if l.strip()])>5)
    # clasificación
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()"); time.sleep(0.8)
    c.evaluate("exportarClasificacionCSV(dashboard.current)"); time.sleep(0.6)
    d2=c.evaluate("window.__dl[window.__dl.length-1]||null")
    chk('CSV de la clasificación', bool(d2) and 'clasificacion' in d2['name'], d2)
    txt2=c.evaluate("window.__dlText(window.__dl[window.__dl.length-1].href)")
    chk('cabeceras con los desempates del torneo', 'Puesto;Jugador' in txt2 and 'BH1' in txt2, txt2.split('\r\n')[0][:90])
    # matches
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('mat'))?.click()"); time.sleep(0.8)
    c.evaluate("exportarMatchesCSV()"); time.sleep(0.6)
    d3=c.evaluate("window.__dl[window.__dl.length-1]||null")
    chk('CSV de los matches', bool(d3) and 'matches' in d3['name'], d3)

    print("== 3. Ficha del jugador ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()"); time.sleep(0.8)
    pid=c.evaluate("""(async()=>{for(const tr of document.querySelectorAll('#playerTable tr')){
        const id=Number(tr.dataset.id);
        const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json','x-token':'tok-test'},body:JSON.stringify({action:'player_history',player_id:id})});
        const j=await r.json();
        if((j.torneos||[]).length>0) return id;
      } return Number(document.querySelector('#playerTable tr').dataset.id);})()""")
    c.evaluate(f"abrirFichaJugador({pid})"); time.sleep(1.8)
    chk('la ficha se abre', c.evaluate("!!document.querySelector('.modal--ficha')") is True)
    if not c.evaluate("!!document.querySelector('.modal--ficha')"):
        print('   DEPURACIÓN modal:', c.evaluate("document.getElementById('modalWrap').innerText.slice(0,200)"))
        print('   DEPURACIÓN errores:', c.evaluate("window.__errs||[]"))
        print('   DEPURACIÓN respuesta cruda:', c.evaluate("fetch('/api',{method:'POST',headers:{'Content-Type':'application/json','x-token':'tok-test'},body:JSON.stringify({action:'player_history',player_id:Number(document.querySelector('#playerTable tr').dataset.id)})}).then(r=>r.text()).catch(e=>String(e))"))
    ftxt=c.evaluate("document.querySelector('.modal--ficha') ? document.querySelector('.modal--ficha').innerText : ''")
    for k in ["Ficha del jugador","Ratings por ritmo","Torneos","Partidas","Rivales más frecuentes","Editar","Cerrar"]:
        chk(f"contiene: {k}", k.lower() in ftxt.lower())
    chk('muestra la foto o iniciales', c.evaluate("!!document.querySelector('.modal--ficha .avatar')") is True)
    shot=c.cmd('Page.captureScreenshot', format='png')['data']
    open(RESULT_DIR + '/ficha_jugador.png','wb').write(base64.b64decode(shot))
    # editar desde la ficha
    c.evaluate("editarDesdeFicha(Number(document.querySelector('#playerTable tr').dataset.id))"); time.sleep(1.0)
    chk('el botón Editar abre el formulario', c.evaluate("(document.querySelector('#app h2')||{}).textContent")=='Editar jugador')
    chk('la ficha se cerró', c.evaluate("!document.querySelector('.modal--ficha')") is True)
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
