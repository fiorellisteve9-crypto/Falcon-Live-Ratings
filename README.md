# Falcón Live Ratings

Ranking y gestión de torneos de ajedrez del club Falcón.

- Web pública: https://falcon-live-ratings.vercel.app/
- Repo: https://github.com/fiorellisteve9-crypto/Falcon-Live-Ratings

## Arquitectura

```
Admin (móvil)  →  admin.html  →  POST /api (token)  →  Vercel Python
                                                          │
                                                          ├─ motor FIDE Dutch + Glicko-2
                                                          └─ Supabase (Postgres)
Público        →  index.html  →  GET /api?action=live  ←──┘
```

- `index.html`: web pública existente (Falcón Live Ratings). Lee el snapshot
  público desde `/api`.
- `admin.html`: panel de administración (en construcción).
- `api/index.py`: función Python de Vercel. Reutiliza el motor de torneos
  (emparejamiento FIDE Dutch, Glicko-2 y desempates).
- Supabase: estado de jugadores, torneos, rondas y partidas. La clave
  `service_role` vive solo en las variables de entorno de Vercel.

## Estado

- [x] Repo y deploy en Vercel existentes.
- [x] Deploy key de escritura para automatizar commits.
- [x] API Python en producción (`ping` y `dbcheck`).
- [x] Esquema Supabase creado y conectado.
- [x] Motor extraído (`engine/core.py`) y estado JSON (`engine/state.py`).
- [x] Generador del payload público (`engine/live.py`).
- [x] API de administración: setup, login con PIN, sesiones, jugadores,
  torneos, rondas, resultados y cierre.
- [ ] Importar el estado migrado de los 7 torneos (desde el panel).
- [ ] Panel `admin.html`.
- [ ] `index.html` leyendo `/api` en lugar de Firebase.

## Motor y migración

- `engine/core.py`: FIDE Dutch, Glicko-2, Round Robin y desempates. Sin
  dependencias del CLI ni de SQLite.
- `engine/state.py`: estado del club en JSON y operaciones sobre él.
- `engine/live.py`: construye exactamente el JSON público que ya consume la web.
- `scripts/migrate_sqlite_to_state.py`: convierte `gestion_glicko2.db` en el
  estado JSON que se importará una sola vez en Supabase.

Validación hecha contra la base real de julio 2026:

- Glicko-2, emparejamientos y desempates idénticos al motor original.
- Los 7 torneos: variaciones de rating idénticas.
- El JSON público generado desde el estado es idéntico al publicado en Firebase.

## Puesta en marcha

1. Crear un proyecto nuevo en Supabase (separado de Chess Tasks).
2. Supabase → **SQL Editor** → pegar `supabase.sql` → **Run**.
3. Vercel → **Settings → Environment Variables**:
   - `SUPABASE_URL` = `https://xxxx.supabase.co`
   - `SUPABASE_KEY` = clave **service_role** (nunca la `anon`)
   - `SETUP_TOKEN` = cadena larga temporal para el primer arranque
4. Redeploy del proyecto para que las variables estén disponibles.
5. En el panel de administración, usar `SETUP_TOKEN` + PIN para crear el
   administrador. Después se puede borrar `SETUP_TOKEN` de Vercel.

## Variables de entorno (Vercel)

- `SUPABASE_URL`
- `SUPABASE_KEY` (clave `service_role`, nunca la `anon`)
- `SETUP_TOKEN` (solo para el primer arranque; se puede borrar después)

## Desarrollo

Este repositorio se edita desde Termux (o GitHub) y se publica solo con
`git push`. Vercel despliega `main` en producción y cada rama en un preview.
No se ejecuta nada en Termux para gestionar torneos: eso se hace desde
`admin.html` en el navegador.
