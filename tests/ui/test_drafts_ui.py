import sys, os, json, threading, subprocess, time, re
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
os.chdir(ROOT)
from server import store
import api.index as api
from engine import state as st

class FakeStore:
    def __init__(self):
        self.state=json.load(open(SEED)); self.state.pop('live',None)
        self.state.setdefault('next_ids',{})
        self.live={}; self.version=1
        self.admin={"name":"Test","pin_hash":store.hash_pin("1234","sal"),"pin_salt":"sal"}
        self.sessions={"tok-test":{"token":"tok-test","last_seen":datetime.now(timezone.utc).isoformat()}}
    def get_state_row(self): return {"state":self.state,"version":self.version,"updated_at":"now"}
    def save_state_row(self,state,live,version): self.state=state; self.live=live; self.version=version+1; return {"version":self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self,pin,name="Admin"): return self.admin
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
store.MAX_FAILED_LOGINS=5
store.session_is_valid=lambda s: bool(s)

WRAP='''<!doctype html><html><head><meta charset="utf-8"></head><body><div id="out">loading</div><script>
localStorage.setItem('falconAdminToken','tok-test');
localStorage.setItem('falconAdminName','Test');
const f=document.createElement('iframe'); f.style.width='100%'; f.style.height='900px'; f.src='/admin.html'; document.body.appendChild(f);
const start=Date.now();
const t=setInterval(()=>{
  try{
    if(f.contentWindow && typeof f.contentWindow.setTab==='function' && f.contentDocument.querySelectorAll('#tabs .tab').length>0){
      clearInterval(t);
      const w=f.contentWindow, d=f.contentDocument, R={};
      const sleep=ms=>new Promise(r=>setTimeout(r,ms));
      const clickText=(txt,scope)=>[...(scope||d).querySelectorAll('button')].find(b=>b.textContent.trim()===txt);
      (async()=>{
        try{
          R.tabs=[...d.querySelectorAll('#tabs .tab')].map(b=>b.textContent.trim());
          w.setTab('inscripciones'); await sleep(400);
          R.titulo=(d.querySelector('#app h2')||{}).textContent||'';
          // crear pre-registro
          const nameEl=d.querySelector('#dName'); nameEl.value='Copa Fin de Año'; nameEl.dispatchEvent(new Event('input',{bubbles:true}));
          const dateEl=d.querySelector('#dDate'); if(dateEl){dateEl.value='2027-03-15'; dateEl.dispatchEvent(new Event('change',{bubbles:true}));}
          await sleep(200);
          clickText('Crear pre-registro', d.querySelector('#app')).click();
          await sleep(1200);
          R.detalle=(d.querySelector('#app h2')||{}).textContent||'';
          R.contadores=(d.querySelector('#app')||{}).innerText.match(/Inscriptos \\(\\d+\\)/i);
          // agregar nombre nuevo
          const inp=d.querySelector('#daName'); inp.value='Niño Prueba'; inp.dispatchEvent(new Event('input',{bubbles:true}));
          await sleep(150);
          clickText('Agregar a la lista', d.querySelector('#app')).click();
          await sleep(1000);
          R.trasNuevo=((d.querySelector('#app')||{}).innerText.match(/Inscriptos \\(\\d+\\)/i)||[])[0];
          // agregar jugador existente
          const sel=d.querySelector('#app select');
          const opts=[...sel.options].filter(o=>o.value);
          sel.value=opts[0].value; sel.dispatchEvent(new Event('change',{bubbles:true}));
          await sleep(600);
          clickText('Agregar a la lista', d.querySelector('#app')).click();
          await sleep(1000);
          R.trasExistente=((d.querySelector('#app')||{}).innerText.match(/Inscriptos \\(\\d+\\)/i)||[])[0];
          R.lista=d.querySelector('#app table') ? d.querySelector('#app table').innerText.replace(/\\s+/g,' ').slice(0,140) : '';
          // activar
          clickText('Activar torneo', d.querySelector('#app')).click();
          await sleep(600);
          R.modalActivar=!!d.querySelector('#modalWrap.show');
          const okBtn=[...d.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Activar');
          if(okBtn) okBtn.click();
          await sleep(1800);
          R.tabTrasActivar=((d.querySelector('#tabs .tab.active')||{}).textContent||'').trim();
          R.tituloTorneo=(d.querySelector('#app h2')||{}).textContent||'';
          R.emparejar=!![...d.querySelectorAll('#app button')].find(b=>/Emparejar ronda/.test(b.textContent));
          // volver a Inscripciones: no debe quedar ningún pre-registro
          w.setTab('inscripciones'); await sleep(700);
          R.hayInscripciones=((d.querySelector('#app')||{}).innerText.match(/Pre-registros abiertos \((\d+)\)/i)||[])[1];
          // comprobar que el jugador nuevo existe
          w.setTab('jugadores'); await sleep(700);
          const tbl=d.querySelector('#app table');
          R.jugadorNuevo=!!tbl && tbl.innerText.includes('Niño Prueba');
        }catch(e){ R.error=String(e)+' @'+(e.stack||'').split('\\n')[1]; }
        document.getElementById('out').textContent=JSON.stringify(R);
      })();
    }
  }catch(e){}
  if(Date.now()-start>40000){clearInterval(t);document.getElementById('out').textContent='timeout';}
},200);
</script></body></html>'''

