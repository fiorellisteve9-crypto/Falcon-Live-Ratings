"""Motor puro de torneos: FIDE Dutch, Glicko-2 y desempates.

Extraído de SwissManager Engine v5.2 (swissisZai.py), sin Rich ni SQLite.
No conoce la base de datos ni la interfaz: recibe y devuelve diccionarios.
"""

import math
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

try:
    from caissify_pairings import generate_pairings, MissingFloatHistoryWarning
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "caissify-pairings es obligatorio. Instálalo con: pip install caissify-pairings"
    ) from exc

warnings.simplefilter("default", MissingFloatHistoryWarning)


# ============================================================
# CONFIGURACIÓN GLOBAL
# ============================================================

DEFAULT_RATING = 1500.0
DEFAULT_RD = 500.0
DEFAULT_SIGMA = 0.09
DEFAULT_TAU = 0.75
MULTIPLIER = 173.7178
CONVERGENCE_TOLERANCE = 0.000001
ITERATION_MAX = 1000
DAYS_PER_MILLI = 1.0 / (1000 * 60 * 60 * 24)
DEFAULT_RATING_PERIODS_PER_DAY = 0.21436
MIN_RATING = 600.0
# MAX_RATING alineado con liglicko2 (Lichess): 4000.
MAX_RATING = 4000.0
MIN_RD = 45.0
MAX_RD = 500.0
MIN_VOLATILITY = 0.01
MAX_VOLATILITY = 0.1
# Cambio máximo de rating permitido por una sola partida (anti-saltos patológicos).
# Alineado con liglicko2: ±700 puntos por partida.
MAX_RATING_DELTA = 700.0
# Regulator factor anti-deflación (Lichess-style). Multiplica las GANANCIAS de
# rating en 1.02 cuando el jugador está por debajo de (DEFAULT_RATING + MAX_RD),
# i.e., rating < 2000. Esto contrarresta la deriva natural hacia abajo del
# sistema cuando los jugadores mejoran más rápido de lo que el rating refleja.
REGULATOR_FACTOR = 1.02


class TipoTorneo(Enum):
    SUIZO = 1
    ROUND_ROBIN_UNA_VUELTA = 2
    ROUND_ROBIN_DOS_VUELTAS = 3

    @classmethod
    def desde_valor(cls, valor):
        for miembro in cls:
            if miembro.value == valor:
                return miembro
        return cls.SUIZO

    @property
    def nombre_corto(self):
        return {
            1: "Suizo",
            2: "RR 1V",
            3: "RR 2V",
        }.get(self.value, "???")


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class FilaTablaPosiciones:
    """Representa una fila de la tabla de posiciones de un torneo."""
    nombre: str
    puntos: float
    direct_encounter: float
    buchholz_cut1: float
    buchholz_total: float
    sonneborn_berger: float
    victorias: int
    rating: float
    jugador_id: int
    tpr: int
    aroc1: float
    koya: float


# ============================================================

def convert_rating_to_glicko2_scale(rating):
    return (rating - DEFAULT_RATING) / MULTIPLIER


def convert_rating_to_original_scale(rating):
    return (rating * MULTIPLIER) + DEFAULT_RATING


def convert_rd_to_glicko2_scale(rd):
    return rd / MULTIPLIER


def convert_rd_to_original_scale(rd):
    return rd * MULTIPLIER


# ============================================================
# UTILIDADES DE TIEMPO
# ============================================================

def parse_datetime(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s), fmt)
        except ValueError:
            pass
    return None


def elapsed_rating_periods(last_date, current_date, rating_periods_per_day=DEFAULT_RATING_PERIODS_PER_DAY):
    d1 = parse_datetime(last_date)
    d2 = parse_datetime(current_date)
    if not d1 or not d2:
        return 0.0
    millis = max(0.0, (d2 - d1).total_seconds() * 1000.0)
    rating_periods_per_milli = rating_periods_per_day * DAYS_PER_MILLI
    return millis * rating_periods_per_milli


# ============================================================
# FUNCIONES AUXILIARES GLICKO-2
# ============================================================

def g(deviation):
    return 1.0 / math.sqrt(1.0 + (3.0 * deviation * deviation / (math.pi * math.pi)))


def E(player_rating, opponent_rating, opponent_deviation):
    return 1.0 / (1.0 + math.exp(-1.0 * g(opponent_deviation) * (player_rating - opponent_rating)))


