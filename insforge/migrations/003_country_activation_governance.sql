-- SAHJONY Global Trade
-- Migration 003: country and corridor activation governance.
--
-- IMPORTANT:
-- - Explicit migration artifact only; /activation/health does not execute this file.
-- - Apply to a Neon temporary branch first and verify before production promotion.
-- - New jurisdictions begin BLOCKED. LIVE/READY execution requires current evidence,
--   owner approval, and a separately approved LIVE corridor.

create table if not exists public.country_activation_profiles (
  id bigserial primary key,
  country_code text not null unique,
  country_name text not null,
  region text,
  operating_status text not null default 'BLOCKED' check (operating_status in ('READY','LIMITED','BLOCKED')),
  scenario_mode text not null default 'LIVE' check (scenario_mode in ('LIVE','HYPOTHETICAL')),
  live_execution_allowed boolean not null default true,
  scenario_label text,
  default_currency text,
  default_locale text,
  notes text,
  owner_approved boolean not null default false,
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.country_activation_profiles add column if not exists scenario_mode text not null default 'LIVE';
alter table public.country_activation_profiles add column if not exists live_execution_allowed boolean not null default true;
alter table public.country_activation_profiles add column if not exists scenario_label text;

create table if not exists public.country_activation_controls (
  id bigserial primary key,
  control_id text not null unique,
  country_code text not null references public.country_activation_profiles(country_code) on delete cascade,
  control_key text not null,
  control_label text not null,
  status text not null default 'BLOCKED' check (status in ('READY','LIMITED','BLOCKED','NOT_APPLICABLE')),
  evidence_summary text,
  evidence_source text,
  evidence_reference text,
  reviewed_by_role text,
  reviewed_by_id text,
  reviewed_at timestamptz,
  expires_at timestamptz,
  owner_waiver boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(country_code, control_key)
);

create table if not exists public.country_product_permissions (
  id bigserial primary key,
  permission_id text not null unique,
  country_code text not null references public.country_activation_profiles(country_code) on delete cascade,
  product_id text not null,
  import_status text not null default 'BLOCKED' check (import_status in ('READY','LIMITED','BLOCKED')),
  export_status text not null default 'BLOCKED' check (export_status in ('READY','LIMITED','BLOCKED')),
  restrictions text,
  permit_requirements text,
  labeling_requirements text,
  agency_requirements text,
  reviewed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(country_code, product_id)
);

create table if not exists public.trade_corridor_activations (
  id bigserial primary key,
  corridor_id text not null unique,
  origin_country_code text not null,
  destination_country_code text not null,
  status text not null default 'BLOCKED' check (status in ('READY','LIMITED','BLOCKED')),
  execution_mode text not null default 'LIVE' check (execution_mode in ('LIVE','SIMULATION')),
  allowed_incoterms jsonb not null default '[]'::jsonb,
  supported_currencies jsonb not null default '[]'::jsonb,
  carrier_coverage boolean not null default false,
  broker_coverage boolean not null default false,
  banking_coverage boolean not null default false,
  insurance_coverage boolean not null default false,
  tax_model_verified boolean not null default false,
  owner_approved boolean not null default false,
  approval_note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(origin_country_code, destination_country_code),
  check (origin_country_code <> destination_country_code),
  check (execution_mode <> 'LIVE' or status <> 'READY' or owner_approved = true)
);

alter table public.trade_corridor_activations add column if not exists execution_mode text not null default 'LIVE';

create table if not exists public.country_activation_audit (
  id bigserial primary key,
  event_id text not null unique,
  country_code text not null,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_country_activation_status on public.country_activation_profiles(operating_status, country_code);
create index if not exists idx_country_activation_scenario on public.country_activation_profiles(scenario_mode, live_execution_allowed);
create index if not exists idx_country_controls_country on public.country_activation_controls(country_code, control_key);
create index if not exists idx_country_controls_expiry on public.country_activation_controls(country_code, expires_at);
create index if not exists idx_corridor_activation_status on public.trade_corridor_activations(status, execution_mode, origin_country_code, destination_country_code);
create index if not exists idx_country_product_permission on public.country_product_permissions(country_code, product_id);
create index if not exists idx_country_activation_audit on public.country_activation_audit(country_code, created_at desc);

comment on table public.country_activation_profiles is 'Fail-closed jurisdiction operating state. HYPOTHETICAL jurisdictions are simulation-only and never authorize live execution.';
comment on table public.country_activation_controls is 'Sixteen mandatory evidence-backed jurisdiction controls. READY/LIMITED evidence is runtime-validated; LIVE NOT_APPLICABLE requires owner waiver.';
comment on table public.trade_corridor_activations is 'Origin-to-destination execution permission. LIVE/READY corridors require owner approval and runtime country/control validation.';
comment on table public.country_activation_audit is 'Append-oriented governance audit for jurisdiction and corridor decisions.';
