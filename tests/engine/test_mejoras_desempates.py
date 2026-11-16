import json, os, sys, threading, time, shutil
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT); sys.path.insert(0, ROOT)
os.chdir(ROOT)
from server import store
import api.index as api
from engine import core, state as st
from engine import tournaments as tm

ok=True
def chk(l,c,e=""):
    global ok
    if not c: ok=False
    print(("  OK  " if c else " FALLA")+f" {l} {e}")

print("== 1. Criterios por tipo de torneo ==")
esperados = {
  ("SUIZO","blitz"): ["puntos","buchholz_cut1","buchholz_total","aroc1","direct_encounter"],
  ("ROUND_ROBIN_UNA_VUELTA","rapid"): ["puntos","direct_encounter","sonneborn_berger","victorias","koya"],
  ("ROUND_ROBIN_UNA_VUELTA","blitz"): ["puntos","direct_encounter","sonneborn_berger","victorias"],
  ("ROUND_ROBIN_DOS_VUELTAS","rapid"): ["puntos","sonneborn_berger","victorias","direct_encounter"],
  ("ROUND_ROBIN_DOS_VUELTAS","bullet"): ["puntos","direct_encounter","victorias","sonneborn_berger"],
}
for (nombre,ritmo),exp in esperados.items():
    tipo = getattr(core.TipoTorneo, nombre)
    got = core.criterios_desempate(tipo, ritmo)
    chk(f"{nombre} {ritmo}", got==exp, got)
    etiquetas=[c['label'] for c in core.etiquetas_criterios(tipo,ritmo)]
    chk(f"  etiquetas {nombre}", etiquetas[0]=="Pts", etiquetas)

print("== 2. BH1 con un solo rival ==")
J={"A":{"id":1,"puntos":1.0,"rating":2000,"historial":["B"],"enfrentamientos":{"B":[1.0]}},
   "B":{"id":2,"puntos":2.0,"rating":1900,"historial":["A"],"enfrentamientos":{"A":[0.0]}}}
chk("BH1 con 1 rival = 0", core.calcular_buchholz_cut1("A",J)==0.0, core.calcular_buchholz_cut1("A",J))
J2={"A":{"id":1,"puntos":2.0,"rating":2000,"historial":["B","C"],"enfrentamientos":{"B":[1.0],"C":[1.0]}},
    "B":{"id":2,"puntos":1.0,"rating":1900,"historial":["A","C"],"enfrentamientos":{"A":[0.0],"C":[1.0]}},
    "C":{"id":3,"puntos":0.0,"rating":1800,"historial":["A","B"],"enfrentamientos":{"A":[0.0],"B":[0.0]}}}
chk("BH1 con 2 rivales = BH - más bajo", core.calcular_buchholz_cut1("A",J2)==1.0, core.calcular_buchholz_cut1("A",J2))

print("== 3. El payload expone los criterios ==")
state=st.new_state()
ids=[]
for n in ["Uno","Dos","Tres","Cuatro"]:
    p=tm.create_player(state,n,"Falcón","-"); ids.append(p["id"])
    st._rating_slot(p,"Blitz").update({"rating":1500.0,"rd":100.0,"sigma":0.06,"var":0,"last":None})
t=tm.create_tournament(state,"Suizo X",1,"Blitz",player_ids=ids)
payload=tm.tournament_payload(state,t)
chk("payload con criterios", bool(payload.get("criterios")), payload.get("criterios"))
chk("criterios del suyo", [c["key"] for c in payload["criterios"]]==["puntos","buchholz_cut1","buchholz_total","aroc1","direct_encounter"], payload.get("criterios"))
print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
