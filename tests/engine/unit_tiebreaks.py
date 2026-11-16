import sys

import os
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
SEED = os.environ.get('FALCON_SEED', '/sdcard/Download/falcon_seed_state.json')
sys.path.insert(0, ROOT)
from engine import core

ok = True
def chk(label, got, exp, tol=1e-9):
    global ok
    good = abs(float(got)-float(exp)) <= tol if isinstance(exp,(int,float)) else got==exp
    if not good: ok=False
    print(("  OK  " if good else " FALLA") + f" {label}: motor={got} esperado={exp}")

# Caso de mano: A gana a B y C; B gana a C; C pierde todo
J = {
 "A": {"id":1,"puntos":2.0,"rating":2000,"historial":["B","C"],"enfrentamientos":{"B":[1.0],"C":[1.0]}},
 "B": {"id":2,"puntos":1.0,"rating":1900,"historial":["A","C"],"enfrentamientos":{"A":[0.0],"C":[1.0]}},
 "C": {"id":3,"puntos":0.0,"rating":1800,"historial":["A","B"],"enfrentamientos":{"A":[0.0],"B":[0.0]}},
}
print("== Caso de mano (A 2, B 1, C 0) ==")
chk("BH de A (1+0)", core.calcular_buchholz_total("A",J), 1.0)
chk("BH1 de A (quita el más bajo)", core.calcular_buchholz_cut1("A",J), 1.0)
chk("SB de A (1*1 + 1*0)", core.calcular_sonneborn_berger("A",J), 1.0)
chk("Victorias de A", core.calcular_victorias("A",J), 2)
chk("Koya de A (B tiene 1 pto = 50% de 2)", core.calcular_koya("A",J), 1.0)
chk("AROC1 de A (quita 1800)", core.calcular_aroc1("A",J), 1900.0)
chk("TPR de A (100% -> max+400)", core.calcular_tpr([1900,1800],2.0), 2300)
chk("DE de A (nadie empatado a 2)", core.calcular_direct_encounter("A",J), 0.0)
chk("DE de B vs C (B y C distintos)", core.calcular_direct_encounter("B",J), 0.0)

print("== Empate a puntos: encuentro directo ==")
J2 = {
 "A": {"id":1,"puntos":1.0,"rating":2000,"historial":["B"],"enfrentamientos":{"B":[1.0]}},
 "B": {"id":2,"puntos":1.0,"rating":1900,"historial":["A"],"enfrentamientos":{"A":[0.0]}},
}
chk("DE del ganador del duelo", core.calcular_direct_encounter("A",J2), 1.0)
chk("DE del perdedor del duelo", core.calcular_direct_encounter("B",J2), 0.0)

print("== TPR extremos ==")
chk("TPR con 0% -> min-400", core.calcular_tpr([1900,1800],0.0), 1400)
chk("TPR con 50% -> promedio", core.calcular_tpr([1900,1800],1.0), 1850)
chk("TPR sin partidas", core.calcular_tpr([],0.0), 0)

print("== Koya: umbral exacto 50% ==")
# 4 rondas -> umbral 2.0 ; B tiene exactamente 2.0 y debe contar
J3 = {
 "A": {"id":1,"puntos":3.0,"rating":2000,"historial":["B","C","D","E"],"enfrentamientos":{"B":[1.0],"C":[1.0],"D":[1.0],"E":[0.0]}},
 "B": {"id":2,"puntos":2.0,"rating":1900,"historial":["A","C","D","E"],"enfrentamientos":{"A":[0.0],"C":[0.5],"D":[0.5],"E":[1.0]}},
 "C": {"id":3,"puntos":1.5,"rating":1800,"historial":["A","B","D","E"],"enfrentamientos":{"A":[0.0],"B":[0.5],"D":[0.0],"E":[1.0]}},
 "D": {"id":4,"puntos":1.5,"rating":1700,"historial":["A","B","C","E"],"enfrentamientos":{"A":[0.0],"B":[0.5],"C":[1.0],"E":[0.0]}},
 "E": {"id":5,"puntos":2.0,"rating":1600,"historial":["A","B","C","D"],"enfrentamientos":{"A":[1.0],"B":[0.0],"C":[0.0],"D":[1.0]}},
}
chk("Koya de A (cuenta B=2.0 exacto y E=2.0)", core.calcular_koya("A",J3), 1.0)

print("== BH1 con un solo rival (caso límite) ==")
J4 = {"A":{"id":1,"puntos":1.0,"rating":2000,"historial":["B"],"enfrentamientos":{"B":[1.0]}},
      "B":{"id":2,"puntos":2.0,"rating":1900,"historial":["A"],"enfrentamientos":{"A":[0.0]}}}
print("   BH1 de A con 1 rival:", core.calcular_buchholz_cut1("A",J4), "(regla estándar daría 0)")

print("\nRESULTADO:", "TODO OK" if ok else "HAY FALLOS")