def calculate_new_rd(phi, sigma, elapsed_rating_periods):
    return math.sqrt((phi * phi) + elapsed_rating_periods * (sigma * sigma))


def _f(x, delta, phi, v, a, tau):
    return (
        math.exp(x) * (delta * delta - phi * phi - v - math.exp(x))
        / (2.0 * ((phi * phi + v + math.exp(x)) ** 2))
    ) - ((x - a) / (tau * tau))


def _v(player_mu, results):
    val = 0.0
    for opp_mu, opp_phi, score in results:
        e = E(player_mu, opp_mu, opp_phi)
        val += (g(opp_phi) ** 2) * e * (1.0 - e)
    return 1.0 / val


def _outcome_based_rating(player_mu, results):
    total = 0.0
    for opp_mu, opp_phi, score in results:
        total += g(opp_phi) * (score - E(player_mu, opp_mu, opp_phi))
    return total


def _delta(player_mu, results):
    v = _v(player_mu, results)
    return v * _outcome_based_rating(player_mu, results)


def _cap_glicko(rating, rd, sigma):
    # Clamps alineados con liglicko2 (Lichess-flavored Glicko-2):
    #   rating      ∈ [MIN_RATING, MAX_RATING]   (600, 4000)
    #   rd          ∈ [MIN_RD, MAX_RD]           (45, 500)
    #   sigma       ∈ [MIN_VOLATILITY, MAX_VOLATILITY]  (0.01, 0.1)
    rating = min(MAX_RATING, max(MIN_RATING, rating))
    rd = min(MAX_RD, max(MIN_RD, rd))
    sigma = min(MAX_VOLATILITY, max(MIN_VOLATILITY, sigma))
    return rating, rd, sigma


def _regulate_rating(rating_old, rating_new):
    """Aplica el regulator factor anti-deflación de Lichess.

    Si el jugador está por debajo de DEFAULT_RATING + MAX_RD (= 2000) y la
    partida le dio una GANANCIA, se multiplica la ganancia por REGULATOR_FACTOR
    (1.02). Después se clamp el delta absoluto a ±MAX_RATING_DELTA (700).

    Esto evita la deriva deflacionaria natural del sistema Glicko-2 cuando
    los jugadores mejoran más rápido de lo que el rating refleja, y a la vez
    limita saltos patológicos (anti-sandbagging/anti-blowup).
    """
    delta = rating_new - rating_old
    if delta > 0.0 and rating_old < (DEFAULT_RATING + MAX_RD):
        delta = delta * REGULATOR_FACTOR
    # Clamp del delta a ±MAX_RATING_DELTA
    if delta > MAX_RATING_DELTA:
        delta = MAX_RATING_DELTA
    elif delta < -MAX_RATING_DELTA:
        delta = -MAX_RATING_DELTA
    return rating_old + delta


# ============================================================
# ACTUALIZACIÓN GLICKO-2 PRINCIPAL
# ============================================================

