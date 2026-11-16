import json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
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
# torneo en curso (para la barra de acción principal)
en_curso=tm.create_tournament(fake.state,"Blitz RR II",2,"Blitz",player_ids=[p['id'] for p in fake.state['players'][:4]])
tm.pair_next_round(fake.state,en_curso['id'])
r1=[g for g in en_curso['games'] if int(g['round'])==1 and not g.get('bye')]
tm.save_results(fake.state,en_curso['id'],[{"game_id":g["id"],"result":1.0 if i%2==0 else 0.0} for i,g in enumerate(r1)])
d=tm.create_draft(fake.state,"Blitz Copa Navidad",1,"Blitz",rounds_total=5,date_start="2027-12-20")
tm.add_draft_entry(fake.state,d['id'],player_id=fake.state['players'][0]['id'])
tm.add_draft_entry(fake.state,d['id'],name="María Fernanda Ruiz",cat="Sub-12",mun="Falcón")

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

CONTRAST = """(()=>{
  function lum(c){const [r,g,b]=c.match(/\\d+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4)});return .2126*r+.7152*g+.0722*b}
  function ratio(a,b){const l1=lum(a),l2=lum(b);const hi=Math.max(l1,l2),lo=Math.min(l1,l2);return (hi+.05)/(lo+.05)}
  const cs=getComputedStyle(document.documentElement);
  const bg=cs.getPropertyValue('--bg2').trim();
  const wrap=document.createElement('div');wrap.style.color=bg;document.body.appendChild(wrap);
  const rgb=getComputedStyle(wrap).color;wrap.remove();
  const hex=h=>{const d=document.createElement('div');d.style.color=h;document.body.appendChild(d);const v=getComputedStyle(d).color;d.remove();return v};
  const t3=hex(cs.getPropertyValue('--text3').trim());
  const t2=hex(cs.getPropertyValue('--text2').trim());
  const gold=hex(cs.getPropertyValue('--gold').trim());
  return {bg2rgb:rgb, text3:ratio(t3,rgb), text2:ratio(t2,rgb), gold:ratio(gold,rgb)};
})()"""

