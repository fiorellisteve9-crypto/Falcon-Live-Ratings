"""Ejecuta toda la batería de pruebas del proyecto.

Uso:
    python3 tests/run_all.py            # motor + API (rápido)
    python3 tests/run_all.py --ui       # además las pruebas de interfaz (Chromium)
    python3 tests/run_all.py --grupo engine

Cada prueba imprime su propio checklist. Al final se resume cuántas pasan.
Los archivos temporales (capturas, JSON) van a $FALCON_TMP (por defecto
/tmp/falcon-tests).
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
RESULT_DIR = os.environ.get('FALCON_TMP', '/tmp/falcon-tests')
os.makedirs(RESULT_DIR, exist_ok=True)

GRUPOS = {
    'engine': [
        ('motor · corregir/eliminar match', 'engine/test_match_update.py'),
        ('motor · desempates (casos de mano)', 'engine/unit_tiebreaks.py'),
        ('motor · simulacro suisse 7 rondas', 'engine/sim_tiebreaks.py'),
        ('motor · simulacro Round Robin 1V y 2V', 'engine/sim_rr.py'),
        ('motor · criterios por tipo de torneo', 'engine/test_mejoras_desempates.py'),
    ],
    'api': [
        ('api · ediciones y fotos', 'api/test_api_edicion.py'),
        ('api · subida de fotos', 'api/test_photo_api.py'),
        ('api · pre-registro de torneos', 'api/test_drafts.py'),
    ],
    'ui': [
        ('ui · auditoría visual del panel', 'ui/audit_visual_admin.py'),
        ('ui · jugadores (orden, csv, ficha)', 'ui/test_club_ui.py'),
        ('ui · guía del torneo', 'ui/test_guia_ui.py'),
        ('ui · ficha del jugador', 'ui/test_ficha_ui.py'),
        ('ui · desempates en la web pública', 'ui/test_publico_desempates.py'),
        ('ui · pwa e instalación', 'ui/test_pwa_cdp.py'),
        ('ui · ritmo en matches jugados', 'ui/test_matches_ritmo.py'),
        ('ui · web pública', 'ui/test_publico_cdp.py'),
        ('ui · pre-registro (interfaz)', 'ui/test_drafts_ui.py'),
        ('ui · subida de fotos (interfaz)', 'ui/test_photo_ui.py'),
        ('ui · criterios en panel e impresión', 'ui/test_mejoras_ui.py'),
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ui', action='store_true', help='incluir las pruebas de interfaz')
    ap.add_argument('--grupo', choices=list(GRUPOS), help='ejecutar solo un grupo')
    args = ap.parse_args()

    grupos = ['engine', 'api'] + (['ui'] if args.ui else [])
    if args.grupo:
        grupos = [args.grupo]

    total = ok = fail = 0
    fallos = []
    for grupo in grupos:
        print(f"\n{'=' * 64}\n== {grupo.upper()} ==\n{'=' * 64}")
        for nombre, script in GRUPOS[grupo]:
            path = os.path.join(HERE, script)
            total += 1
            inicio = time.time()
            proc = subprocess.run([sys.executable, path], cwd=ROOT,
                                  capture_output=True, text=True, timeout=600)
            salida = (proc.stdout or '') + (proc.stderr or '')
            resumen = [l for l in salida.splitlines() if 'RESULTADO' in l]
            dur = time.time() - inicio
            if proc.returncode == 0:
                ok += 1
                print(f"  OK   {nombre} ({dur:.0f}s) {resumen[-1] if resumen else ''}")
            else:
                fail += 1
                fallos.append((nombre, salida))
                print(f"  FALLA {nombre} ({dur:.0f}s)")
                for l in salida.splitlines()[-6:]:
                    print('       ', l)

    print(f"\n{'=' * 64}\nRESUMEN: {ok}/{total} pruebas OK" + (f" · {fail} con fallos" if fail else ""))
    if fallos:
        print("\nPruebas con fallos:")
        for nombre, _ in fallos:
            print('  -', nombre)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
