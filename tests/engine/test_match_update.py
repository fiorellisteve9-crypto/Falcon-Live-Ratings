import sys, json, copy, importlib.util

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
from engine import tournaments as tm
from engine import state as st

def fresh():
    s={"version":2,"next_ids":{"player":1,"tournament":1,"game":1,"match":1},"players":[],
       "tournaments":[],"matches":[],"ranking_snapshot":{}}
    a=tm.create_player(s,"Ana","Falcón","-")
    b=tm.create_player(s,"Beto","Falcón","-")
    return s,a,b

def rating(s,pid,rhythm="Blitz"):
    p=tm.player_by_id(s,pid)
    sl=p["ratings"][rhythm]
    return round(sl["rating"],6), round(sl["rd"],6), round(sl["sigma"],6), sl.get("last")

ok=True
def chk(label,cond,extra=""):
    global ok
    if not cond: ok=False
    print(("  OK  " if cond else " FALLA")+f" {label} {extra}")

print("== 1. update_match reproduce la creación desde cero ==")
s,a,b=fresh()
m=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-09")
r_after=rating(s,a["id"])
s2,a2,b2=fresh()
m2=tm.create_match(s2,a2["id"],b2["id"],"Blitz",[0,1,1],"2026-08-09")
r_expected=rating(s2,a2["id"])
s,a,b=fresh()
m=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-09")
tm.update_match(s,m["id"],[0,1,1],"2026-08-09")
r_fixed=rating(s,a["id"])
chk("rating corregida = creada desde cero", r_fixed==r_expected, f"{r_fixed} vs {r_expected}")
chk("score corregido 1-2", (s["matches"][0]["score_p1"],s["matches"][0]["score_p2"])==(1.0,2.0),
    (s["matches"][0]["score_p1"],s["matches"][0]["score_p2"]))

print("== 2. corregir y reaplicar matches posteriores ==")
s,a,b=fresh()
m1=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-01")
m2=tm.create_match(s,a["id"],b["id"],"Blitz",[0,1,1],"2026-08-05")
m3=tm.create_match(s,a["id"],b["id"],"Blitz",[1,1,0],"2026-08-09")
# referencia: m1 corregida + m2 + m3 desde cero
ref,ra,rb=fresh()
rm1=tm.create_match(ref,ra["id"],rb["id"],"Blitz",[0,1,1],"2026-08-01")
rm2=tm.create_match(ref,ra["id"],rb["id"],"Blitz",[0,1,1],"2026-08-05")
rm3=tm.create_match(ref,ra["id"],rb["id"],"Blitz",[1,1,0],"2026-08-09")
r_ref=rating(ref,ra["id"])
tm.update_match(s,m1["id"],[0,1,1],"2026-08-01")
r_fix=rating(s,a["id"])
chk("rating final tras corregir = referencia", r_fix==r_ref, f"{r_fix} vs {r_ref}")
chk("match posterior reaplicado (score)", s["matches"][1]["score_p1"]==ref["matches"][1]["score_p1"],
    (s["matches"][1]["score_p1"],ref["matches"][1]["score_p1"]))
chk("match posterior reaplicado (rating final)", abs(s["matches"][1]["rating_final_p1"]-ref["matches"][1]["rating_final_p1"])<1e-9,
    (s["matches"][1]["rating_final_p1"],ref["matches"][1]["rating_final_p1"]))
chk("ultimo match intacto en valor", abs(s["matches"][2]["rating_final_p1"]-ref["matches"][2]["rating_final_p1"])<1e-9,
    (s["matches"][2]["rating_final_p1"],ref["matches"][2]["rating_final_p1"]))

print("== 3. delete_match revierte ==")
s,a,b=fresh()
m1=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-01")
m2=tm.create_match(s,a["id"],b["id"],"Blitz",[1,1,1],"2026-08-05")
r_before=rating(s,a["id"])
tm.delete_match(s,m1["id"])
r_after=rating(s,a["id"])
chk("match eliminado del estado", len(s["matches"])==1, len(s["matches"]))
# referencia: solo m2
ref,ra,rb=fresh()
rm2=tm.create_match(ref,ra["id"],rb["id"],"Blitz",[1,1,1],"2026-08-05")
chk("rating tras borrar = referencia", rating(ref,ra["id"])==r_after, f"{rating(ref,ra['id'])} vs {r_after}")