class Combined(api.handler, SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'): return api.handler.do_GET(self)
        if self.path.startswith('/test_drafts'):
            body=WRAP.encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        return SimpleHTTPRequestHandler.do_GET(self)
    def do_POST(self):
        if self.path.startswith('/api'): return api.handler.do_POST(self)
        self.send_error(501)

srv=ThreadingHTTPServer(('127.0.0.1',0),Combined); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
out=RESULT_DIR + '/dom_drafts.html'
cmd=['chromium-browser','--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
     '--window-size=412,915','--virtual-time-budget=40000',f'--user-data-dir={RESULT_DIR}/chrome-dr-{int(time.time())}',
     '--dump-dom',f'http://127.0.0.1:{port}/test_drafts.html']
with open(out,'w') as fh:
    subprocess.run(cmd,stdout=fh,stderr=subprocess.DEVNULL,timeout=120)
dom=open(out,encoding='utf-8').read()
m=re.search(r'<div id="out">(.*?)</div>',dom,re.S)
try: R=json.loads(m.group(1))
except Exception:
    print('NO JSON:', (m.group(1) if m else dom[-400:])[:600]); sys.exit(1)
ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")
print("== UI INSCRIPCIONES ==")
chk('pestaña Inscripciones', 'Inscripciones' in (R.get('tabs') or []), R.get('tabs'))
chk('vista de pre-registro', R.get('titulo')=='Pre-registro', R.get('titulo'))
chk('abre el detalle al crear', R.get('detalle')=='Copa Fin de Año', R.get('detalle'))
chk('agrega nombre nuevo', (R.get('trasNuevo') or '').lower()=='inscriptos (1)', R.get('trasNuevo'))
chk('agrega jugador existente', (R.get('trasExistente') or '').lower()=='inscriptos (2)', R.get('trasExistente'))
chk('lista muestra el inscrito nuevo', 'Niño Prueba' in (R.get('lista') or ''), R.get('lista'))
chk('pide confirmación al activar', R.get('modalActivar') is True)
chk('tras activar va a Torneo', R.get('tabTrasActivar')=='Torneo', R.get('tabTrasActivar'))
chk('puede emparejar la ronda 1', R.get('emparejar') is True)
chk('torneo activo visible', R.get('tituloTorneo')=='Copa Fin de Año', R.get('tituloTorneo'))
chk('sin pre-registros pendientes', str(R.get('hayInscripciones'))=='0', R.get('hayInscripciones'))
chk('creó el jugador nuevo', R.get('jugadorNuevo') is True)
if R.get('error'): print('  ERROR JS:', R['error'])
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
