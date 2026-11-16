import base64, json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from server import store
import api.index as api
from engine import tournaments as tm

# Foto de prueba 512x512 (el mismo tamaño que una foto subida desde el móvil).
# La genera la propia prueba para no depender de ningún archivo del repo.
from PIL import Image, ImageDraw
TEST_PHOTO = os.path.join(ROOT, '_test_foto.jpg')
_im = Image.new('RGB', (512, 512), (30, 60, 120))
_d = ImageDraw.Draw(_im)
_d.ellipse([80, 40, 432, 392], fill=(240, 200, 80))
_d.rectangle([120, 330, 392, 512], fill=(20, 120, 60))
_im.save(TEST_PHOTO, 'JPEG', quality=90)
FOTO = "/_test_foto.jpg"

class FakeStore:
    def __init__(self):
        self.state = json.load(open(SEED))
        self.state.pop('live', None)
        self.state.setdefault('next_ids', {})
        # foto real en el primer jugador con historial
        for p in self.state['players']:
            if p['name'] == 'Jeanfranco Hurtado':
                p['foto_url'] = FOTO
        self.live = {}; self.version = 1
        self.admin = {"name": "Test", "pin_hash": store.hash_pin("1234", "sal"), "pin_salt": "sal"}
        self.sessions = {"tok-test": {"token": "tok-test", "last_seen": datetime.now(timezone.utc).isoformat()}}
    def get_state_row(self): return {"state": self.state, "version": self.version, "updated_at": "x"}
    def save_state_row(self, s, l, v): self.state = s; self.live = l; self.version = v + 1; return {"version": self.version}
    def get_live(self): return self.live
    def get_admin(self): return self.admin
    def create_admin(self, p, name="A"): return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok-test"
    def create_session(self, t): pass
    def get_session(self, t): return self.sessions.get(t)
    def touch_session(self, t): pass
    def delete_session(self, t): pass
    def update_admin_pin(self, p): pass

fake = FakeStore()
for n in ['get_state_row','save_state_row','get_live','get_admin','create_admin','count_recent_failures',
          'add_failed_login','clear_logins','new_token','create_session','get_session','touch_session',
          'delete_session','update_admin_pin']:
    setattr(store, n, getattr(fake, n))
store.MAX_FAILED_LOGINS = 5
store.session_is_valid = lambda s: bool(s)

class H(api.handler, SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'): return api.handler.do_GET(self)
        return SimpleHTTPRequestHandler.do_GET(self)
    def do_POST(self):
        if self.path.startswith('/api'): return api.handler.do_POST(self)
        self.send_error(501)
    def log_message(self, *a): pass

srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{port}'
sys.path.insert(0, ROOT)
from cdp import Chrome

ok = True
def chk(l, c, e=""):
    global ok
    if not c: ok = False
    print(("  OK  " if c else " FALLA") + f" {l} {e}")

profile = RESULT_DIR + '/chrome-ficha'; shutil.rmtree(profile, ignore_errors=True)
c = Chrome(profile, window='412,915')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    c.navigate(base + '/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Test');")
    c.cmd('Page.reload'); time.sleep(3)
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()")
    time.sleep(0.8)
    # abrir la ficha del jugador con foto
    pid = c.evaluate("(()=>{const tr=[...document.querySelectorAll('#playerTable tr')].find(r=>r.dataset.name==='Jeanfranco Hurtado');return tr?Number(tr.dataset.id):0})()")
    chk('jugador con foto encontrado', pid > 0, pid)
    c.evaluate("abrirFichaJugador(%d)" % pid); time.sleep(2.5)

    print("== Modal de la ficha en móvil ==")
    chk('la ficha se abre', c.evaluate("!!document.querySelector('.modal--ficha')") is True)
    av = c.evaluate("(()=>{const a=document.querySelector('.modal--ficha .avatar');const r=a.getBoundingClientRect();"
                     "const i=a.querySelector('img');return {w:Math.round(r.width),h:Math.round(r.height),"
                     "imgW:i?i.naturalWidth:0,imgH:i?i.naturalHeight:0,overflow:getComputedStyle(a).overflow,"
                     "fit:i?getComputedStyle(i).objectFit:''}})()")
    chk('el avatar NO se muestra gigante', 40 <= av['w'] <= 80, av)
    chk('el avatar es cuadrado', av['w'] == av['h'], av)
    chk('la foto real se cargó (512px)', av['imgW'] >= 400, av)
    chk('la foto se recorta con object-fit', av['fit'] == 'cover', av)
    chk('el avatar recorta el desborde', av['overflow'] == 'hidden', av)

    sheet = c.evaluate("(()=>{const m=document.querySelector('.modal--ficha');const r=m.getBoundingClientRect();"
                       "const b=m.querySelector('.ficha-body');"
                       "return {w:Math.round(r.width),h:Math.round(r.height),vh:window.innerHeight,"
                       "overflow:b?getComputedStyle(b).overflowY:'',ratio:getComputedStyle(m).borderTopLeftRadius}})()")
    chk('la hoja cabe en la pantalla', sheet['h'] <= sheet['vh'] + 2, sheet)
    chk('la hoja va pegada al borde inferior', abs(sheet['h'] - sheet['vh']) < 60 or sheet['h'] > sheet['vh'] - 300, sheet)
    chk('el contenido se desplaza dentro', sheet['overflow'] in ('auto', 'scroll'), sheet)
    chk('sin scroll horizontal de página', c.evaluate("document.documentElement.scrollWidth") <= 392,
        c.evaluate("document.documentElement.scrollWidth"))
    chk('sin desbordes dentro de la ficha', c.evaluate("(()=>{const b=document.querySelector('.ficha-body');return b.scrollWidth<=b.clientWidth+1})()"),
        c.evaluate("(()=>{const b=document.querySelector('.ficha-body');return b.scrollWidth+'/'+b.clientWidth})()"))

    print("== Contenido ==")
    tarjetas = c.evaluate("document.querySelectorAll('.modal--ficha .ficha-card').length")
    chk('3 tarjetas de ritmo', tarjetas == 3, tarjetas)
    filas = c.evaluate("document.querySelectorAll('.modal--ficha .ficha-row').length")
    chk('filas de datos', filas > 0, filas)
    ident = c.evaluate("(()=>{const n=document.querySelector('.modal--ficha .ficha-name');return n?n.textContent.trim():''})()")
    chk('muestra el nombre', ident == 'Jeanfranco Hurtado', ident)
    chk('las tarjetas de ritmo traen rating', c.evaluate("!!document.querySelector('.modal--ficha .fc-r')") is True)
    chk('botones en la barra inferior fija', c.evaluate("(()=>{const a=document.querySelector('.ficha-actions');if(!a)return false;const r=a.getBoundingClientRect();return r.bottom<=window.innerHeight+2})()"))
    shot = c.cmd('Page.captureScreenshot', format='png')['data']
    open(RESULT_DIR + '/ficha_movil_ok.png', 'wb').write(base64.b64decode(shot))
    print('   captura: /tmp/opencode/ficha_movil_ok.png')
finally:
    c.close(); shutil.rmtree(profile, ignore_errors=True)
    srv.shutdown()
    try:
        os.remove(TEST_PHOTO)
    except OSError:
        pass
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