profile=RESULT_DIR + '/chrome-visual'; shutil.rmtree(profile,ignore_errors=True)
c=Chrome(profile, window='390,844')
try:
    c.cmd('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
    c.navigate(base+'/admin.html'); time.sleep(1.5)
    c.evaluate("localStorage.setItem('falconAdminToken','tok-test');localStorage.setItem('falconAdminName','Test');")
    c.cmd('Page.reload'); time.sleep(3)

    print("== Cabecera (Fase 2) ==")
    head=c.evaluate("""(()=>{const l=document.querySelector('.brand-logo');
      const r=document.querySelector('#user .icon-btn');
      const who=document.querySelector('#user .who');
      return {logo:!!l&&l.naturalWidth>0, iconR:r?Math.round(r.getBoundingClientRect().height):0,
              who:who?who.textContent.trim():'', stamp:!!document.querySelector('#user .stamp')}})()""")
    chk('emblema del club en la cabecera', head.get('logo') is True)
    chk('botón de refrescar 40px', head.get('iconR')>=40, head.get('iconR'))
    chk('nombre de sesión visible', bool(head.get('who')), head.get('who'))

    print("== Contraste (sobre tarjeta #1e1e1e) ==")
    r=c.evaluate(CONTRAST)
    chk('text3 ≥ 4.5:1', r['text3']>=4.5, round(r['text3'],2))
    chk('text2 ≥ 4.5:1', r['text2']>=4.5, round(r['text2'],2))
    chk('dorado ≥ 4.5:1', r['gold']>=4.5, round(r['gold'],2))

    print("== Objetivos táctiles ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()")
    time.sleep(0.6)
    sizes=c.evaluate("""(()=>{const o={};for(const s of ['.tab','.btn:not(.btn-sm)','.btn-sm','.btn-primary','.input,select']){
      const e=[...document.querySelectorAll(s)].filter(x=>x.offsetParent);if(!e.length)continue;
      const h=e.map(x=>Math.round(x.getBoundingClientRect().height));o[s]=Math.min(...h);}return o})()""")
    chk('pestañas ≥44', sizes.get('.tab',0)>=44, sizes.get('.tab'))
    chk('botones ≥40', sizes.get('.btn:not(.btn-sm)',0)>=40, sizes.get('.btn:not(.btn-sm)'))
    chk('botones pequeños ≥34', sizes.get('.btn-sm',0)>=34, sizes.get('.btn-sm'))
    chk('inputs ≥44', sizes.get('.input,select',0)>=44, sizes.get('.input,select'))

    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()")
    time.sleep(0.5)
    print("== Pestañas ==")
    tabs=c.evaluate("""(()=>{const n=document.querySelector('nav.tabs');const a=n.querySelector('.tab.active');
      const cs=getComputedStyle(n);
      return {mask:cs.webkitMaskImage||cs.maskImage, icos:n.querySelectorAll('.tab svg').length,
              activoBg:getComputedStyle(a).backgroundColor,
              activoVisible:a.getBoundingClientRect().left>=0 && a.getBoundingClientRect().right<=n.getBoundingClientRect().right+1}})()""")
    chk('degradado de borde', 'gradient' in (tabs.get('mask') or ''), (tabs.get('mask') or '')[:40])
    chk('7 pestañas con icono', tabs.get('icos')==7, tabs.get('icos'))
    chk('pestaña activa con fondo', tabs.get('activoBg') not in ('rgba(0, 0, 0, 0)','transparent'), tabs.get('activoBg'))
    chk('pestaña activa visible', tabs.get('activoVisible') is True)

    print("== Sin scroll horizontal por pestaña ==")
    for tab in ['torneo','nuevo','inscripciones','matches','jugadores','historial','ajustes']:
        c.evaluate(f"[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('{tab[:4]}'))?.click()")
        time.sleep(0.5)
        sw=c.evaluate("document.documentElement.scrollWidth")
        chk(f'{tab}: sin desborde de página', sw<=392, sw)

    print("== Barra de acción del torneo ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()")
    time.sleep(0.6)
    act=c.evaluate("""(()=>{const a=document.querySelector('.actions');
      if(!a)return {};
      const main=a.querySelector('.actions-main .btn-primary');
      const aux=a.querySelectorAll('.actions-aux .btn');
      return {hay:true, primario:!!main, h:main?Math.round(main.getBoundingClientRect().height):0,
              aux:aux.length, sep:getComputedStyle(a.querySelector('.actions-aux')).borderTopWidth}})()""")
    chk('acción principal destacada', act.get('primario') is True)
    chk('acción principal ≥44px', (act.get('h') or 0)>=44, act.get('h'))
    chk('acciones secundarias agrupadas', (act.get('aux') or 0)>=2, act.get('aux'))
    chk('separador entre principal y secundarias', act.get('sep')!='0px', act.get('sep'))

    print("== Tablas ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()"); time.sleep(0.6)
    tbl=c.evaluate("""(()=>{const t=document.querySelector('.standings-tbl');
      if(!t)return {hay:false};
      const rows=[...t.querySelectorAll('tbody tr')];
      const bg=rows.map(r=>getComputedStyle(r).backgroundColor);
      const th=document.querySelector('.standings-tbl th[scope=col]');
      const rtg=document.querySelector('.standings-tbl td:nth-child(5)');
      return {hay:true, zebra:new Set(bg).size>1, scope:!!th, rtgOculta:getComputedStyle(rtg).display==='none',
              scroll:document.querySelector('.standings-tbl').getBoundingClientRect().width<=392}})()""")
    chk('tabla de clasificación presente', tbl.get('hay') is True)
    chk('filas alternas (zebra)', tbl.get('zebra') is True)
    chk('encabezados con scope', tbl.get('scope') is True)
    chk('columnas Rtg/V ocultas en móvil', tbl.get('rtgOculta') is True)
    chk('tabla cabe en 390px', tbl.get('scroll') is True)

    print("== Títulos de sección ==")
    h3=c.evaluate("""(()=>{const h=[...document.querySelectorAll('.card h3')].find(x=>x.offsetParent);
      if(!h)return {};const cs=getComputedStyle(h);return {tt:cs.textTransform, color:cs.color, size:cs.fontSize}})()""")
    chk('h3 en mayúsculas', h3.get('tt')=='uppercase', h3.get('tt'))
    chk('h3 dorado', '255, 213, 79' in (h3.get('color') or ''), h3.get('color'))

    print("== Modal bottom-sheet + foco ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('insc'))?.click()"); time.sleep(0.6)
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Abrir')?.click()"); time.sleep(0.6)
    c.evaluate("(()=>{const b=[...document.querySelectorAll('#app button')].find(x=>x.textContent.trim()==='Eliminar pre-registro');b.focus();b.click()})()"); time.sleep(0.7)
    m=c.evaluate("""(()=>{const el=document.querySelector('#modalWrap .modal');if(!el)return {hay:false};
      const r=el.getBoundingClientRect();const cs=getComputedStyle(el);
      return {hay:true, bottom:Math.round(r.bottom), vh:window.innerHeight,
              topRadius:cs.borderTopLeftRadius, maxW:cs.maxWidth,
              foco:document.activeElement?document.activeElement.id:''}})()""")
    chk('modal abierto', m.get('hay') is True)
    chk('pegado al borde inferior', abs(m.get('bottom',0)-m.get('vh',0))<=2, (m.get('bottom'),m.get('vh')))
    chk('esquinas superiores redondeadas', m.get('topRadius') not in ('0px',''), m.get('topRadius'))
    chk('foco inicial dentro del modal', m.get('foco') in ('modalCancel','modalOk'), m.get('foco'))
    c.cmd('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    c.cmd('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    time.sleep(0.5)
    after=c.evaluate("""(()=>{const open=document.querySelector('#modalWrap').classList.contains('show');
      const a=document.activeElement;return {open, txt:a?a.textContent.trim().slice(0,20):''}})()""")
    chk('Escape cierra', after.get('open') is False)
    chk('foco devuelto al botón que abrió', 'Eliminar' in (after.get('txt') or ''), after.get('txt'))

    print("== Estados vacíos y toasts ==")
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('juga'))?.click()"); time.sleep(0.6)
    c.evaluate("(()=>{const i=document.querySelector('#app input[placeholder^=\"Buscar\"]');i.value='zzzz';i.dispatchEvent(new Event('input',{bubbles:true}))})()")
    time.sleep(0.6)
    emp=c.evaluate("(()=>{const e=[...document.querySelectorAll('.empty')].find(x=>x.offsetParent);return e?{svg:!!e.querySelector('svg.empty-ic'),txt:e.textContent.trim().slice(0,30)}:{}})()")
    chk('estado vacío con icono', emp.get('svg') is True, emp.get('txt'))
    c.evaluate("[...document.querySelectorAll('#tabs .tab')].find(b=>b.textContent.trim().toLowerCase().startsWith('torn'))?.click()"); time.sleep(0.6)
    c.evaluate("[...document.querySelectorAll('#app button')].find(b=>b.textContent.trim()==='Actualizar')?.click()"); time.sleep(1.0)
    tst=c.evaluate("(()=>{const t=document.querySelector('#toast');return {svg:!!t.querySelector('svg'),txt:t.textContent.trim(),show:t.classList.contains('show')}})()")
    chk('toast con icono', tst.get('svg') is True, tst.get('txt'))
finally:
    c.close(); shutil.rmtree(profile,ignore_errors=True)
srv.shutdown()
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
