create extension if not exists pgcrypto;

create table if not exists public.trade_cases (
  id uuid primary key default gen_random_uuid(),
  mode text not null check (mode in ('import','export')),
  origin_country text not null,
  destination_country text not null,
  product text not null,
  hs_code text,
  incoterm text not null default 'EXW',
  quantity numeric not null check (quantity > 0),
  unit_cost numeric not null check (unit_cost >= 0),
  target_sale_price_per_unit numeric,
  status text not null default 'draft',
  readiness_score integer not null default 0 check (readiness_score between 0 and 100),
  release_gate text not null default 'HOLD' check (release_gate in ('HOLD','REVIEW','READY')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.counterparties (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid references public.trade_cases(id) on delete cascade,
  kind text not null check (kind in ('supplier','buyer','broker','carrier','warehouse','bank','insurer')),
  legal_name text not null,
  country text,
  verification_status text not null default 'pending',
  sanctions_status text not null default 'pending',
  risk_score integer not null default 50 check (risk_score between 0 and 100),
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.shipments (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid not null references public.trade_cases(id) on delete cascade,
  carrier text,
  mode text,
  origin_location text,
  destination_location text,
  etd timestamptz,
  eta timestamptz,
  status text not null default 'planned',
  tracking_reference text,
  temperature_required boolean not null default false,
  telemetry jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.trade_documents (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid not null references public.trade_cases(id) on delete cascade,
  document_type text not null,
  storage_path text,
  status text not null default 'missing',
  checksum text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.compliance_checks (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid not null references public.trade_cases(id) on delete cascade,
  check_type text not null,
  status text not null check (status in ('pending','pass','review','blocked')),
  source text,
  evidence jsonb not null default '{}'::jsonb,
  checked_at timestamptz not null default now()
);

create table if not exists public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid references public.trade_cases(id) on delete cascade,
  agent_name text not null,
  objective text not null,
  status text not null default 'queued',
  confidence numeric check (confidence between 0 and 1),
  input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '[]'::jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.trade_decisions (
  id uuid primary key default gen_random_uuid(),
  trade_case_id uuid references public.trade_cases(id) on delete cascade,
  decision_type text not null,
  decision text not null,
  readiness_score integer not null check (readiness_score between 0 and 100),
  release_gate text not null check (release_gate in ('HOLD','REVIEW','READY')),
  rationale jsonb not null default '{}'::jsonb,
  next_actions jsonb not null default '[]'::jsonb,
  policy_version text not null default 'trade-os-v2',
  created_at timestamptz not null default now()
);

create table if not exists public.trade_events (
  id bigint generated always as identity primary key,
  trade_case_id uuid references public.trade_cases(id) on delete cascade,
  event_type text not null,
  severity text not null default 'info' check (severity in ('info','warning','critical')),
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_trade_cases_status on public.trade_cases(status, release_gate);
create index if not exists idx_counterparties_trade_case on public.counterparties(trade_case_id);
create index if not exists idx_shipments_trade_case on public.shipments(trade_case_id);
create index if not exists idx_agent_runs_trade_case on public.agent_runs(trade_case_id, created_at desc);
create index if not exists idx_trade_events_trade_case on public.trade_events(trade_case_id, created_at desc);

comment on table public.trade_decisions is 'Auditable, policy-gated decisions. AI recommendations never bypass mandatory compliance gates.';
