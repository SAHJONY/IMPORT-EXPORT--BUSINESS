-- ============================================================
-- PAQUETES.SAHJONY.com — estado de seguridad en Supabase
-- Pegar UNA VEZ en el SQL Editor del proyecto Supabase del VPS
-- (Dashboard > SQL Editor > New query > pegar > Run).
-- Es idempotente: se puede correr más de una vez sin daño.
-- ============================================================

create table if not exists staff_users (
  id uuid primary key default gen_random_uuid(),
  username text unique not null,
  pw_hash text not null,
  created_at timestamptz not null default now()
);

create table if not exists staff_sessions (
  id uuid primary key default gen_random_uuid(),
  token_hash text unique not null,
  username text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked boolean not null default false
);
create index if not exists staff_sessions_token_idx on staff_sessions(token_hash);

create table if not exists login_attempts (
  id bigint generated always as identity primary key,
  key text not null,
  ts timestamptz not null default now()
);
create index if not exists login_attempts_key_ts_idx on login_attempts(key, ts);

create table if not exists scan_events (
  id bigint generated always as identity primary key,
  agency_id integer not null,
  ts timestamptz not null default now()
);
create index if not exists scan_events_agency_ts_idx on scan_events(agency_id, ts);

create table if not exists agency_resets (
  id uuid primary key default gen_random_uuid(),
  owner_email text not null,
  token_hash text unique not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  used boolean not null default false
);
create index if not exists agency_resets_token_idx on agency_resets(token_hash);

-- La service_role key ignora RLS; esto solo bloquea la anon key.
alter table staff_users enable row level security;
alter table staff_sessions enable row level security;
alter table login_attempts enable row level security;
alter table scan_events enable row level security;
alter table agency_resets enable row level security;
