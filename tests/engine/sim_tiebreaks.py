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

random.seed(20261113)

NOMBRES = [
 ("Ana Pérez", 2050), ("Luis Gómez", 1980), ("María Ruiz", 1930), ("Carlos Díaz", 1880),
 ("Sofía León", 1840), ("Diego Mora", 1800), ("Valentina Ríos", 1760), ("Andrés Silva", 1710),
 ("Camila Torres", 1660), ("Javier Paredes", 1610), ("Lucía Reyes", 1560), ("Miguel Soto", 1500),
 ("Elena Vargas", 1440), ("Pedro Navas", 1380), ("Rosa Medina", 1320)
]

state = st.new_state()
ids = []
for name, rating in NOMBRES:
    p = tm.create_player(state, name, "Falcón", "Absoluta")
    ids.append(p["id"])
    # sembrar rating en Rapid
    slot = st._rating_slot(p, "Rapid")
    slot.update({"rating": float(rating), "rd": 100.0, "sigma": 0.06, "var": 0, "last": None})

RONDAS = 7
t = tm.create_tournament(state, "Suizo de prueba 7 rondas", 1, "Rapid", rounds_total=RONDAS, player_ids=ids)
print("Torneo:", t["name"], "| jugadores:", len(t["participants"]), "| rondas:", t["rounds_total"])

def p_win(rw, rb):
    d = (rw - rb) / 400.0
    return 1.0 / (1.0 + 10 ** (-d * 0.7))   # algo aplanado, mas tablas

def simulate_round(rnd):
    tm.pair_next_round(state, t["id"])
    games = [g for g in t["games"] if int(g["round"]) == rnd]
    res = []
    for g in games:
        if g.get("bye"):
            continue
        rw = next(p["ratings"]["Rapid"]["rating"] for p in state["players"] if p["id"] == g["white_id"])
        rb = next(p["ratings"]["Rapid"]["rating"] for p in state["players"] if p["id"] == g["black_id"])
        pw = p_win(rw, rb)
        x = random.random()
        if x < pw * 0.78:
            r = 1.0
        elif x < pw * 0.78 + 0.30:
            r = 0.5
        else:
            r = 0.0
        res.append({"game_id": g["id"], "result": r})
    tm.save_results(state, t["id"], res)
    print(f"  ronda {rnd}: {len(games)} partidas ({sum(1 for g in games if g.get('bye'))} byes)")

for r in range(1, RONDAS + 1):
    simulate_round(r)

tm.close_tournament(state, t["id"])
filas = st.standings(state, t, rating_mode="tournament_end")
print("\nClasificación del motor:")
print(f"{'#':>2} {'Jugador':<18} {'Pts':>4} {'BH1':>5} {'BH':>5} {'SB':>5} {'W':>2} {'Koya':>5} {'AROC1':>6} {'TPR':>5} {'DE':>4}")
for i, f in enumerate(filas, 1):
    print(f"{i:>2} {f.nombre:<18} {f.puntos:>4} {f.buchholz_cut1:>5} {f.buchholz_total:>5} "
          f"{f.sonneborn_berger:>5} {f.victorias:>2} {f.koya:>5} {f.aroc1:>6.1f} {f.tpr:>5} {f.direct_encounter:>4}")

# ───────────────────────── referencia independiente ─────────────────────────
players = {p["name"]: p for p in state["players"]}
rating_end = {}
for part in t["participants"]:
    nm = next(p["name"] for p in state["players"] if p["id"] == part["player_id"])
    rating_end[nm] = float(part["rating_start"]) + float(part["variation_total"] or 0)

pts = {n: 0.0 for n in players}
opps = {n: [] for n in players}       # rivales reales (con repetición)
res_vs = {n: {} for n in players}     # rival -> lista de resultados del jugador
byes = {n: 0 for n in players}
for g in sorted(t["games"], key=lambda g: (int(g["round"]), int(g["id"]))):
    if g.get("result") is None:
        continue
    wn = next(p["name"] for p in state["players"] if p["id"] == g["white_id"])
    if g.get("bye") or g.get("black_id") is None:
        pts[wn] += 1.0; byes[wn] += 1; continue
    bn = next(p["name"] for p in state["players"] if p["id"] == g["black_id"])
    r = float(g["result"])
    pts[wn] += r; pts[bn] += 1 - r
    opps[wn].append(bn); opps[bn].append(wn)
    res_vs[wn].setdefault(bn, []).append(r)
    res_vs[bn].setdefault(wn, []).append(1 - r)

