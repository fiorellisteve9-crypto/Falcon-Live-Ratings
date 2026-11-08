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
- [ ] API Python de prueba (`/api?action=ping`).
- [ ] Esquema Supabase y migración de los 7 torneos históricos.
- [ ] Motor extraído del CLI y adaptado a Supabase.
- [ ] Panel `admin.html`.
- [ ] `index.html` leyendo `/api` en lugar de Firebase.

## Puesta en marcha

1. Crear un proyecto nuevo en Supabase (separado de Chess Tasks).
2. Supabase → **SQL Editor** → pegar `supabase.sql` → **Run**.
3. Vercel → **Settings → Environment Variables**:
   - `SUPABASE_URL` = `https://xxxx.supabase.co`
   - `SUPABASE_KEY` = clave **service_role** (nunca la `anon`)
4. Redeploy del proyecto para que las variables estén disponibles.
5. Abrir el panel de administración y crear el PIN inicial (próximo paso).

## Variables de entorno (Vercel)

- `SUPABASE_URL`
- `SUPABASE_KEY` (clave `service_role`, nunca la `anon`)

## Desarrollo

Este repositorio se edita desde Termux (o GitHub) y se publica solo con
`git push`. Vercel despliega `main` en producción y cada rama en un preview.
No se ejecuta nada en Termux para gestionar torneos: eso se hace desde
`admin.html` en el navegador.
