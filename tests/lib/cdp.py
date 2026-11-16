import json, os, socket, subprocess, time
import requests
import websocket


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Chrome:
    def __init__(self, profile, headless=True, window='412,915', extra=None):
        self.profile = profile
        self.port = free_port()
        os.makedirs(profile, exist_ok=True)
        cmd = ['chromium-browser']
        if headless:
            cmd.append('--headless=new')
        cmd += ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--hide-scrollbars',
                '--disable-features=Translate,MediaRouter', '--no-first-run', '--no-default-browser-check',
                f'--window-size={window}', f'--remote-debugging-port={self.port}',
                f'--user-data-dir={profile}', 'about:blank']
        if extra:
            cmd = cmd[:-1] + extra + ['about:blank']
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = f'http://127.0.0.1:{self.port}'
        self.ws = None
        self._id = 0
        for _ in range(120):
            try:
                if requests.get(self.base + '/json/version', timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError('Chrome no arranco')

    def page_target(self):
        for _ in range(60):
            try:
                targets = requests.get(self.base + '/json/list', timeout=5).json()
                pages = [t for t in targets if t.get('type') == 'page']
                if pages:
                    return pages[0]
            except Exception:
                pass
            time.sleep(0.25)
        raise RuntimeError('No hay target de pagina')

    def connect(self):
        if self.ws is None:
            t = self.page_target()
            self.ws = websocket.create_connection(t['webSocketDebuggerUrl'], suppress_origin=True, timeout=40)
        return self.ws

    def cmd(self, method, **params):
        self.connect()
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get('result', {})

    def navigate(self, url):
        self.cmd('Page.enable')
        self.cmd('Page.navigate', url=url)
        self.wait_ready()

    def reload(self):
        self.cmd('Page.enable')
        self.cmd('Page.reload', ignoreCache=False)
        self.wait_ready()

    def wait_ready(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = self.evaluate('document.readyState')
                if r in ('interactive', 'complete'):
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def evaluate(self, expr, await_promise=True, timeout=30):
        res = self.cmd('Runtime.evaluate', expression=expr, awaitPromise=await_promise,
                       returnByValue=True, userGesture=True)
        if res.get('exceptionDetails'):
            raise RuntimeError(json.dumps(res['exceptionDetails'])[:500])
        return res.get('result', {}).get('value')

    def wait_for(self, expr, timeout=25, interval=0.4):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = self.evaluate(expr)
                if last:
                    return last
            except Exception as e:
                last = str(e)[:120]
            time.sleep(interval)
        return last if last is not None else False

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
