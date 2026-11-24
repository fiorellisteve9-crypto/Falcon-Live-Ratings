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

    print("== 4. Ocultar un jugador del ranking público ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()"); time.sleep(0.8)
    pid2=c.evaluate("Number(document.querySelector('#playerTable tr').dataset.id)")
    fila_sel=f"document.querySelector('#playerTable tr[data-id=\"{pid2}\"]')"
    chk('la fila trae el botón Ocultar', 'Ocultar' in (c.evaluate(f"({fila_sel}||{{}}).innerText||''") or ''),
        (c.evaluate(f"({fila_sel}||{{}}).innerText||''") or '')[:60])
    c.evaluate(f"togglePlayerHidden({pid2})"); time.sleep(1.8)
    fila=c.evaluate(f"(()=>{{const tr={fila_sel};return tr?{{txt:tr.innerText,cls:tr.className}}:null}})()")
    chk('la fila muestra la pill Oculto', bool(fila) and 'Oculto' in fila['txt'], (fila or {}).get('txt','')[:80])
    chk('la fila queda atenuada', bool(fila) and 'player-hidden' in fila['cls'], (fila or {}).get('cls'))
    chk('el botón ahora dice Mostrar', bool(fila) and 'Mostrar' in fila['txt'])
    oculto=c.evaluate(f"(dashboard.players||[]).find(p=>Number(p.id)==={pid2})?.hidden")
    chk('el panel lo guarda como oculto', int(oculto or 0)==1, oculto)
    c.evaluate(f"abrirFichaJugador({pid2})"); time.sleep(1.8)
    ftxt2=c.evaluate("document.querySelector('.modal--ficha')?document.querySelector('.modal--ficha').innerText:''")
    chk('la ficha avisa de que está oculto', 'oculto en el ranking' in ftxt2.lower(), ftxt2[:90])
    chk('la ficha ofrece volver a mostrarlo', 'mostrar en el ranking' in ftxt2.lower())
    c.evaluate(f"togglePlayerHidden({pid2}, true)"); time.sleep(2.0)
    chk('vuelve a mostrarse en el ranking',
        int(c.evaluate(f"(dashboard.players||[]).find(p=>Number(p.id)==={pid2})?.hidden||0") or 0)==0)
    fila2=c.evaluate(f"({fila_sel}||{{}}).innerText||''")
    chk('la pill Oculto desaparece', 'Oculto' not in (fila2 or ''), (fila2 or '')[:60])
    chk('la fila deja de estar atenuada',
        'player-hidden' not in (c.evaluate(f"({fila_sel}||{{}}).className") or ''))

    print("== 5. Categoría automática por año de nacimiento ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()"); time.sleep(0.8)
    chk('el formulario pide el año, no la categoría',
        c.evaluate("!!document.getElementById('pBirth') && !document.getElementById('pCat')") is True)
    anio=datetime.now().year; nac=anio-14; nac2=anio-16
    c.evaluate(f"""(()=>{{
      document.getElementById('pName').value='Prueba Cat'; playerForm.name='Prueba Cat';
      const i=document.getElementById('pBirth'); i.value='{nac}';
      i.dispatchEvent(new Event('input',{{bubbles:true}}));
    }})()""")
    chk('la vista previa calcula Sub-14',
        'Sub-14' in (c.evaluate("document.getElementById('pCatPreview').textContent") or ''),
        c.evaluate("document.getElementById('pCatPreview').textContent"))
    c.evaluate("savePlayer()"); time.sleep(1.8)
    nuevo=c.evaluate("(dashboard.players||[]).find(p=>p.name==='Prueba Cat')||null")
    chk('se creó el jugador', bool(nuevo), nuevo)
    if nuevo:
        chk('guarda el año de nacimiento', int(nuevo.get('birth_year') or 0)==nac, nuevo.get('birth_year'))
        chk('guarda la categoría calculada', nuevo.get('cat')=='Sub-14', nuevo.get('cat'))
        chk('la tabla muestra la categoría',
            'Sub-14' in (c.evaluate("(()=>{const r=[...document.querySelectorAll('#playerTable tr')].find(x=>x.dataset.name==='Prueba Cat');return r?r.innerText:''})()") or ''))
        print("== 6. Editar el año recalcula la categoría ==")
        c.evaluate(f"startEditPlayer({nuevo['id']})"); time.sleep(0.8)
        chk('el formulario trae el año guardado',
            c.evaluate("document.getElementById('pBirth').value")==str(nac),
            c.evaluate("document.getElementById('pBirth').value"))
        c.evaluate(f"""(()=>{{const i=document.getElementById('pBirth');i.value='{nac2}';
          i.dispatchEvent(new Event('input',{{bubbles:true}}));}})()""")
        chk('la vista previa pasa a Sub-16',
            'Sub-16' in (c.evaluate("document.getElementById('pCatPreview').textContent") or ''),
            c.evaluate("document.getElementById('pCatPreview').textContent"))
        c.evaluate("savePlayer()"); time.sleep(1.8)
        editado=c.evaluate(f"(dashboard.players||[]).find(p=>Number(p.id)==={nuevo['id']})||null")
        chk('la categoría se recalculó al guardar', (editado or {}).get('cat')=='Sub-16', (editado or {}).get('cat'))
        chk('el año quedó actualizado', int((editado or {}).get('birth_year') or 0)==nac2,
            (editado or {}).get('birth_year'))
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
