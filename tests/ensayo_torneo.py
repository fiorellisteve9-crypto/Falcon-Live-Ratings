"""Ensayo general de un torneo, de punta a punta (cualquier formato).

Simula un torneo real pulsando en la interfaz del panel (no llamando a la API
a mano) y comprueba cada paso:

  1. Crear el torneo (Suizo, RR 1 vuelta o RR 2 vueltas).
  2. Emparejar y capturar los resultados de todas las rondas.
  3. Cerrar el torneo y comprobar que los ratings cambian.
  4. Imprimir la clasificación (el acta).
  5. Revisar la ficha de un jugador.
  6. Generar la tarjeta de imagen del jugador.
  7. Comprobar la web pública: torneo, desempates y ranking actualizado.

Uso:
    python3 tests/ensayo_torneo.py --tipo suizo --jugadores 9
    python3 tests/ensayo_torneo.py --tipo rr1v  --jugadores 8 --ritmo Rapid
    python3 tests/ensayo_torneo.py --tipo rr2v  --jugadores 6 --ritmo Blitz
    python3 tests/ensayo_torneo.py --todos
"""
import argparse, base64, json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root(start):
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
sys.path.insert(0, os.path.join(HERE, 'lib'))

from server import store
import api.index as api
from engine import live as live_engine
from engine.core import TipoTorneo, etiquetas_criterios

FORMAS = {
    # tipo del panel: 1 Suizo, 2 Round Robin 1 vuelta, 3 Round Robin 2 vueltas
    'suizo': {'tipo': 1, 'label': 'Suizo', 'rondas_manuales': 7},
    'rr1v':  {'tipo': 2, 'label': 'Round Robin 1 vuelta', 'rondas_manuales': 0},
    'rr2v':  {'tipo': 3, 'label': 'Round Robin 2 vueltas', 'rondas_manuales': 0},
}


def rondas_esperadas(forma, jugadores):
    """Rondas que debe tener el torneo (misma regla que el panel)."""
    if forma == 'suizo':
        return FORMAS['suizo']['rondas_manuales']
    if forma == 'rr1v':
        return jugadores - 1 if jugadores % 2 == 0 else jugadores
    return (jugadores - 1) * 2 if jugadores % 2 == 0 else jugadores * 2
# Los criterios de desempate NO se escriben aquí: se leen del motor
# (engine/core.py), que es la fuente de verdad. El ensayo comprueba que el
# panel, el acta y la web pública muestran exactamente esos.
def criterios_del_motor(forma, ritmo):
    tipo = {'suizo': TipoTorneo.SUIZO,
            'rr1v': TipoTorneo.ROUND_ROBIN_UNA_VUELTA,
            'rr2v': TipoTorneo.ROUND_ROBIN_DOS_VUELTAS}[forma]
    return [c['label'] for c in etiquetas_criterios(tipo, ritmo)]


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