def glicko2_update(rating, rd, sigma, results, elapsed_rating_periods=0.0, tau=DEFAULT_TAU):
    player_mu = convert_rating_to_glicko2_scale(rating)
    phi = convert_rd_to_glicko2_scale(rd)

    if not results:
        new_phi = calculate_new_rd(phi, sigma, elapsed_rating_periods)
        return _cap_glicko(rating, convert_rd_to_original_scale(new_phi), sigma)

    converted_results = []
    for opp_rating, opp_rd, score in results:
        opp_mu = convert_rating_to_glicko2_scale(opp_rating)
        opp_phi = convert_rd_to_glicko2_scale(opp_rd)
        converted_results.append((opp_mu, opp_phi, score))

    a = math.log(sigma * sigma)
    delta = _delta(player_mu, converted_results)
    v = _v(player_mu, converted_results)

    A = a
    if (delta * delta) > (phi * phi + v):
        B = math.log((delta * delta) - (phi * phi) - v)
    else:
        k = 1
        B = a - (k * abs(tau))
        while _f(B, delta, phi, v, a, tau) < 0:
            k += 1
            B = a - (k * abs(tau))

    fA = _f(A, delta, phi, v, a, tau)
    fB = _f(B, delta, phi, v, a, tau)
    iterations = 0

    while abs(B - A) > CONVERGENCE_TOLERANCE and iterations < ITERATION_MAX:
        iterations += 1
        C = A + (((A - B) * fA) / (fB - fA))
        fC = _f(C, delta, phi, v, a, tau)
        if fC * fB <= 0:
            A = B
            fA = fB
            B = C
            fB = fC
        else:
            fA = fA / 2.0
            B = C
            fB = fC

    if iterations == ITERATION_MAX:
        try:
            get_logger().warning(
                "Glicko-2 no convergió (rating=%.2f, rd=%.2f, results=%s). "
                "Manteniendo valores originales.", rating, rd, results
            )
        except Exception:
            pass
        return _cap_glicko(rating, rd, sigma)

    new_sigma = math.exp(A / 2.0)
    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt((1.0 / (phi_star * phi_star)) + (1.0 / v))
    new_mu = player_mu + ((new_phi * new_phi) * _outcome_based_rating(player_mu, converted_results))

    # Convertir de vuelta a escala original
    new_rating_raw = convert_rating_to_original_scale(new_mu)
    new_rd_raw = convert_rd_to_original_scale(new_phi)

    # Cambio 2 (Lichess-style): aplicar regulator factor (×1.02 en ganancias
    # cuando rating < DEFAULT_RATING + MAX_RD = 2000) y clamp ±700 por partida.
    new_rating = _regulate_rating(rating, new_rating_raw)

    return _cap_glicko(
        new_rating,
        new_rd_raw,
        new_sigma,
    )


def glicko2_match_update_pair(r1, rd1, s1, r2, rd2, s2, score1, elapsed1=0.0, elapsed2=0.0):
    base_rd1 = convert_rd_to_original_scale(calculate_new_rd(convert_rd_to_glicko2_scale(rd1), s1, elapsed1))
    base_rd2 = convert_rd_to_original_scale(calculate_new_rd(convert_rd_to_glicko2_scale(rd2), s2, elapsed2))

    new1 = glicko2_update(r1, base_rd1, s1, [(r2, base_rd2, score1)], elapsed_rating_periods=0.0)
    new2 = glicko2_update(r2, base_rd2, s2, [(r1, base_rd1, 1.0 - score1)], elapsed_rating_periods=0.0)
    return new1, new2


def _round_count_from_historial(datos):
    return len(datos.get("historial", []))


def _round_count_suizo(jugadores):
    if not jugadores:
        return 0
    return max(_round_count_from_historial(d) for d in jugadores.values())


def _build_previous_pairings(jugadores):
    pairings = set()
    for nombre, datos in jugadores.items():
        my_id = datos["id"]
        for rival in datos.get("historial", []):
            if rival == "BYE" or rival not in jugadores:
                continue
            opp_id = jugadores[rival]["id"]
            pairings.add(tuple(sorted((my_id, opp_id))))
    return pairings


def _build_float_history_map(jugadores):
    rondas = _round_count_suizo(jugadores)
    float_hist = {nom: [] for nom in jugadores}
    score_before = {nom: 0.0 for nom in jugadores}
    processed = set()

    for r in range(rondas):
        handled = set()
        for nombre, datos in jugadores.items():
            if nombre in handled:
                continue
            if r >= len(datos.get("historial", [])):
                continue
            rival = datos["historial"][r]
            if rival == "BYE" or rival not in jugadores:
                float_hist[nombre].append("none")
                handled.add(nombre)
                continue
            key = (r, tuple(sorted((nombre, rival))))
            if key in processed:
                handled.add(nombre)
                continue
            processed.add(key)
            handled.add(nombre)
            handled.add(rival)
            sp = score_before[nombre]
            so = score_before[rival]
            if sp > so:
                float_hist[nombre].append("down")
                float_hist[rival].append("up")
            elif sp < so:
                float_hist[nombre].append("up")
                float_hist[rival].append("down")
            else:
                float_hist[nombre].append("none")
                float_hist[rival].append("none")

        for nombre, datos in jugadores.items():
            if r < len(datos.get("historial", [])):
                rival = datos["historial"][r]
                if rival == "BYE":
                    score_before[nombre] += 1.0
                elif rival in jugadores:
                    resultados_rival = datos.get("enfrentamientos", {}).get(rival, [])
                    if isinstance(resultados_rival, (int, float)):
                        score_before[nombre] += resultados_rival
                    else:
                        score_before[nombre] += sum(resultados_rival)

    return float_hist


