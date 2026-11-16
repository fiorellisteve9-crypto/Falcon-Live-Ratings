"""Ensayo general de un torneo, de punta a punta.

Simula un torneo real pulsando en la interfaz del panel (no llamando a la API
a mano) y comprueba cada paso:

  1. Crear el torneo (Suizo, 7 rondas, 9 jugadores → hay descansos).
  2. Emparejar y capturar los resultados de las 7 rondas.
  3. Cerrar el torneo y comprobar que los ratings cambian.
  4. Imprimir la clasificación (el acta).
  5. Revisar la ficha de un jugador.
  6. Generar la tarjeta de imagen del jugador.
  7. Comprobar la web pública: torneo, desempates y ranking actualizado.

Al final imprime un checklist con el resultado de cada paso y guarda las
capturas en $FALCON_TMP.
"""
import base64, json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root(start):
    """Sube hasta la carpeta que contiene engine/ y api/ (la raíz del repo)."""
    d = start
    for _ in range(5):
        if (os.path.isfile(os.path.join(d, 'engine', 'core.py'))
                and os.path.isfile(os.path.join(d, 'api', 'index.py'))):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.abspath(os.path.join(start, '..'))


ROOT = _find_root(HERE)
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))
sys.path.insert(0, os.path.join(HERE, 'lib'))

from server import store
import api.index as api
from engine import live as live_engine

# ── Almacén falso (Supabase simulado) ────────────────────────────────
class FakeStore:
    def __init__(self):
        self.state = json.load(open(SEED))
        self.state.pop('live', None)
        self.state.setdefault('next_ids', {})
        self.live = {}
        self.version = 1
        self.admin = {"name": "Ensayo", "pin_hash": store.hash_pin("1234", "sal"), "pin_salt": "sal"}
        self.sessions = {"tok-test": {"token": "tok-test", "last_seen": datetime.now(timezone.utc).isoformat()}}
    def get_state_row(self):
        return {"state": self.state, "version": self.version, "updated_at": "x"}
    def save_state_row(self, state, live, version):
        self.state = state; self.live = live; self.version = version + 1
        return {"version": self.version}
    def get_live(self):
        # La web pública lee del mismo estado: el torneo se ve al instante.
        return live_engine.build_live(self.state)
    def get_admin(self): return self.admin
    def create_admin(self, pin, name="A"): return self.admin
    def count_recent_failures(self): return 0
    def add_failed_login(self): pass
    def clear_logins(self): pass
    def new_token(self): return "tok-test"
    def create_session(self, token): pass
    def get_session(self, token): return self.sessions.get(token)
    def touch_session(self, token): pass
    def delete_session(self, token): pass
    def update_admin_pin(self, pin): pass

fake = FakeStore()
for n in ['get_state_row', 'save_state_row', 'get_live', 'get_admin', 'create_admin',
          'count_recent_failures', 'add_failed_login', 'clear_logins', 'new_token',
          'create_session', 'get_session', 'touch_session', 'delete_session', 'update_admin_pin']:
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

from cdp import Chrome