def ejecutar(forma, jugadores, ritmo, verbose=True):
    cfg = FORMAS[forma]
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

    def chk(label, cond, extra=""):
        CHECKS.append((label, bool(cond), str(extra)[:120]))
        if verbose:
            print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:110]) if extra != "" else ""))

    def wait_js(expr, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if c.evaluate(expr):
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    nombre = f"Ensayo {cfg['label']}"
    profile = os.path.join(RESULT_DIR, f'chrome-ensayo-{forma}')
    shutil.rmtree(profile, ignore_errors=True)
    c = Chrome(profile, window='412,915')
    try:
        c.cmd('Emulation.setDeviceMetricsOverride', width=412, height=915, deviceScaleFactor=2, mobile=True)

        if verbose:
            print(f"== {cfg['label']} · ritmo {ritmo} · {jugadores} jugadores ==")
            print("== 1. Entrar al panel ==")
        c.navigate(base + '/admin.html'); time.sleep(1.5)
        c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Ensayo');")
        c.cmd('Page.reload'); time.sleep(3)
        chk('el panel carga con sesión', c.evaluate("!!document.querySelector('#tabs .tab')") is True)

        print("== 2. Crear el torneo ==")
        c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('nuevo'))?.click()")
        time.sleep(0.8)
        c.evaluate("(()=>{const n=document.querySelector('#tName');n.value='%s';n.dispatchEvent(new Event('input',{bubbles:true}));})()" % nombre)
        c.evaluate("(()=>{const s=[...document.querySelectorAll('#app select')].find(x=>x.getAttribute('onchange')&&x.getAttribute('onchange').includes('setNewType'));if(s){s.value='%d';s.dispatchEvent(new Event('change',{bubbles:true}));}})()" % cfg['tipo'])
        time.sleep(0.4)
        c.evaluate("(()=>{const s=[...document.querySelectorAll('#app select')].find(x=>x.getAttribute('onchange')&&x.getAttribute('onchange').includes('setNewRhythm'));if(s){s.value='%s';s.dispatchEvent(new Event('change',{bubbles:true}));}})()" % ritmo)
        time.sleep(0.4)
        if cfg['rondas_manuales']:
            c.evaluate("(()=>{const r=document.querySelector('#tRounds');if(r){r.value='%d';"
                       "r.dispatchEvent(new Event('input',{bubbles:true}));}})()" % cfg['rondas_manuales'])
            time.sleep(0.4)
        for _ in range(jugadores + 3):
            n = c.evaluate("document.querySelectorAll('#app .player-pick input[type=checkbox]:checked').length")
            if n >= jugadores:
                break
            c.evaluate("""(()=>{const cb=[...document.querySelectorAll('#app .player-pick input[type=checkbox]')]
              .find(x=>!x.checked); if(cb) cb.click();})()""")
            time.sleep(0.45)
        time.sleep(0.8)
        resumen = c.evaluate("""(()=>{const hs=[...document.querySelectorAll('#app .hint')].map(h=>h.textContent.trim());
          const h=hs.find(x=>x.includes('rondas'));return h||hs.join(' | ');})()""")
        chk('el resumen muestra jugadores, rondas y ritmo',
            'rondas' in (resumen or '') and 'jugadores' in (resumen or ''), resumen)
        c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim().startsWith('Crear torneo'))?.click()")
        time.sleep(2.2)
        titulo = c.evaluate("(()=>{const h=document.querySelector('#app h2');return h?h.textContent.trim():''})()")
        chk('el torneo se crea y se abre su ficha', nombre in (titulo or ''), titulo)
        t_real = fake.state['tournaments'][-1]
        rondas_total = int(t_real['rounds_total'])
        r_esp = rondas_esperadas(forma, jugadores)
        chk('el torneo tiene los participantes y las rondas correctas',
            len(t_real['participants']) == jugadores and rondas_total == r_esp,
            f"{len(t_real['participants'])} jugadores · {rondas_total} rondas (esperadas {r_esp}) · {t_real['rhythm']}")
        chk('el formato es el pedido', int(t_real['type']) == cfg['tipo'], t_real['type'])

        # Ratings antes de la primera ronda
        ritmo_t = t_real['rhythm']
        rating_inicio = {p['id']: p['ratings'][ritmo_t]['rating'] for p in fake.state['players']}

        print(f"== 3. Rondas (1 a {rondas_total}) ==")
        for r in range(1, rondas_total + 1):
            c.evaluate("[...document.querySelectorAll('#app button')].find(b=>/Emparejar ronda/.test(b.textContent))?.click()")
            wait_js("[...document.querySelectorAll('#modalWrap button')].some(b=>b.textContent.trim()==='Emparejar')")
            c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Emparejar')?.click()")
            wait_js("document.querySelectorAll('#app .game').length>0", timeout=25)
            time.sleep(0.8)
            juegos = c.evaluate("document.querySelectorAll('#app .game').length")
            for _ in range(80):
                pend = c.evaluate("""(()=>{const gs=[...document.querySelectorAll('#app .game')]
                    .filter(g=>g.querySelector('.res'));
                  return gs.findIndex(g=>![...g.querySelectorAll('.res')].some(b=>b.classList.contains('on')));})()""")
                if pend < 0:
                    break
                c.evaluate("""(()=>{const gs=[...document.querySelectorAll('#app .game')]
                    .filter(g=>g.querySelector('.res'));
                  const g=gs.find(g=>![...g.querySelectorAll('.res')].some(b=>b.classList.contains('on')));
                  if(g){const b=g.querySelector('.res');if(b)b.click();}})()""")
                time.sleep(0.55)
            faltan = c.evaluate("(()=>{const t=document.querySelector('#app').innerText;const i=t.indexOf('Faltan');return i>=0?t.slice(i,i+40):''})()")
            marcados = c.evaluate("""(()=>{const t=[...document.querySelectorAll('#app .game .res')],
              o=t.filter(b=>b.classList.contains('on'));return o.length+'/'+t.length})()""")
            chk(f'ronda {r}: emparejada y con resultados', (faltan or '') == '' and (juegos > 0),
                f"{juegos} juegos · {marcados} marcados")
        filas = c.evaluate("(()=>{const t=document.querySelector('#app table');return t?t.querySelectorAll('tbody tr').length:0})()")
        chk('la clasificación tiene a todos los jugadores', filas == jugadores, filas)

        print("== 4. Cerrar el torneo ==")
        c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Cerrar torneo')?.click()")
        wait_js("[...document.querySelectorAll('#modalWrap button')].some(b=>b.textContent.trim()==='Cerrar')")
        c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Cerrar')?.click()")
        wait_js("(()=>{const p=document.querySelector('#app .pill');return p&&p.textContent.trim()==='Finalizado'})()", timeout=25)
        time.sleep(1.0)
        estado = c.evaluate("(()=>{const p=document.querySelector('#app .pill');return p?p.textContent.trim():''})()")
        chk('el torneo queda finalizado', estado == 'Finalizado', estado)
        cambiados = [p['name'] for p in fake.state['players']
                     if abs(p['ratings'][ritmo_t]['rating'] - rating_inicio.get(p['id'], 0)) > 0.5]
        chk('los ratings se actualizan al cerrar', len(cambiados) >= 5,
            f"ritmo {ritmo_t} · {len(cambiados)} con cambio: {', '.join(cambiados[:3])}")

        print("== 5. El acta impresa ==")
        c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Imprimir')?.click()")
        time.sleep(1.4)
        acta = c.evaluate("(()=>{const a=document.querySelector('#printArea');return a?a.innerText.replace(/\\s+/g,' ').slice(0,240):''})()")
        crit_esperados = criterios_del_motor(forma, ritmo)
        chk('el acta tiene el torneo y la clasificación', nombre in (acta or '') and 'Pts' in (acta or ''), (acta or '')[:120])
        chk('el acta usa los desempates del formato',
            all(x in (acta or '') for x in crit_esperados), f"deben aparecer: {', '.join(crit_esperados)}")

        print("== 6. Ficha de un jugador ==")
        c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()")
        time.sleep(0.8)
        c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Ficha')?.click()")
        time.sleep(2.0)
        ficha = c.evaluate("(()=>{const f=document.querySelector('.modal--ficha');return f?f.innerText.replace(/\\s+/g,' ').slice(0,160):''})()")
        chk('la ficha se abre con datos', 'ratings por ritmo' in (ficha or '').lower(), (ficha or '')[:110])
        c.evaluate("[...document.querySelectorAll('#modalWrap button')].find(b=>b.textContent.trim()==='Cerrar')?.click()")
        time.sleep(0.5)

        print("== 7. Tarjeta de imagen (web pública) ==")
        c.navigate(base + '/'); time.sleep(4)
        c.evaluate("(()=>{const r=document.querySelector('.prow');if(r)r.click();})()")
        time.sleep(2.5)
        c.evaluate("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Tarjeta imagen');if(b)b.click();})()""")
        time.sleep(2.5)
        card = c.evaluate("""(()=>{const i=document.querySelector('#cardPreviewWrap img');
          if(!i)return {ok:false};const cv=document.createElement('canvas');cv.width=i.naturalWidth;cv.height=i.naturalHeight;
          const g=cv.getContext('2d');g.drawImage(i,0,0);
          const d=g.getImageData(0,0,cv.width,cv.height).data;let s=0;for(let k=0;k<d.length;k+=4000)s+=d[k];
          return {ok:true,w:i.naturalWidth,h:i.naturalHeight,pix:s};})()""")
        chk('la tarjeta de imagen se genera', card.get('ok') and card.get('w', 0) > 500 and card.get('pix', 0) > 0, card)

        print("== 8. Web pública ==")
        c.navigate(base + '/'); time.sleep(5)
        pub = c.evaluate("""(async()=>{const j=await (await fetch('/api?action=live')).json();
          return {torneo:j.torneo&&j.torneo.nombre, final:j.torneo&&j.torneo.finalizado,
                  crit:(j.torneo&&j.torneo.criterios||[]).map(c=>c.label),
                  jugadores:j.torneo?j.torneo.jugadores.length:0,
                  enRanking:(j.ranking[j.torneo&&j.torneo.ritmo]||[]).length};})()""")
        chk('la web pública muestra el torneo terminado', pub.get('torneo') == nombre and pub.get('final') == 1, pub.get('torneo'))
        chk('la web pública muestra los desempates del formato',
            pub.get('crit') == crit_esperados, f"{pub.get('crit')} (esperado {crit_esperados})")
        chk('los participantes están en el ranking', pub.get('enRanking', 0) >= jugadores, pub.get('enRanking'))
        shot = c.cmd('Page.captureScreenshot', format='png')['data']
        open(os.path.join(RESULT_DIR, f'ensayo-web-publica-{forma}.png'), 'wb').write(base64.b64decode(shot))
    finally:
        c.close()
        shutil.rmtree(profile, ignore_errors=True)
        srv.shutdown()

    fallos = [x for x in CHECKS if not x[1]]
    print(f"RESULTADO [{forma} · {ritmo} · {jugadores} jugadores]: {len(CHECKS) - len(fallos)}/{len(CHECKS)} pasos correctos")
    for label, _, extra in fallos:
        print('  FALLA:', label, extra)
    return (len(CHECKS) - len(fallos), len(CHECKS), fallos)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--tipo', choices=list(FORMAS), default='suizo')
    ap.add_argument('--jugadores', type=int, default=9)
    ap.add_argument('--ritmo', default='Blitz')
    ap.add_argument('--todos', action='store_true', help='probar los tres formatos')
    args = ap.parse_args()

    if args.todos:
        plan = [('suizo', 9, 'Blitz'), ('rr1v', 8, 'Rapid'), ('rr2v', 6, 'Blitz')]
        total_ok = total = 0
        todo_ok = True
        for forma, jug, rit in plan:
            print()
            ok, n, fallos = ejecutar(forma, jug, rit)
            total_ok += ok; total += n
            if fallos:
                todo_ok = False
        print(f"\nRESUMEN GENERAL: {total_ok}/{total} pasos correctos")
        sys.exit(0 if todo_ok else 1)

    ok, n, fallos = ejecutar(args.tipo, args.jugadores, args.ritmo)
    sys.exit(0 if not fallos else 1)