print("== 4. correccion de fecha ==")
s,a,b=fresh()
m=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-09")
tm.update_match(s,m["id"],None,"2026-08-02")
chk("fecha actualizada", s["matches"][0]["fecha"].startswith("2026-08-02"), s["matches"][0]["fecha"])
try:
    s,a,b=fresh()
    m=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,0.5],"2026-08-09")
    tm.update_match(s,m["id"],None,"2027-01-01")
    chk("rechaza fecha futura", False)
except Exception as e:
    chk("rechaza fecha futura", "futura" in str(e), str(e))

print("== 5. correccion de rating/RD del jugador ==")
s,a,b=fresh()
tm.update_player(s,a["id"],{"name":"Ana","mun":"Falcón","cat":"-","rhythm":"Blitz","rating":2186,"rd":99.23})
sl=a["ratings"]["Blitz"]
chk("rating corregido", abs(sl["rating"]-2186)<1e-9, sl["rating"])
chk("RD corregido", abs(sl["rd"]-99.23)<1e-9, sl["rd"])
chk("otros ritmos intactos", a["ratings"]["Rapid"]["rating"]==1500 and a["ratings"]["Bullet"]["rating"]==1500)
tm.update_player(s,a["id"],{"name":"Ana","rhythm":"Todos","rating":2000})
chk("Todos aplica a los 3 ritmos", all(abs(a["ratings"][r]["rating"]-2000)<1e-9 for r in ("Rapid","Blitz","Bullet")),
    [a["ratings"][r]["rating"] for r in ("Rapid","Blitz","Bullet")])
for bad in ({"rhythm":"Blitz","rating":500},{"rhythm":"Blitz","rating":5000},{"rhythm":"Blitz","rd":10},
            {"rhythm":"Blitz","rd":600},{"rhythm":"Foo","rating":2000},{"rating":2000}):
    try:
        tm.update_player(s,a["id"],bad)
        chk(f"rechaza {bad}", False)
    except Exception as e:
        chk(f"rechaza {bad}", True, str(e)[:60])

print("== 6. match antiguo sin detalle: reconstruccion ==")
s,a,b=fresh()
m=tm.create_match(s,a["id"],b["id"],"Blitz",[1,0,1],"2026-08-09")
del s["matches"][0]["resultados"]
rec=tm._match_results(s["matches"][0])
chk("reconstruye n partidas", len(rec)==3, rec)
p1pts=sum(rec[i] if i%2==0 else (1-rec[i]) for i in range(len(rec)))
chk("reconstruye el marcador (P1 suma 3.0)", abs(p1pts-3.0)<1e-9, (p1pts,rec))
chk("reconstruccion usa 1/0/0.5", all(v in (0.0,0.5,1.0) for v in rec), rec)

print("== 7. create_match sin regresiones (comparado con el motor anterior) ==")
# La copia del motor anterior solo existe si se guardó a mano; si no, se omite.
OLD_ENGINE = os.path.join(ROOT, "tournaments.bak.py")
if os.path.exists(OLD_ENGINE):
    import engine
    spec=importlib.util.spec_from_file_location("engine.tournaments_old",OLD_ENGINE)
    old=importlib.util.module_from_spec(spec)
    sys.modules["engine.tournaments_old"]=old
    spec.loader.exec_module(old)
    base=json.load(open(SEED)); base.pop('live',None)
    for label,mod in (("nuevo",tm),("viejo",old)):
        s=copy.deepcopy(base)
        mod.create_match(s,2,5,"Blitz",[1,0,0.5,1,0.5],"2026-08-09")
        globals()[f"res_{label}"]=(s["matches"][-1]["rating_final_p1"],s["matches"][-1]["rd_final_p1"],
                                   s["matches"][-1]["var_p1"],s["matches"][-1]["score_p1"])
    chk("create_match identico al anterior", res_nuevo==res_viejo, f"{res_nuevo} vs {res_viejo}")
else:
    print("   (omitido: no hay copia del motor anterior en el repo)")

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
