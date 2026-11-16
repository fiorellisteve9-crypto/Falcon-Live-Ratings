"""Semilla de pruebas: usa la real si existe; si no, genera una sintética.

Las pruebas necesitan un estado de partida (jugadores, torneos y partidas). En el
teléfono se usa la copia real (`falcon_seed_state.json`), pero en CI o en un
ordenador nuevo no existe. En ese caso se genera una semilla sintética **con el
propio motor**, para que sea válida por construcción.

    python3 tests/lib/seed.py           # genera la semilla y dice dónde está
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
DEFAULT_SEED = '/sdcard/Download/falcon_seed_state.json'

NOMBRES = ["Jugador Prueba", "Ana Probeta", "Bruno Ensayo", "Carla Simulación",
           "Diego Verificación", "Elena Chequeo", "Félix Test", "Gloria Caso",
           "Hugo Batería", "Irene Traza", "Julián Ronda", "Karina Partido"]

def _png_512():
    """Un PNG 512x512 de un solo color, generado aquí (sin dependencias)."""
    import struct
    import zlib
    ancho = alto = 512
    fila = b"\x00" + bytes([46, 106, 158] * ancho)      # una fila RGB + filtro 0
    crudo = fila * alto
    def bloque(tipo, datos):
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xffffffff))
    png = (b"\x89PNG\r\n\x1a\n"
           + bloque(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
           + bloque(b"IDAT", zlib.compress(crudo, 9))
           + bloque(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# Foto de 512 px (el mismo tamaño que una foto subida desde el móvil).
FOTO_PNG = _png_512()


def generar_semilla(destino, jugadores=12, partidos=18):
    """Crea un estado de partida usando el motor (válido por construcción)."""
    sys.path.insert(0, ROOT)
    from engine import tournaments as tm

    state = {"schema": 1, "players": [], "tournaments": [], "matches": [], "next_ids": {}}
    for i, nombre in enumerate(NOMBRES[:jugadores]):
        tm.create_player(state, nombre, mun="Falcón", cat="Sub-14",
                         rhythm="Rapid", rating=1400 + i * 15, rd=200,
                         foto_url=(FOTO_PNG if i == 0 else None))

    # ── Unas partidas sueltas (fuera de torneo), repartidas entre los jugadores ──
    # La fecha es temprana a propósito: el motor no deja capturar un partido con
    # fecha anterior a la última actividad del jugador, y las pruebas usan
    # fechas de agosto.
    for i in range(partidos):
        j1 = (i % jugadores) + 1
        j2 = ((i * 3) % jugadores) + 1
        if j1 == j2:
            j2 = (j2 % jugadores) + 1
        resultados = [1, 0.5, 0][i % 3]
        tm.create_match(state, j1, j2, "Rapid" if i % 2 == 0 else "Blitz",
                        [resultados], "2026-01-15 10:00:00")

    # ── Un Suizo en curso (8 jugadores, 4 rondas) ──
    tm.create_tournament(state, "Torneo Semilla Suizo", 1, "Blitz", 4,
                         player_ids=[7, 8, 9, 10, 11, 12, 1, 2],
                         date_start="2026-02-01 10:00:00")
    # ── Un Round Robin de 1 vuelta terminado (6 jugadores) ──
    # Se crea después para que sea el último (es el que muestra la web pública).
    tm.create_tournament(state, "Torneo Semilla RR I", 2, "Rapid", 5,
                         player_ids=[1, 2, 3, 4, 5, 6],
                         date_start="2026-02-01 10:00:00")

    # ── Se juegan 3 rondas del Round Robin, para que tenga partidas y
    #    "rivales más frecuentes" en la ficha del jugador ──
    rr = state["tournaments"][-1]
    for ronda in range(1, 4):
        tm.pair_next_round(state, int(rr["id"]))
        juegos = [g for g in rr["games"] if int(g["round"]) == ronda and not g.get("bye")]
        resultados = []
        for g in juegos:
            # Resultado desde las blancas: gana el que tiene el id par.
            g["result"] = 1.0 if int(g["white_id"]) % 2 == 0 else 0.0
            resultados.append({"game_id": int(g["id"]), "result": g["result"]})
        if resultados:
            tm.save_results(state, int(rr["id"]), resultados)

    # Las rondas se jugaron "hoy"; se rebobinan a febrero para que la semilla
    # no dependa del día en que se genera (el motor no admite partidos con
    # fecha anterior a la última actividad del jugador).
    for t in state.get("tournaments", []):
        for g in t.get("games", []):
            g["date"] = "2026-02-01 10:00:00"
    tm._recompute_last_activity(state)

    state.pop("live", None)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    return destino


def seed_path():
    """Ruta del archivo de semilla: la real si existe, si no una sintética."""
    p = os.environ.get("FALCON_SEED", DEFAULT_SEED)
    if p and os.path.exists(p):
        return p
    os.makedirs(RESULT_DIR, exist_ok=True)
    destino = os.path.join(RESULT_DIR, "seed_sintetico.json")
    if not os.path.exists(destino):
        generar_semilla(destino)
    return destino


if __name__ == "__main__":
    ruta = seed_path()
    d = json.load(open(ruta, encoding="utf-8"))
    print("semilla:", ruta)
    print("  jugadores:", len(d.get("players", [])),
          "| torneos:", len(d.get("tournaments", [])),
          "| partidas:", len(d.get("matches", [])))
    for t in d.get("tournaments", []):
        print(f"    torneo {t['id']}: {t['name']} (tipo {t['type']}, {t['rhythm']}, "
              f"{len(t.get('games', []))} partidas)")
