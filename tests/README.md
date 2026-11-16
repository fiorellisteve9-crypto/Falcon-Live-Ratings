# Pruebas del proyecto

Todo lo que se ha construido (motor de desempates, fotos, PWA, pre-registro de
torneos, CSV, ficha de jugador, rediseño del panel) tiene su prueba aquí, para
que nada se pierda en una limpieza y se pueda volver a ejecutar tras cualquier
cambio.

## Cómo ejecutarlas

```bash
# motor + API (rápido, sin navegador)
python3 tests/run_all.py

# todo, incluidas las pruebas de interfaz (necesita Chromium)
python3 tests/run_all.py --ui

# solo un grupo
python3 tests/run_all.py --grupo engine

# el ensayo completo de torneo (tarda ~3-4 minutos: juega 3 torneos)
python3 tests/run_all.py --grupo ensayo
```

Variables opcionales:

| Variable | Para qué | Por defecto |
|---|---|---|
| `FALCON_SEED` | estado inicial de los tournaments simulados | `/sdcard/Download/falcon_seed_state.json` |
| `FALCON_TMP` | carpeta de capturas y JSON generados | `/tmp/falcon-tests` |

## Qué cubre cada grupo

### `tests/engine` — el motor (sin navegador)
| Prueba | Qué comprueba |
|---|---|
| `test_match_update.py` | Corregir y eliminar matches recalcula los ratings y los matches posteriores; el match reconstruye el detalle cuando no lo tiene; `create_match` no ha cambiado de comportamiento. |
| `unit_tiebreaks.py` | Casos de mano de cada desempate (BH, BH1, SB, Koya, AROC1, TPR, encuentro directo, victorias) con números conocidos a mano. |
| `sim_tiebreaks.py` | Torneo suicides simulado de 7 rondas con 15 jugadores: los 9 valores se comparan contra un recálculo independiente y se comprueba el orden. |
| `sim_rr.py` | Lo mismo para Round Robin de 1 vuelta (Rapid y Blitz) y de 2 vueltas (Rapid y Blitz), con descansos. |
| `test_mejoras_desempates.py` | Los criterios que aplican a cada tipo de torneo y el BH1 con un solo rival. |

### `tests/api` — la API (sin navegador)
| Prueba | Qué comprueba |
|---|---|
| `test_api_edicion.py` | Editar/eliminar jugadores y matches, corregir el rating/RD, el dashboard con partidas por jugador. |
| `test_photo_api.py` | Subida de fotos a Supabase Storage: valida formato y tamaño, guarda la URL, borra la anterior y quita la foto. |
| `test_drafts.py` | Pre-registro de torneos: crear, añadir y quitar inscriptos, activar (crea los jugadores nuevos) y el desempate por formato. |

### `tests/ui` — el panel y la web (Chromium headless, móvil 390 px)
| Prueba | Qué comprueba |
|---|---|
| `audit_visual_admin.py` | Contraste, objetivos táctiles, pestañas, tablas, modal (bottom-sheet, foco, Escape), estados vacíos y toasts. |
| `test_club_ui.py` | Ordenar la tabla de jugadores, exportar los tres CSV y abrir la ficha. |
| `test_guia_ui.py` | La guía del torneo: plegada, se abre, contiene los puntos clave y el enlace de Ajustes funciona. |
| `test_ficha_ui.py` | La ficha del jugador en móvil: avatar circular que recorta la foto, hoja que cabe en la pantalla, sin scroll horizontal. |
| `test_publico_desempates.py` | La web pública muestra los desempates de cada torneo y el atajo `?tab=ranking` funciona. |
| `test_pwa_cdp.py` | Manifest, iconos, service worker, precache, atajos y el funcionamiento sin conexión. |
| `test_matches_ritmo.py` | El perfil público indica el ritmo de cada match jugado. |
| `test_publico_cdp.py` | La web pública carga, pinta el ranking y no da errores. |
| `test_drafts_ui.py` | El pre-registro desde la interfaz. |
| `test_photo_ui.py` | Subir una foto desde el móvil (recorte a 512 px) y quitarla. |
| `test_mejoras_ui.py` | La tabla de desempates y la hoja impresa muestran solo los criterios de cada torneo. |

### `tests/ensayo_torneo.py` — el ensayo general de un torneo (Chromium)
No es una prueba de un detalle: es un **torneo completo de punta a punta**, pulsando
en la interfaz del panel como si fuera el día del torneo. Se puede lanzar para un
formato o para los tres:

```bash
python3 tests/ensayo_torneo.py --tipo rr1v --jugadores 8 --ritmo Rapid
python3 tests/ensayo_torneo.py --todos
```

Por cada formato comprueba: crear el torneo (resumen en vivo, participantes, rondas
y formato correctos), emparejar y capturar **todas** las rondas, el aviso «Faltan N
resultados», cerrar el torneo (los ratings cambian), el acta impresa, la ficha del
jugador, la tarjeta de imagen y la web pública (torneo terminado, desempates y
ranking).

Los **desempates no están escritos a mano en la prueba**: se leen del motor
(`engine/core.py`), que es la fuente de verdad, y se comprueba que el acta y la web
pública muestran exactamente esos.

| Formato | Escenario | Criterios que se comprueban |
|---|---|---|
| Suizo | 9 jugadores, 7 rondas manuales, Blitz (impar → descansos) | Pts · BH1 · BH · AROC1 · DE |
| Round Robin 1 vuelta | 8 jugadores, 7 rondas, Rapid | Pts · DE · SB · W · Koya |
| Round Robin 2 vueltas | 6 jugadores, 10 rondas, Blitz | Pts · DE · W · SB |

Resultado actual: **69/69 pasos correctos** en los tres formatos.

## Nota sobre `tournaments.bak.py`
La prueba que compara el motor actual con el motor anterior solo se ejecuta si
existe una copia del motor viejo en la raíz del repo. Si no está, se omite.