rounds = RONDAS
ref = {}
for n in players:
    u = set(opps[n])
    bh = sum(pts[o] for o in u)
    low = sorted(pts[o] for o in u)
    bh1 = (bh - low[0]) if len(low) >= 2 else (low[0] if low else 0.0)   # regla documentada en el motor
    sb = 0.0
    for o, rs in res_vs[n].items():
        for r in rs:
            if r == 1.0: sb += pts[o]
            elif r == 0.5: sb += pts[o] * 0.5
    wins = sum(1 for rs in res_vs[n].values() for r in rs if r == 1.0)
    koya = sum(r for o, rs in res_vs[n].items() if pts[o] >= rounds/2 for r in rs)
    aro = sorted(rating_end[o] for o in u)
    aro_cut = aro[1:] if len(aro) >= 2 else aro
    aroc1 = sum(aro_cut)/len(aro_cut) if aro_cut else 0.0
    rr = [rating_end[o] for o in u]
    if rr:
        ra = sum(rr)/len(rr); p = (pts[n]-byes[n])/len(rr)
        if p >= 1.0: tpr = int(max(rr)+400)
        elif p <= 0.0: tpr = int(min(rr)-400)
        else: tpr = int(ra + (p-0.5)*800)
    else:
        tpr = 0
    de = sum(r for o, rs in res_vs[n].items() if abs(pts[o]-pts[n]) < 1e-9 for r in rs)
    ref[n] = dict(puntos=pts[n], bh1=bh1, bh=bh, sb=sb, wins=wins, koya=koya, aroc1=aroc1, tpr=tpr, de=de)

CAMPS = [("puntos","puntos"), ("bh1","buchholz_cut1"), ("bh","buchholz_total"),
         ("sb","sonneborn_berger"), ("wins","victorias"), ("koya","koya"),
         ("aroc1","aroc1"), ("tpr","tpr"), ("de","direct_encounter")]
fallos = []
print("\nComparación motor vs referencia:")
for key, attr in CAMPS:
    difs = []
    for f in filas:
        v_eng = getattr(f, attr)
        v_ref = ref[f.nombre][key]
        if abs(float(v_eng) - float(v_ref)) > 1e-6:
            difs.append((f.nombre, v_eng, v_ref))
    if difs:
        fallos.append((key, difs))
        print(f"  {key}: {len(difs)} diferencias -> {difs[:3]}")
    else:
        print(f"  {key}: OK en los {len(filas)} jugadores")

# orden
def key_swiss(f):
    return (f.puntos, f.buchholz_cut1, f.buchholz_total, f.aroc1, f.direct_encounter)
orden_esperado = [f.nombre for f in sorted(filas, key=key_swiss, reverse=True)]
orden_actual = [f.nombre for f in filas]
print("\nOrden por clave documentada:", "OK" if orden_esperado == orden_actual else "DIFERENTE")
print("Puntos descendentes:", all(filas[i].puntos >= filas[i+1].puntos for i in range(len(filas)-1)))

json.dump({"filas":[{"nombre":f.nombre,"puntos":f.puntos,"bh1":f.buchholz_cut1,"bh":f.buchholz_total,
  "sb":f.sonneborn_berger,"wins":f.victorias,"koya":f.koya,"aroc1":f.aroc1,"tpr":f.tpr,"de":f.direct_encounter}
  for f in filas],
  "partidas":len([g for g in t["games"] if not g.get("bye")]),
  "byes":len([g for g in t["games"] if g.get("bye")]),
  "fallos":[[k,[[n,a,b] for n,a,b in d]] for k,d in fallos]}, open(RESULT_DIR + '/tiebreaks_result.json','w'), ensure_ascii=False, indent=1)
