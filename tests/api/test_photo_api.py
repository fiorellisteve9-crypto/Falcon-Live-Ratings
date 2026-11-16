import sys, os, json, threading, urllib.request, urllib.error, base64, io
from datetime import datetime, timezone

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../lib'))
from seed import seed_path
SEED = seed_path()
sys.path.insert(0, ROOT)
os.environ['SETUP_TOKEN']='setup123'
os.environ['SUPABASE_URL']='https://demo.supabase.co'
from server import store
import api.index as api
from engine import state as st

class FakeStore:
    def __init__(self):
        self.state=st.new_state(); self.live={}; self.version=1
        self.admin=None; self.sessions={}
    def get_state_row(self): return {"state":self.state,"version":self.version,"updated_at":"now"}
    def save_state_row(self,state,live,version):
        self.state=state; self.live=live; self.version=version+1; return {"version":self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self,pin,name="Administrador"):
        self.admin={"name":name,"pin_hash":store.hash_pin(pin,"sal"),"pin_salt":"sal"}; return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok-test"
    def create_session(self,token):
        self.sessions[token]={"token":token,"last_seen":datetime.now(timezone.utc).isoformat()}
    def get_session(self,token): return self.sessions.get(token)
    def touch_session(self,token): pass
    def delete_session(self,token): self.sessions.pop(token,None)
    def update_admin_pin(self,pin): pass

fake=FakeStore()
for n in ['get_state_row','save_state_row','get_live','get_admin','create_admin','count_recent_failures',
          'add_failed_login','clear_logins','new_token','create_session','get_session','touch_session',
          'delete_session','update_admin_pin']:
    setattr(store,n,getattr(fake,n))
store.MAX_FAILED_LOGINS=5
store.session_is_valid=lambda s: bool(s)

# Storage simulado
UPLOADED={}
DELETED=[]
def fake_upload(object_path, payload, content_type):
    UPLOADED[object_path]=(len(payload), content_type)
    return store.photo_public_url(object_path)
def fake_delete(url):
    DELETED.append(url)
    return True
store.upload_photo=fake_upload
store.delete_photo=fake_delete

from http.server import HTTPServer
srv=HTTPServer(('127.0.0.1',0), api.handler); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()
def post(action, token=None, **kw):
    body={"action":action, **kw}
    req=urllib.request.Request(f'http://127.0.0.1:{port}/api', data=json.dumps(body).encode(),
        headers={'Content-Type':'application/json', **({'x-token':token} if token else {})}, method='POST')
    try:
        r=urllib.request.urlopen(req,timeout=30); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")

post('setup', setup_token='setup123', pin='1234')
code,r=post('login', pin='1234'); token=r['token']
code,r=post('player_create', token=token, name='Con Foto', mun='Falcón', cat='-')
pid=r['player']['id']
png=base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0'*400).decode()
code,r=post('photo_upload', token=token, player_id=pid, data='data:image/png;base64,'+png)
chk('subida 200', code==200, (code, r.get('error')))
chk('guarda la URL en el jugador', str(r.get('player',{}).get('foto_url','')).startswith('https://demo.supabase.co/storage/v1/object/public/fotos/'), r.get('player',{}).get('foto_url'))
chk('subió el objeto al bucket', any(k.startswith(f'{pid}-') and v[1]=='image/png' for k,v in UPLOADED.items()), UPLOADED)
url1=r['player']['foto_url']
# reemplazo borra la anterior
code,r=post('photo_upload', token=token, player_id=pid, data='data:image/jpeg;base64,'+png)
chk('reemplazo 200', code==200, r.get('error'))
chk('borra la foto anterior', url1 in DELETED, DELETED)
# quitar
code,r=post('photo_delete', token=token, player_id=pid)
chk('photo_delete 200', code==200, r.get('error'))
chk('foto_url queda vacío', r.get('player',{}).get('foto_url') in (None,''), r.get('player',{}).get('foto_url'))
# validaciones
code,r=post('photo_upload', token=token, player_id=pid, data='data:image/gif;base64,'+png)
chk('rechaza gif', code==400, r.get('error'))
code,r=post('photo_upload', token=token, player_id=pid, data='no-es-imagen')
chk('rechaza texto', code==400, r.get('error'))
code,r=post('photo_upload', token=token, player_id=pid, data='data:image/png;base64,@@@')
chk('rechaza base64 inválido', code==400, r.get('error'))
code,r=post('photo_upload', token=token, player_id=99999, data='data:image/png;base64,'+png)
chk('rechaza jugador inexistente', code==400 and 'no encontrado' in str(r.get('error')).lower(), r.get('error'))
code,r=post('photo_upload', player_id=pid, data='data:image/png;base64,'+png)
chk('exige token', code==401, code)
# dashboard público con la foto
code,r=post('photo_upload', token=token, player_id=pid, data='data:image/png;base64,'+png)
code,live=urllib.request.urlopen(f'http://127.0.0.1:{port}/api?action=live',timeout=20), None
import json as _j
lv=_j.loads(live) if live else None
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
