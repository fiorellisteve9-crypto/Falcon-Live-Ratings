import sys, json, random, math

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
from engine import state as st
from engine import tournaments as tm
from engine import core

RATINGS = [2050,1980,1930,1880,1840,1800,1760,1710,1660,1610,1560,1500]
NOMBRES = ["Ana Pérez","Luis Gómez","María Ruiz","Carlos Díaz","Sofía León","Diego Mora",
           "Valentina Ríos","Andrés Silva","Camila Torres","Javier Paredes","Lucía Reyes","Miguel Soto"]

def p_win(rw, rb):
    d=(rw-rb)/400.0
    return 1.0/(1.0+10**(-d*0.7))

def simular(tipo, ritmo, n_jugadores, semilla):
    random.seed(semilla)
    state = st.new_state()
    ids=[]
    for i in range(n_jugadores):
        p=tm.create_player(state, NOMBRES[i], "Falcón", "Absoluta")
        ids.append(p["id"])
        st._rating_slot(p, ritmo).update({"rating":float(RATINGS[i]),"rd":100.0,"sigma":0.06,"var":0,"last":None})
    nombre = {2:"Round Robin 1 vuelta", 3:"Round Robin 2 vueltas"}[tipo]
    t=tm.create_tournament(state, f"{nombre} simulado", tipo, ritmo, player_ids=ids)
    total_rondas=int(t["rounds_total"])
    for rnd in range(1, total_rondas+1):
        tm.pair_next_round(state, t["id"])
        games=[g for g in t["games"] if int(g["round"])==rnd]
        res=[]
        for g in games:
            if g.get("bye"): continue
            rw=next(p["ratings"][ritmo]["rating"] for p in state["players"] if p["id"]==g["white_id"])
            rb=next(p["ratings"][ritmo]["rating"] for p in state["players"] if p["id"]==g["black_id"])
            pw=p_win(rw,rb); x=random.random()
            r=1.0 if x<pw*0.78 else (0.5 if x<pw*0.78+0.30 else 0.0)
            res.append({"game_id":g["id"],"result":r})
        tm.save_results(state, t["id"], res)
    tm.close_tournament(state, t["id"])
    return state, t, total_rondas

def referencia(state, t, rondas, ritmo):
    """Recálculo independiente a partir de las partidas."""
    players={p["name"]:p for p in state["players"]}
    rating_end={}
    for part in t["participants"]:
        nm=next(p["name"] for p in state["players"] if p["id"]==part["player_id"])
        rating_end[nm]=float(part["rating_start"])+float(part["variation_total"] or 0)
    pts={n:0.0 for n in players}; opps={n:[] for n in players}
    res_vs={n:{} for n in players}; byes={n:0 for n in players}
    for g in sorted(t["games"], key=lambda g:(int(g["round"]),int(g["id"]))):
        if g.get("result") is None: continue
        wn=next(p["name"] for p in state["players"] if p["id"]==g["white_id"])
        if g.get("bye") or g.get("black_id") is None:
            pts[wn]+=1.0; byes[wn]+=1; continue
        bn=next(p["name"] for p in state["players"] if p["id"]==g["black_id"])
        r=float(g["result"]); pts[wn]+=r; pts[bn]+=1-r
        opps[wn].append(bn); opps[bn].append(wn)
        res_vs[wn].setdefault(bn,[]).append(r); res_vs[bn].setdefault(wn,[]).append(1-r)
    ref={}
    for n in players:
        u=set(opps[n])
        low=sorted(pts[o] for o in u)
        bh=sum(pts[o] for o in u)
        bh1=sum(low[1:])
        sb=sum((pts[o] if r==1.0 else pts[o]*0.5 if r==0.5 else 0.0) for o,rs in res_vs[n].items() for r in rs)
        wins=sum(1 for rs in res_vs[n].values() for r in rs if r==1.0)
        koya=sum(r for o,rs in res_vs[n].items() if pts[o]>=rondas/2 for r in rs)
        aro=sorted(rating_end[o] for o in u); aro_cut=aro[1:] if len(aro)>=2 else aro
        aroc1=sum(aro_cut)/len(aro_cut) if aro_cut else 0.0
        rr=[rating_end[o] for o in opps[n]]   # una entrada por partida (rivales repetidos cuentan)
        if rr:
            ra=sum(rr)/len(rr); p=(pts[n]-byes[n])/len(rr)
            tpr=int(max(rr)+400) if p>=1.0 else (int(min(rr)-400) if p<=0.0 else int(ra+(p-0.5)*800))
        else: tpr=0
        de=sum(r for o,rs in res_vs[n].items() if abs(pts[o]-pts[n])<1e-9 for r in rs)
        ref[n]=dict(puntos=pts[n],bh1=bh1,bh=bh,sb=sb,wins=wins,koya=koya,aroc1=aroc1,tpr=tpr,de=de,
                    bh_por_partida=sum(pts[o] for o in opps[n]),
                    bh1_por_partida=(sum(sorted(pts[o] for o in opps[n])[1:]) if len(opps[n])>=2 else 0.0))
    return ref