def _build_caissify_players(lista_viva, jugadores):
    float_hist_map = _build_float_history_map(jugadores)
    jugadores_caiss = []
    for idx, nombre in enumerate(
        sorted(lista_viva, key=lambda x: (-jugadores[x]["rating"], x)), 1
    ):
        datos = jugadores[nombre]
        color_hist = []
        for c in datos.get("colores", []):
            if c == "B":
                color_hist.append("white")
            elif c == "N":
                color_hist.append("black")
            else:
                color_hist.append("none")
        jugadores_caiss.append({
            "id": datos["id"],
            "name": nombre,
            "score": float(datos["puntos"]),
            "rating": int(round(datos["rating"])),
            "starting_number": idx,
            "color_hist": color_hist,
            "float_history": float_hist_map.get(nombre, []),
            "bye_count": datos.get("historial", []).count("BYE"),
            "forfeit_win_count": 0,
        })
    return jugadores_caiss


def emparejamiento_suizo(lista_viva, jugadores, console=None):
    if len(lista_viva) < 2:
        return [], None

    jugadores_caiss = _build_caissify_players(lista_viva, jugadores)
    previous_pairings = _build_previous_pairings(jugadores)
    ronda_actual = _round_count_suizo(jugadores) + 1
    total_rondas = max(ronda_actual, math.ceil(math.log2(max(2, len(jugadores)))))

    with warnings.catch_warnings():
        warnings.simplefilter("always", MissingFloatHistoryWarning)
        pairings = generate_pairings(
            system="dutch",
            players=jugadores_caiss,
            previous_pairings=previous_pairings,
            round_number=ronda_actual,
            total_rounds=total_rondas,
            accelerated=True,
            bye_value=1.0,
            max_byes_per_player=1,
        )

    id_to_nombre = {jugadores[n]["id"]: n for n in lista_viva}
    parejas = []
    bye = None
    usados = set()
    for item in pairings:
        white_id = item.get("white_id")
        black_id = item.get("black_id")
        if item.get("bye") or black_id is None:
            bye = id_to_nombre.get(white_id)
            if bye:
                usados.add(bye)
            continue
        blanco = id_to_nombre[white_id]
        negro = id_to_nombre[black_id]
        parejas.append((blanco, negro))
        usados.add(blanco)
        usados.add(negro)

    esperadas = len(lista_viva) // 2
    if len(parejas) != esperadas:
        raise RuntimeError(
            f"Emparejamiento inválido: se esperaban {esperadas} mesas y se "
            f"recibieron {len(parejas)}"
        )
    if len(usados) != len(lista_viva):
        faltantes = [n for n in lista_viva if n not in usados]
        raise RuntimeError(
            f"Emparejamiento incompleto: jugadores sin asignación {faltantes}"
        )
    return parejas, bye


# ============================================================
# ROUND ROBIN (Circle Method)
# ============================================================

