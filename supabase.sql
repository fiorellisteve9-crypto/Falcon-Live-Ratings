-- ================================================================
-- FALCÓN LIVE RATINGS · Supabase
-- ---------------------------------------------------------------
-- Pegar TODO este bloque en: Supabase > SQL Editor > New query > Run
--
-- La API de Vercel usa la clave service_role. El navegador nunca
-- habla directamente con estas tablas: toda lectura/escritura pasa
-- por /api. Por eso no hay políticas públicas de RLS.
-- ================================================================

-- 1) Estado completo del club + snapshot público.
--    Una sola fila (id = 'main').
--    state: jugadores, torneos, rondas, partidas, matches y ratings.
--    live:  el JSON público que consume index.html.
--    version: bloqueo optimista para que dos pestañas no se pisen.
create table if not exists public.falcon_state (
  id          text primary key default 'main',
  state       jsonb not null default '{}'::jsonb,
  live        jsonb not null default '{}'::jsonb,
  version     integer not null default 1,
  updated_at  timestamptz not null default now()
);

-- 2) Credenciales del administrador (un solo registro).
--    El PIN nunca se guarda en claro: solo hash + sal.
create table if not exists public.admin (
  id          text primary key default 'main',
  name        text not null default 'Administrador',
  pin_hash    text not null,
  pin_salt    text not null,
  updated_at  timestamptz not null default now()
);

-- 3) Sesiones del panel de administración.
create table if not exists public.sessions (
  token       text primary key,
  created_at  timestamptz not null default now(),
  last_seen   timestamptz not null default now()
);
create index if not exists sessions_last_seen_idx on public.sessions (last_seen desc);

-- 4) Intentos de entrada, para bloquear fuerza bruta.
create table if not exists public.logins (
  id          bigserial primary key,
  ok          boolean not null,
  at          timestamptz not null default now()
);
create index if not exists logins_at_idx on public.logins (at desc);

-- Fila inicial del estado (vacía; se rellena al importar la migración
-- de los 7 torneos o al crear el primer torneo desde el panel).
insert into public.falcon_state (id, state, live, version)
values ('main', '{}'::jsonb, '{}'::jsonb, 1)
on conflict (id) do nothing;

-- RLS: activado y SIN políticas. Solo la clave service_role
-- (que se salta RLS) puede tocar estas tablas. La anon no ve nada.
alter table public.falcon_state enable row level security;
alter table public.admin       enable row level security;
alter table public.sessions    enable row level security;
alter table public.logins      enable row level security;

revoke all on public.falcon_state from anon, authenticated;
revoke all on public.admin       from anon, authenticated;
revoke all on public.sessions    from anon, authenticated;
revoke all on public.logins      from anon, authenticated;

-- Permisos explícitos para la API.
grant all on public.falcon_state to service_role;
grant all on public.admin       to service_role;
grant all on public.sessions    to service_role;
grant all on public.logins      to service_role;
grant usage, select on sequence public.logins_id_seq to service_role;

-- Verificación: debe devolver una fila con version = 1.
-- select id, version, updated_at,
--        jsonb_typeof(state) as state,
--        jsonb_typeof(live)  as live
-- from public.falcon_state;