CAMPOS=[("puntos","puntos"),("bh1","buchholz_cut1"),("bh","buchholz_total"),("sb","sonneborn_berger"),
        ("wins","victorias"),("koya","koya"),("aroc1","aroc1"),("tpr","tpr"),("de","direct_encounter")]

def auditar(tipo, ritmo, n, semilla):
    state,t,rondas = simular(tipo, ritmo, n, semilla)
    filas = st.standings(state, t, rating_mode="tournament_end")
    ref = referencia(state, t, rondas, ritmo)
    tipo_obj = core.TipoTorneo.desde_valor(tipo)
    criterios = core.criterios_desempate(tipo_obj, ritmo)
    resultado = {
        "tipo": {2:"Round Robin 1 vuelta",3:"Round Robin 2 vueltas"}[tipo],
        "ritmo": ritmo, "jugadores": n, "rondas": rondas,
        "criterios": [core.CRITERIO_LABELS[k] for k in criterios],
        "partidas": len([g for g in t["games"] if not g.get("bye")]),
        "byes": len([g for g in t["games"] if g.get("bye")]),
        "comparacion": {}, "orden_ok": False, "tabla": [],
    }
    for key, attr in CAMPOS:
        difs=[(f.nombre, getattr(f,attr), ref[f.nombre][key])
              for f in filas if abs(float(getattr(f,attr))-float(ref[f.nombre][key]))>1e-6]
        resultado["comparacion"][key]= "OK" if not difs else f"{len(difs)} diferencias: {difs[:2]}"
    # orden con la clave definida
    mapa={"puntos":"puntos","buchholz_cut1":"bh1","buchholz_total":"bh","sonneborn_berger":"sb",
          "victorias":"wins","koya":"koya","aroc1":"aroc1","direct_encounter":"de"}
    def key_ref(n):
        return tuple(ref[n][mapa[k]] for k in criterios)
    esperado=sorted(ref.keys(), key=key_ref, reverse=True)
    actual=[f.nombre for f in filas]
    resultado["orden_ok"] = esperado==actual
    if n > 1:
        top=max(filas, key=lambda f: f.puntos)
        resultado["ejemplo_bh"]={
            "jugador": top.nombre,
            "bh_mostrado": round(float(ref[top.nombre]["bh"]),1),
            "bh_si_contara_cada_partida": round(float(ref[top.nombre]["bh_por_partida"]),1),
            "bh1_mostrado": round(float(ref[top.nombre]["bh1"]),1),
            "bh1_si_contara_cada_partida": round(float(ref[top.nombre]["bh1_por_partida"]),1),
        }
    resultado["tabla"]=[{"pos":i,"nombre":f.nombre,"pts":f.puntos,
                         **{k: getattr(f,attr) for k,attr in CAMPOS}}
                        for i,f in enumerate(filas,1)]
    return resultado

if __name__=="__main__":
    casos=[(2,"Rapid",8,101),(2,"Blitz",7,202),(3,"Rapid",6,303),(3,"Blitz",7,404)]
    salida=[]
    for tipo,ritmo,n,semilla in casos:
        r=auditar(tipo,ritmo,n,semilla)
        salida.append(r)
        print(f"== {r['tipo']} {r['ritmo']} · {n} jugadores · {r['rondas']} rondas ==")
        print("   criterios:", " · ".join(r['criterios']))
        print("   partidas:", r['partidas'], "| descansos:", r['byes'])
        for k,v in r['comparacion'].items():
            print(f"   {k:8}: {v}")
        print("   orden correcto:", r['orden_ok'])
        print()
    json.dump(salida, open(RESULT_DIR + '/rr_result.json','w'), ensure_ascii=False, indent=1)
    print("guardado rr_result.json")
