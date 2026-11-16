import sys, os, json, threading, subprocess, time, re, base64
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
os.environ['SUPABASE_URL']='https://demo.supabase.co'
os.chdir(ROOT)
from server import store
import api.index as api

class FakeStore:
    def __init__(self):
        self.state=json.load(open(SEED)); self.state.pop('live',None)
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

UPLOADS=[]; DELETES=[]
def fake_upload(path, payload, ctype):
    UPLOADS.append({'path':path,'size':len(payload),'type':ctype})
    open(RESULT_DIR + '/uploaded_photo.bin','wb').write(payload)
    return store.photo_public_url(path)
def fake_delete(url):
    DELETES.append(url); return True
store.upload_photo=fake_upload
store.delete_photo=fake_delete

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
      (async()=>{
        try{
          w.setTab('jugadores'); await sleep(250);
          // Editar el primer jugador
          const editBtn=[...d.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Editar');
          editBtn.click(); await sleep(300);
          R.hayPreview=!!d.querySelector('#pFotoPrev');
          R.hayBotonSubir=!!d.querySelector('#pFotoUploadBtn');
          R.hayInputFile=!!d.querySelector('#pFotoFile');
          R.hayInputUrl=!!d.querySelector('#pFoto');
          // Elegir una imagen grande (1600x1200) -> debe reducirse a 512x512
          const mk=async()=>{
            const cv=document.createElement('canvas'); cv.width=1600; cv.height=1200;
            const g=cv.getContext('2d');
            const gr=g.createLinearGradient(0,0,1600,1200); gr.addColorStop(0,'#8BC34A'); gr.addColorStop(1,'#1565C0');
            g.fillStyle=gr; g.fillRect(0,0,1600,1200);
            g.fillStyle='#fff'; g.font='bold 220px sans-serif'; g.fillText('FC',600,700);
            const b=await new Promise(r=>cv.toBlob(r,'image/png'));
            return new File([b],'foto grande.png',{type:'image/png'});
          };
          const file=await mk();
          const dt=new DataTransfer(); dt.items.add(file);
          const inp=d.querySelector('#pFotoFile'); inp.files=dt.files;
          inp.dispatchEvent(new Event('change',{bubbles:true}));
          await sleep(2500);
          R.previewImg=!!d.querySelector('#pFotoPrev img');
          R.srcPreview=(d.querySelector('#pFotoPrev img')||{}).src||'';
          R.msg=(d.querySelector('#toast')||{}).textContent||'';
          // Quitar la foto
          const quit=[...d.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Quitar');
          quit.click(); await sleep(1200);
          R.trasQuitar=!!d.querySelector('#pFotoPrev img');
          R.toastQuitar=(d.querySelector('#toast')||{}).textContent||'';
        }catch(e){ R.error=String(e)+' @'+(e.stack||'').split('\\n')[1]; }
        document.getElementById('out').textContent=JSON.stringify(R);
      })();
    }
  }catch(e){}
  if(Date.now()-start>30000){clearInterval(t);document.getElementById('out').textContent='timeout';}
},200);
</script></body></html>'''

class Combined(api.handler, SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'): return api.handler.do_GET(self)
        if self.path.startswith('/test_photo'):
            body=WRAP.encode()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        return SimpleHTTPRequestHandler.do_GET(self)
    def do_POST(self):
        if self.path.startswith('/api'): return api.handler.do_POST(self)
        self.send_error(501)

srv=ThreadingHTTPServer(('127.0.0.1',0),Combined); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
out=RESULT_DIR + '/dom_photo.html'
cmd=['chromium-browser','--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
     '--window-size=412,915','--virtual-time-budget=30000',f'--user-data-dir={RESULT_DIR}/chrome-ph-{int(time.time())}',
     '--dump-dom',f'http://127.0.0.1:{port}/test_photo.html']
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
print("== UI FOTO ==")
chk('vista previa presente', R.get('hayPreview') is True)
chk('boton subir foto', R.get('hayBotonSubir') is True)
chk('input de archivo', R.get('hayInputFile') is True)
chk('input de URL se conserva', R.get('hayInputUrl') is True)
chk('subió la foto', len(UPLOADS)==1, UPLOADS)
chk('se envió como jpeg', UPLOADS and UPLOADS[0]['type']=='image/jpeg', UPLOADS)
chk('preview con imagen tras subir', R.get('previewImg') is True)
chk('aviso de foto actualizada', 'foto' in (R.get('msg') or '').lower(), R.get('msg'))
chk('quitar borra la vista previa', R.get('trasQuitar') is False)
chk('se borró en Storage', len(DELETES)==1, DELETES)
try:
    from PIL import Image
    im=Image.open(RESULT_DIR + '/uploaded_photo.bin')
    chk('imagen reducida a 512x512', im.size==(512,512), im.size)
    chk('tamaño razonable (<200 KB)', os.path.getsize(RESULT_DIR + '/uploaded_photo.bin')<200*1024, os.path.getsize(RESULT_DIR + '/uploaded_photo.bin'))
except Exception as e:
    chk('PIL pudo leer la imagen', False, e)
if R.get('error'): print('  ERROR JS:', R['error'])
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
