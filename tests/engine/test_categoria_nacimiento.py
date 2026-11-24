"""Categoría automática por año de nacimiento (regla de año simple).

La regla acordada es: edad = año en curso - año de nacimiento, y se asigna
la primera Sub-X que cubre esa edad (Sub-8, 10, 12, 14, 16, 18, 20).
Adultos: 21-49 Absoluta, 50-64 Senior, 65+ Súper Senior.

Además de la tabla de conversión, comprueba que la categoría se recalcula
siempre desde el año de nacimiento: al cambiar de año, cambia sola sin editar
al jugador, tanto en el panel como en el JSON público.

No necesita navegador.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from engine import live as lv
from engine import tournaments as tm

ok = True


def chk(label, cond, extra=""):
    global ok
    if not cond:
        ok = False
    print(("  OK   " if cond else "  FALLA ") + label + ((" · " + str(extra)[:120]) if extra != "" else ""))


print("== 1. Regla de conversión (año 2026) ==")
casos = {
    2019: "Sub-8",    # 7 años -> la categoría más baja
    2018: "Sub-8",    # 8
    2017: "Sub-10",   # 9
    2016: "Sub-10",   # 10
    2015: "Sub-12",   # 11
    2014: "Sub-12",   # 12
    2013: "Sub-14",   # 13
    2012: "Sub-14",   # 14
    2011: "Sub-16",   # 15
    2010: "Sub-16",   # 16
    2009: "Sub-18",   # 17
    2008: "Sub-18",   # 18
    2007: "Sub-20",   # 19
    2006: "Sub-20",   # 20
    2005: "Absoluta", # 21
    1980: "Absoluta", # 46
    1976: "Senior",   # 50
    1962: "Senior",   # 64
    1961: "Súper Senior",  # 65
}
for nacido, esperado in casos.items():
    chk(f"{nacido} -> {esperado}", tm.categoria_por_nacimiento(nacido, 2026) == esperado,
        tm.categoria_por_nacimiento(nacido, 2026))
for invalido in ("", None, "abc", 1899, 2027, "2012.5"):
    chk(f"sin categoría para {invalido!r}", tm.categoria_por_nacimiento(invalido, 2026) is None,
        tm.categoria_por_nacimiento(invalido, 2026))

print("== 2. Crear jugador con año ==")
state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
ana = tm.create_player(state, "Ana", mun="Falcón", birth_year=2012)
chk("guarda el año", ana.get("birth_year") == 2012, ana.get("birth_year"))
chk("calcula la categoría", ana.get("cat") == tm.categoria_por_nacimiento(2012), ana.get("cat"))
beto = tm.create_player(state, "Beto", mun="Falcón", cat="Senior", birth_year="")
chk("sin año conserva la categoría que se le dé", beto.get("cat") == "Senior", beto.get("cat"))
chk("sin año queda sin año de nacimiento", beto.get("birth_year") is None, beto.get("birth_year"))
carla = tm.create_player(state, "Carla", mun="Falcón")
chk("jugador importado sin año sigue con '-'", carla.get("cat") == "-", carla.get("cat"))

print("== 3. Editar el año ==")
tm.update_player(state, 1, {"birth_year": 2010, "mun": "Coro"})
chk("recalcula la categoría", tm.player_by_id(state, 1)["cat"] == tm.categoria_por_nacimiento(2010),
    tm.player_by_id(state, 1)["cat"])
chk("el municipio también cambia", tm.player_by_id(state, 1)["mun"] == "Coro")
tm.update_player(state, 1, {"birth_year": "", "cat": "Senior"})
chk("borrar el año conserva la categoría enviada", tm.player_by_id(state, 1)["cat"] == "Senior")
tm.update_player(state, 1, {"birth_year": 2012, "cat": "Senior"})
chk("si hay año, manda la categoría calculada (no la del formulario)",
    tm.player_by_id(state, 1)["cat"] == "Sub-14", tm.player_by_id(state, 1)["cat"])
try:
    tm.update_player(state, 1, {"birth_year": 1800})
    chk("rechaza un año imposible", False)
except tm.TournamentError:
    chk("rechaza un año imposible", True)

print("== 4. Cambio de año sin editar ==")
for pid, nacido in [(1, 2012), (4, 2012)]:
    if pid > len(state["players"]):
        tm.create_player(state, "Dani", birth_year=nacido)
tm.update_player(state, 1, {"birth_year": 2012})
# Dos jugadores con partidas para que salgan en el ranking público.
for pid, nacido in [(1, 2012), (2, 2012)]:
    tm.update_player(state, pid, {"birth_year": nacido})
for j1, j2, r in [(1, 2, 1.0), (2, 1, 0.0)]:
    tm.create_match(state, j1, j2, "Rapid", [r], "2026-03-01 10:00:00")
tm.sync_categories(state, 2026)
chk("Sub-14 en 2026", all(p["cat"] == "Sub-14" for p in state["players"] if p.get("birth_year") == 2012),
    [(p["name"], p["cat"]) for p in state["players"] if p.get("birth_year") == 2012])
cambios = tm.sync_categories(state, 2027)
chk("al llegar 2027 hay cambios", cambios is True, cambios)
chk("Sub-16 en 2027 (15 años)", all(p["cat"] == "Sub-16" for p in state["players"] if p.get("birth_year") == 2012),
    [(p["name"], p["cat"]) for p in state["players"] if p.get("birth_year") == 2012])
chk("una segunda llamada no cambia nada", tm.sync_categories(state, 2027) is False)
chk("el jugador sin año no se toca", tm.player_by_id(state, 3)["cat"] == "-",
    tm.player_by_id(state, 3)["cat"])
anio_real = tm._anio_actual
tm._anio_actual = lambda: 2027  # simulamos estar ya en 2027
try:
    payload = lv.build_live(state)
    cats = [row.get("cat") for row in payload["ranking"]["Rapid"]]
    chk("el JSON público lleva la categoría recalculada", all(c == "Sub-16" for c in cats), cats)

    print("== 5. Convive con 'hidden' ==")
    tm.update_player(state, 1, {"hidden": True})
    oculto = lv.build_live(state)
    chk("sigue oculto del ranking", "Ana" not in [r["n"] for r in oculto["ranking"]["Rapid"]],
        [r["n"] for r in oculto["ranking"]["Rapid"]])
    chk("el otro mantiene su categoría",
        [r["cat"] for r in oculto["ranking"]["Rapid"]] == ["Sub-16"],
        [r["cat"] for r in oculto["ranking"]["Rapid"]])
finally:
    tm._anio_actual = anio_real

print("RESULTADO:", "TODO OK" if ok else "HAY FALLOS")
sys.exit(0 if ok else 1)