CHECKS = []
def wait_js(expr, timeout=15):
    """Espera a que una expresión en la página sea verdadera."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if c.evaluate(expr):
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def chk(label, cond, extra=""):
    CHECKS.append((label, bool(cond), str(extra)[:120]))
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:110]) if extra != "" else ""))

RONDAS = 7
JUGADORES = 9
NOMBRE_TORNEO = "Ensayo Copa Falcón"

profile = os.path.join(RESULT_DIR, 'chrome-ensayo')
shutil.rmtree(profile, ignore_errors=True)
c = Chrome(profile, window='412,915')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=412, height=915, deviceScaleFactor=2, mobile=True)

    print("== 1. Entrar al panel ==")
    c.navigate(base + '/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Ensayo');")
    c.cmd('Page.reload'); time.sleep(3)
    chk('el panel carga con sesión', c.evaluate("!!document.querySelector('#tabs .tab')") is True)

    print("== 2. Crear el torneo ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('nuevo'))?.click()")
    time.sleep(0.8)
    c.evaluate("(()=>{const n=document.querySelector('#tName');n.value='%s';n.dispatchEvent(new Event('input',{bubbles:true}));})()" % NOMBRE_TORNEO)
    c.evaluate("(()=>{const r=document.querySelector('#tRounds');if(r){r.value='%d';r.dispatchEvent(new Event('input',{bubbles:true}));}})()" % RONDAS)
    # elegir los primeros 9 jugadores (número impar → habrá descansos)
    for _ in range(JUGADORES + 3):
        n = c.evaluate("document.querySelectorAll('#app .player-pick input[type=checkbox]:checked').length")
        if n >= JUGADORES:
            break
        c.evaluate("""(()=>{const cb=[...document.querySelectorAll('#app .player-pick input[type=checkbox]')]
          .find(x=>!x.checked); if(cb) cb.click();})()""")
        time.sleep(0.45)
    time.sleep(0.6)
    resumen = c.evaluate("(()=>{const hs=[...document.querySelectorAll('#app .hint')].map(h=>h.textContent.trim());"
                          "const h=hs.find(x=>x.includes('rondas'));return h||hs.join(' | ');})()")
    chk('el resumen muestra jugadores, rondas y ritmo', '7 rondas' in (resumen or '') and 'jugadores' in (resumen or ''), resumen)
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim().startsWith('Crear torneo'))?.click()")
    time.sleep(2.0)
    titulo = c.evaluate("(()=>{const h=document.querySelector('#app h2');return h?h.textContent.trim():''})()")
    chk('el torneo se crea y se abre su ficha', NOMBRE_TORNEO in (titulo or ''), titulo)
    chk('el torneo tiene 9 participantes', len(fake.state['tournaments'][-1]['participants']) == JUGADORES,
        len(fake.state['tournaments'][-1]['participants']))

    # Ratings antes de la primera ronda (el cierre consolida lo del torneo)
    t_pre = fake.state['tournaments'][-1]
    ritmo_pre = t_pre['rhythm']
    rating_inicio = {p['id']: p['ratings'][ritmo_pre]['rating'] for p in fake.state['players']}

    print(f"== 3. Rondas (1 a {RONDAS}) ==")
    for r in range(1, RONDAS + 1):
        c.evaluate("[...document.querySelectorAll('#app button')].find(b=>/Emparejar ronda/.test(b.textContent))?.click()")
        wait_js("[...document.querySelectorAll('#modalWrap button')].some(b=>b.textContent.trim()==='Emparejar')")
        c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Emparejar')?.click()")
        wait_js("document.querySelectorAll('#app .game').length>0", timeout=20)
        time.sleep(0.8)
        juegos = c.evaluate("document.querySelectorAll('#app .game').length")
        # marcar todos los resultados que falten (1-0, luego ½, luego 0-1)
        for _ in range(60):
            pend = c.evaluate("""(()=>{const gs=[...document.querySelectorAll('#app .game')]
                .filter(g=>g.querySelector('.res'));
              return gs.findIndex(g=>![...g.querySelectorAll('.res')].some(b=>b.classList.contains('on')));})()""")
            if pend < 0:
                break
            c.evaluate("""(()=>{const gs=[...document.querySelectorAll('#app .game')]
                .filter(g=>g.querySelector('.res'));
              const g=gs.find(g=>![...g.querySelectorAll('.res')].some(b=>b.classList.contains('on')));
              if(g){const b=g.querySelector('.res');if(b)b.click();}})()""")
            time.sleep(0.6)
        faltan = c.evaluate("(()=>{const t=document.querySelector('#app').innerText;const i=t.indexOf('Faltan');return i>=0?t.slice(i,i+40):''})()")
        marcados = c.evaluate("(()=>{const t=[...document.querySelectorAll('#app .game .res')],o=t.filter(b=>b.classList.contains('on'));return o.length+'/'+t.length})()")
        ronda_txt = c.evaluate("(()=>{const d=document.querySelector('#app .muted');return d?d.textContent.trim():''})()")
        chk(f'ronda {r}: emparejada y con resultados', (faltan or '') == '' and (juegos > 0), f"{juegos} juegos · {marcados} marcados · {ronda_txt}")
    puntos = c.evaluate("(()=>{const t=document.querySelector('#app table');if(!t)return 0;return t.querySelectorAll('tbody tr').length})()")
    chk('la clasificación tiene a los 9 jugadores', puntos == JUGADORES, puntos)

    print("== 4. Cerrar el torneo ==")
    t_real = fake.state['tournaments'][-1]
    ritmo_t = t_real['rhythm']
    rating_antes = rating_inicio
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Cerrar torneo')?.click()")
    wait_js("[...document.querySelectorAll('#modalWrap button')].some(b=>b.textContent.trim()==='Cerrar')")
    c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Cerrar')?.click()")
    wait_js("(()=>{const p=document.querySelector('#app .pill');return p&&p.textContent.trim()==='Finalizado'})()", timeout=20)
    time.sleep(1.0)
    estado = c.evaluate("(()=>{const p=document.querySelector('#app .pill');return p?p.textContent.trim():''})()")
    chk('el torneo queda finalizado', estado == 'Finalizado', estado)
    cambiados = [p['name'] for p in fake.state['players']
                 if abs(p['ratings'][ritmo_t]['rating'] - rating_antes.get(p['id'], 0)) > 0.5]
    chk('los ratings se actualizan al cerrar', len(cambiados) >= 5,
        f"ritmo {ritmo_t} · {len(cambiados)} jugadores con cambio: {', '.join(cambiados[:4])}")

    print("== 5. El acta impresa ==")
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Imprimir')?.click()")
    time.sleep(1.2)
    acta = c.evaluate("(()=>{const a=document.querySelector('#printArea');if(!a)return '';return a.innerText.replace(/\\s+/g,' ').slice(0,220)})()")
    chk('la hoja impresa tiene el torneo y la clasificación', NOMBRE_TORNEO in (acta or '') and 'Pts' in (acta or ''), acta[:150])

    print("== 6. Ficha de un jugador ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()")
    time.sleep(0.8)
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Ficha')?.click()")
    time.sleep(1.8)
    ficha = c.evaluate("(()=>{const f=document.querySelector('.modal--ficha');return f?f.innerText.replace(/\\s+/g,' ').slice(0,160):''})()")
    chk('la ficha se abre con datos', 'ratings por ritmo' in (ficha or '').lower(), ficha[:130])
    c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Cerrar')?.click()")
    time.sleep(0.5)

    print("== 7. Tarjeta de imagen (web pública) ==")
    c.navigate(base + '/'); time.sleep(4)
    c.evaluate("""(()=>{const r=document.querySelector('.prow');if(r)r.click();})()""")
    time.sleep(2.5)
    c.evaluate("""(()=>{const b=[...document.querySelectorAll('#app button,button')].find(x=>x.textContent.trim()==='Tarjeta imagen');if(b)b.click();})()""")
    time.sleep(2.5)
    card = c.evaluate("""(()=>{const i=document.querySelector('#cardPreviewWrap img');
      if(!i)return {ok:false};const cv=document.createElement('canvas');cv.width=i.naturalWidth;cv.height=i.naturalHeight;
      const g=cv.getContext('2d');g.drawImage(i,0,0);
      const d=g.getImageData(0,0,cv.width,cv.height).data;
      let suma=0;for(let k=0;k<d.length;k+=4000)suma+=d[k];
      return {ok:true,w:i.naturalWidth,h:i.naturalHeight,pix:suma};})()""")
    chk('la tarjeta de imagen se genera', card.get('ok') and card.get('w', 0) > 500 and card.get('pix', 0) > 0, card)

    print("== 8. Web pública ==")
    c.navigate(base + '/'); time.sleep(5)
    pub = c.evaluate("""(async()=>{const j=await (await fetch('/api?action=live')).json();
      return {torneo:j.torneo&&j.torneo.nombre, final:j.torneo&&j.torneo.finalizado,
              crit:(j.torneo&&j.torneo.criterios||[]).map(c=>c.label),
              jugadores:j.torneo?j.torneo.jugadores.length:0,
              rapido:(j.ranking.Rapid||[]).length};})()""")
    chk('la web pública muestra el torneo terminado', pub.get('torneo') == NOMBRE_TORNEO and pub.get('final') == 1, pub)
    chk('la web pública muestra los desempates aplicables', 'BH1' in (pub.get('crit') or []), pub.get('crit'))
    chk('el ranking rápido tiene a los participantes', pub.get('rapido', 0) >= 9, pub.get('rapido'))
    shot = c.cmd('Page.captureScreenshot', format='png')['data']
    open(os.path.join(RESULT_DIR, 'ensayo-web-publica.png'), 'wb').write(base64.b64decode(shot))

finally:
    c.close()
    shutil.rmtree(profile, ignore_errors=True)
    srv.shutdown()

print()
fallos = [x for x in CHECKS if not x[1]]
print(f"RESULTADO: {len(CHECKS) - len(fallos)}/{len(CHECKS)} pasos correctos")
for label, _, extra in fallos:
    print('  FALLA:', label, extra)
sys.exit(1 if fallos else 0)