def generar_round_robin(jugadores_lista, dos_vueltas=False):
    """Genera emparejamientos Round Robin usando Circle Method con balance de colores FIDE.

    El algoritmo asigna colores priorizando:
    1. Evitar rachas de 3+ colores iguales consecutivos
    2. Balancear blancas/negras (diferencia max 1)
    3. Alternar colores entre rondas
    """
    lista = list(jugadores_lista)
    n = len(lista)
    if n < 2:
        return []
    if n % 2 == 1:
        lista.append("BYE")
        n += 1

    # Generar pares sin colores usando Circle Method
    rotate = list(lista)
    rondas_pares = []
    for rnd_idx in range(n - 1):
        ronda = []
        for i in range(n // 2):
            j = n - 1 - i
            ronda.append((rotate[i], rotate[j]))
        rondas_pares.append(ronda)
        rotate = [rotate[0]] + [rotate[-1]] + rotate[1:-1]

    # Asignar colores con algoritmo de balance
    blancas_count = {p: 0 for p in lista if p != "BYE"}
    negras_count = {p: 0 for p in lista if p != "BYE"}
    last_color = {p: None for p in lista if p != "BYE"}
    streak = {p: 0 for p in lista if p != "BYE"}

    rondas = []
    for ronda_pares in rondas_pares:
        ronda = []
        for b, n_ in ronda_pares:
            if b == "BYE":
                ronda.append((n_, "BYE"))
                continue
            if n_ == "BYE":
                ronda.append((b, "BYE"))
                continue

            # Decidir colores basado en balance y racha
            diff_b = blancas_count[b] - negras_count[b]
            diff_n = blancas_count[n_] - negras_count[n_]
            b_should_white = diff_b <= diff_n

            # Priorizar romper rachas de 2+ colores iguales
            if streak[b] >= 2 and last_color[b] == "B":
                b_should_white = False
            elif streak[b] >= 2 and last_color[b] == "N":
                b_should_white = True
            elif streak[n_] >= 2 and last_color[n_] == "B":
                b_should_white = True
            elif streak[n_] >= 2 and last_color[n_] == "N":
                b_should_white = False

            if b_should_white:
                white, black = b, n_
            else:
                white, black = n_, b

            ronda.append((white, black))
            blancas_count[white] += 1
            negras_count[black] += 1
            if last_color[white] == "B":
                streak[white] += 1
            else:
                streak[white] = 1
            last_color[white] = "B"
            if last_color[black] == "N":
                streak[black] += 1
            else:
                streak[black] = 1
            last_color[black] = "N"
        rondas.append(ronda)

    if dos_vueltas:
        segunda = []
        for ronda in rondas:
            inv = []
            for b, n_ in ronda:
                inv.append((b, "BYE") if n_ == "BYE" else (n_, b))
            segunda.append(inv)
        rondas.extend(segunda)
    return rondas


def calcular_tpr(ratings_rivales, puntos):
    partidas = len(ratings_rivales)
    if partidas == 0:
        return 0
    r_a = sum(ratings_rivales) / partidas
    p = puntos / partidas
    if p >= 1.0:
        return int(max(ratings_rivales) + 400)
    if p <= 0.0:
        return int(min(ratings_rivales) - 400)
    d_p = (p - 0.5) * 800
    return int(r_a + d_p)


def calcular_buchholz_total(jugador, jugadores):
    rivales = set(op for op in jugadores[jugador]["historial"] if op in jugadores and op != "BYE")
    return sum(jugadores[op]["puntos"] for op in rivales)


def calcular_buchholz_cut1(jugador, jugadores):
    """Buchholz Cut 1: suma de los rivales descontando el más flojo.

    Si el jugador tiene menos de dos rivales reales no hay nada que
    descartar, así que el valor es 0 (regla estándar: con un solo rival se
    descarta y no queda nada por sumar).
    """
    rivales = set(op for op in jugadores[jugador]["historial"] if op in jugadores and op != "BYE")
    pts = sorted(jugadores[op]["puntos"] for op in rivales)
    return sum(pts[1:])


def calcular_sonneborn_berger(jugador, jugadores):
    sb = 0.0
    for rival, resultados in jugadores[jugador]["enfrentamientos"].items():
        if rival in jugadores:
            if isinstance(resultados, (int, float)):
                resultados = [resultados]
            for r in resultados:
                if r == 1.0:
                    sb += jugadores[rival]["puntos"]
                elif r == 0.5:
                    sb += jugadores[rival]["puntos"] * 0.5
    return sb


def calcular_direct_encounter(jugador, jugadores):
    datos = jugadores[jugador]
    mi_pts = datos["puntos"]
    de = 0.0
    for rival, resultados in datos["enfrentamientos"].items():
        if rival in jugadores and jugadores[rival]["puntos"] == mi_pts:
            if isinstance(resultados, (int, float)):
                de += resultados
            else:
                de += sum(resultados)
    return de


def calcular_victorias(jugador, jugadores):
    count = 0
    for resultados in jugadores[jugador]["enfrentamientos"].values():
        if isinstance(resultados, (int, float)):
            resultados = [resultados]
        count += sum(1 for r in resultados if r == 1.0)
    return count


def calcular_aroc1(jugador, jugadores):
    rivales = set(op for op in jugadores[jugador]["historial"] if op in jugadores and op != "BYE")
    if not rivales:
        return 0.0
    ratings = sorted(jugadores[op]["rating"] for op in rivales)
    ratings_cut = ratings[1:] if len(ratings) >= 2 else ratings
    return sum(ratings_cut) / len(ratings_cut) if ratings_cut else 0.0


def calcular_koya(jugador, jugadores):
    """
    Sistema Koya (FIDE).

    Suma de los puntos obtenidos por el jugador contra aquellos oponentes
    que hayan alcanzado AL MENOS el 50 % de la puntuacion maxima posible
    del torneo (>= umbral, no estrictamente mayor).

    Definicion oficial:
      - puntuacion_maxima = numero total de rondas del torneo
        (cada ronda otorga 1 punto por victoria, 0.5 por empate,
         0 por derrota; un bye tambien cuenta como 1 punto).
      - umbral = puntuacion_maxima / 2.
      - Solo se consideran partidas reales (se excluyen byes: no hay
        oponente real contra quien sumar puntos).
      - Se suman los puntos que el JUGADOR obtuvo contra esos oponentes
        (1.0 victoria, 0.5 tablas, 0.0 derrota).

    Implementacion:
      - puntuacion_maxima = max(len(historial)) entre todos los jugadores.
        El historial incluye los byes como 'BYE', por lo que su longitud
        coincide con el numero de rondas jugadas. Esto cubre todos los
        formatos: RR 1V, RR 2V y Suizo, con o sin byes.
      - El dict `enfrentamientos` ya excluye byes (ver cargar_estado_jugadores),
        asi que iterar sobre el es suficiente para considerar solo partidas reales.
      - Comparacion `>= umbral` (al menos el 50 %, no estrictamente mayor).
    """
    if not jugadores:
        return 0.0

    # puntuacion_maxima = numero total de rondas del torneo.
    # Cada jugador tiene len(historial) entradas (partidas + byes).
    # Si algun jugador se retira y tiene menos rondas jugadas, tomamos
    # el maximo entre todos para reflejar el numero real de rondas.
    puntuacion_maxima = max(
        (len(j.get("historial", [])) for j in jugadores.values()),
        default=0,
    )
    if puntuacion_maxima == 0:
        return 0.0
    umbral = puntuacion_maxima / 2.0

    koya = 0.0
    datos_jugador = jugadores[jugador]
    for rival, resultados in datos_jugador["enfrentamientos"].items():
        # Solo rivales validos que hayan alcanzado o superado el 50 %.
        # Los byes no aparecen en `enfrentamientos`, asi que ya estan excluidos.
        if rival not in jugadores:
            continue
        if jugadores[rival]["puntos"] < umbral:
            continue
        # Normalizar a lista para iterar
        if isinstance(resultados, (int, float)):
            resultados = [resultados]
        # Sumar los puntos que el JUGADOR obtuvo contra ese rival.
        # 1.0 victoria, 0.5 tablas, 0.0 derrota. Las tablas SI cuentan.
        koya += sum(resultados)
    return koya


def construir_fila_posiciones(nombre, datos_jugador, jugadores, n_jugadores):
    de = calcular_direct_encounter(nombre, jugadores)
    bt = calcular_buchholz_total(nombre, jugadores)
    bc1 = calcular_buchholz_cut1(nombre, jugadores)
    sb = calcular_sonneborn_berger(nombre, jugadores)
    vict = calcular_victorias(nombre, jugadores)
    aroc1 = calcular_aroc1(nombre, jugadores)
    koya = calcular_koya(nombre, jugadores)

    rivales = [op for op in datos_jugador["historial"] if op in jugadores and op != "BYE"]
    ratings_riv = [jugadores[op]["rating"] for op in rivales]
    byes = datos_jugador["historial"].count("BYE")
    pts_efectivos = max(0.0, datos_jugador["puntos"] - byes)
    tpr = calcular_tpr(ratings_riv, pts_efectivos)

    return FilaTablaPosiciones(
        nombre=nombre,
        puntos=datos_jugador["puntos"],
        direct_encounter=de,
        buchholz_cut1=bc1,
        buchholz_total=bt,
        sonneborn_berger=sb,
        victorias=vict,
        rating=datos_jugador["rating"],
        jugador_id=datos_jugador["id"],
        tpr=tpr,
        aroc1=aroc1,
        koya=koya,
    )


# ── Criterios de desempate por tipo de torneo ──────────────────────
# Fuente única de verdad: el orden de la clasificación y lo que se muestra
# en el panel / en la impresión salen de aquí.
CRITERIO_LABELS = {
    "puntos": "Pts",
    "buchholz_cut1": "BH1",
    "buchholz_total": "BH",
    "sonneborn_berger": "SB",
    "victorias": "W",
    "koya": "Koya",
    "aroc1": "AROC1",
    "direct_encounter": "DE",
}

CRITERIOS = {
    "suizo":     ["puntos", "buchholz_cut1", "buchholz_total", "aroc1", "direct_encounter"],
    "rr1v_rapid": ["puntos", "direct_encounter", "sonneborn_berger", "victorias", "koya"],
    "rr1v_bb":   ["puntos", "direct_encounter", "sonneborn_berger", "victorias"],
    "rr2v_rapid": ["puntos", "sonneborn_berger", "victorias", "direct_encounter"],
    "rr2v_bb":   ["puntos", "direct_encounter", "victorias", "sonneborn_berger"],
    "default":   ["puntos", "direct_encounter", "buchholz_cut1", "buchholz_total",
                  "sonneborn_berger", "victorias"],
}


def _tipo_criterios(tipo_torneo, ritmo):
    r = (ritmo or "").lower()
    nombre = getattr(tipo_torneo, "name", str(tipo_torneo))
    if nombre == "SUIZO" and r in ("rapid", "blitz", "bullet"):
        return "suizo"
    if nombre == "ROUND_ROBIN_UNA_VUELTA" and r == "rapid":
        return "rr1v_rapid"
    if nombre == "ROUND_ROBIN_UNA_VUELTA" and r in ("blitz", "bullet"):
        return "rr1v_bb"
    if nombre == "ROUND_ROBIN_DOS_VUELTAS" and r == "rapid":
        return "rr2v_rapid"
    if nombre == "ROUND_ROBIN_DOS_VUELTAS" and r in ("blitz", "bullet"):
        return "rr2v_bb"
    return "default"


def criterios_desempate(tipo_torneo, ritmo):
    """Criterios que aplican a ese torneo, en orden."""
    return list(CRITERIOS[_tipo_criterios(tipo_torneo, ritmo)])


def etiquetas_criterios(tipo_torneo, ritmo):
    """Criterios aplicables con su etiqueta, para el panel y la impresión."""
    return [
        {"key": key, "label": CRITERIO_LABELS.get(key, key)}
        for key in criterios_desempate(tipo_torneo, ritmo)
    ]


def ordenar_tabla_posiciones(filas, tipo_torneo, ritmo):
    """Ordena la clasificación aplicando los desempates según modalidad y ritmo."""
    criterios = criterios_desempate(tipo_torneo, ritmo)
    return sorted(filas, key=lambda f: tuple(float(getattr(f, k, 0) or 0) for k in criterios), reverse=True)


def calcular_categoria_ajedrez(anio_nacimiento, anio_actual=None):
    """Determina la categoría de ajedrez a partir del año de nacimiento.

    Sigue el esquema de categorías por edad usado habitualmente por FIDE y
    federaciones nacionales (Sub-8 .. Sub-20, Absoluta, Senior, Súper Senior).
    La categoría es "par" en el sentido de que depende sólo del año de
    nacimiento frente al año actual, no del mes de cumpleaños, para mantener
    estabilidad durante todo el calendario deportivo.

    Devuelve "-" si el dato no es válido o está vacío.
    """
    if anio_actual is None:
        anio_actual = datetime.now().year
    try:
        anio_nac = int(str(anio_nacimiento).strip())
    except (ValueError, TypeError):
        return "-"
    if anio_nac <= 1900 or anio_nac > anio_actual + 1:
        return "-"
    edad = anio_actual - anio_nac
    if edad < 0:
        return "-"
    if edad <= 8:
        return "Sub-8"
    if edad <= 10:
        return "Sub-10"
    if edad <= 12:
        return "Sub-12"
    if edad <= 14:
        return "Sub-14"
    if edad <= 16:
        return "Sub-16"
    if edad <= 18:
        return "Sub-18"
    if edad <= 20:
        return "Sub-20"
    if edad >= 65:
        return "Súper Senior"
    if edad >= 50:
        return "Senior"
    return "Absoluta"


def _normalizar_texto_opcional(valor, defecto="-"):
    """Normaliza un campo de texto opcional: vacío se convierte en el defecto."""
    if valor is None:
        return defecto
    v = str(valor).strip()
    return v if v else defecto

