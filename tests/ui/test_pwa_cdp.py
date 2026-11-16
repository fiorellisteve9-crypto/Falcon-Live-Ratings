import json, os, sys, threading, time, shutil
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

REPO = RESULT_DIR + '/Falcon-Live-Ratings'
os.chdir(ROOT)

LIVE = {
    "timestamp": "2026-11-08T12:00:00",
    "ranking": {"Rapid": [{"e": 1500, "n": "Jugador Prueba", "p": 3, "r": 1, "v": 12, "dr": 0,
                            "sp": [1490, 1500], "cat": "Sub-12", "mun": "Falcón", "flag": "\U0001F1FA\U0001F1EA"}],
                "Blitz": [], "Bullet": []},
    "torneo": None, "torneo_partidas": [], "matches": [], "historial": []
}

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api'):
            body = json.dumps(LIVE).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith('/sw.js'):
            data = open('sw.js', 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript')
            self.send_header('Service-Worker-Allowed', '/')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith('/manifest'):
            data = open('manifest.webmanifest' if 'admin' not in self.path else 'manifest-admin.webmanifest', 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/manifest+json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return SimpleHTTPRequestHandler.do_GET(self)
    def log_message(self, *a): pass

srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{port}'
profile = RESULT_DIR + '/chrome-pwa-test'

ok = True
def chk(label, cond, extra=""):
    global ok
    if not cond: ok = False
    print(("  OK  " if cond else " FALLA") + f" {label} {extra}")

shutil.rmtree(profile, ignore_errors=True)
chrome = Chrome(profile)
try:
    print("== 1. Carga inicial ==")
    chrome.navigate(base + '/')
    chk('la pagina carga', chrome.evaluate("document.title") == 'Falcón Live Ratings', chrome.evaluate("document.title"))
    chk('manifest enlazado', chrome.evaluate("document.querySelector('link[rel=manifest]').href.endsWith('/manifest.webmanifest')"))
    chk('theme-color', chrome.evaluate("document.querySelector('meta[name=theme-color]').content") == '#121212')
    chk('boton Instalar app', chrome.evaluate("!!document.getElementById('installBtn')"))
    chk('el boton Instalar app existe', chrome.evaluate("!!document.getElementById('installBtn')"))
    chrome.navigate(base + '/')
    chrome.wait_for("document.getElementById('installBtn').hidden === false ? true : false", timeout=25)
    chk('Chrome la considera instalable (el boton aparece con beforeinstallprompt)',
        chrome.evaluate("document.getElementById('installBtn').hidden") is False,
        'hidden=' + str(chrome.evaluate("document.getElementById('installBtn').hidden")))

    man = json.loads(chrome.evaluate("fetch('/manifest.webmanifest').then(r=>r.text())"))
    chk('manifest: nombre', man['name'] == 'Falcón Live Ratings', man['name'])
    chk('manifest: standalone', man['display'] == 'standalone')
    chk('manifest: start_url', man['start_url'] == '/')
    chk('manifest: iconos', len(man['icons']) >= 4, len(man['icons']))
    chk('manifest: 3 atajos', len(man.get('shortcuts', [])) == 3, [x.get('name') for x in man.get('shortcuts', [])])
    adm = json.loads(chrome.evaluate("fetch('/manifest-admin.webmanifest').then(r=>r.text())"))
    chk('manifest admin: start_url', adm['start_url'] == '/admin.html', adm['start_url'])
    for ic in man['icons']:
        code = chrome.evaluate(f"fetch('{ic['src']}').then(r=>r.status)")
        chk(f"icono {ic['src']} ({ic.get('purpose','any')})", code == 200, code)

    print("== 2. Service worker ==")
    chrome.evaluate("navigator.serviceWorker.register('/sw.js',{scope:'/'}).then(r=>r.scope)", await_promise=True)
    chrome.wait_for("navigator.serviceWorker.ready.then(()=>true)", timeout=30)
    chk('service worker activo', chrome.evaluate("!!navigator.serviceWorker.controller || navigator.serviceWorker.getRegistrations().then(r=>r.length>0)") is not False)
    chk('registro con scope raiz', chrome.evaluate("navigator.serviceWorker.getRegistration('/').then(r=>r && r.scope)").endswith('/'))
    chk('sw controlando la pagina', chrome.evaluate("navigator.serviceWorker.controller ? true : false") is True)
    cache = chrome.evaluate("caches.keys().then(k=>k.join(','))")
    chk('cache creado', 'falcon-' in (cache or ''), cache)
    entries = chrome.evaluate("caches.keys().then(ks=>caches.open(ks[0])).then(c=>c.keys()).then(ks=>ks.map(r=>new URL(r.url).pathname).join(' '))")
    for need in ['/index.html', '/admin.html', '/manifest.webmanifest', '/icons/icon-512.png', '/fonts/inter.css', '/vendor/chart.umd.min.js']:
        chk(f'precache {need}', need in (entries or ''), entries[:120] if entries else '')
    chk('api NO cacheado', '/api' not in (entries or ''))

    print("== 3. La API nunca se sirve del cache ==")
    live = chrome.evaluate("fetch('/api?action=live').then(r=>r.json()).then(j=>j.ranking.Rapid.length)")
    chk('api responde con datos frescos', live == 1, live)

    print("== 4. Sin conexion ==")
    srv.shutdown()
    time.sleep(1)
    chrome.cmd('Page.enable')
    chrome.cmd('Page.navigate', url=base + '/')
    chrome.wait_ready(timeout=25)
    time.sleep(8)   # el sitio cambia a modo local/dEMO tras 5 s sin respuesta de la API
    txt = chrome.evaluate("document.body.innerText.slice(0,200)", await_promise=False)
    chk('la app abre sin conexion', 'Falcón Live Ratings' in (txt or ''), (txt or '')[:60].replace('\n', ' '))
    filas = chrome.evaluate("document.querySelectorAll('#rankingWrap .prow, #rankingWrap table tbody tr').length", await_promise=False)
    chk('el ranking sigue visible (copia en localStorage)', filas and filas > 0, filas)
    chk('barra de sin conexion visible',
        chrome.evaluate("document.getElementById('offlineBar').classList.contains('show')", await_promise=False) is True)
    etiqueta = chrome.evaluate("document.getElementById('liveLabel').textContent.trim()", await_promise=False)
    chk('la etiqueta ya no dice EN VIVO', etiqueta != 'EN VIVO', etiqueta)
finally:
    chrome.close()
    shutil.rmtree(profile, ignore_errors=True)

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
