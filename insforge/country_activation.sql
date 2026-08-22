-- SAHJONY Global Trade country/corridor activation governance
create table if not exists country_activation_profiles (
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

-- Forward-compatible migration for projects where the table already exists.
alter table country_activation_profiles add column if not exists scenario_mode text not null default 'LIVE';
alter table country_activation_profiles add column if not exists live_execution_allowed boolean not null default true;
alter table country_activation_profiles add column if not exists scenario_label text;

create table if not exists country_activation_controls (
  id bigserial primary key,
  control_id text not null unique,
  country_code text not null references country_activation_profiles(country_code) on delete cascade,
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

create table if not exists country_product_permissions (
  id bigserial primary key,
  permission_id text not null unique,
  country_code text not null references country_activation_profiles(country_code) on delete cascade,
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

create table if not exists trade_corridor_activations (
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
  unique(origin_country_code, destination_country_code)
);

alter table trade_corridor_activations add column if not exists execution_mode text not null default 'LIVE';

create table if not exists country_activation_audit (
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

create index if not exists idx_country_activation_status on country_activation_profiles(operating_status, country_code);
create index if not exists idx_country_activation_scenario on country_activation_profiles(scenario_mode, live_execution_allowed);
create index if not exists idx_country_controls_country on country_activation_controls(country_code, control_key);
create index if not exists idx_corridor_activation_status on trade_corridor_activations(status, origin_country_code, destination_country_code);
create index if not exists idx_country_product_permission on country_product_permissions(country_code, product_id);

-- Canonical fail-closed controls expected per country:
-- legal_entity_trading_eligibility
-- importer_exporter_registration
-- customs_broker_coverage
-- sanctions_export_controls
-- product_restrictions
-- tax_vat_gst
-- banking_settlement
-- currency_support
-- freight_carrier_coverage
-- cargo_liability_insurance
-- document_requirements
-- translation_language
-- local_contracts
-- warehouse_3pl
-- data_privacy
-- accounting_reconciliation
-- A country cannot be READY unless all mandatory controls are READY or formally NOT_APPLICABLE and owner-approved.
-- HYPOTHETICAL jurisdictions are simulation-only. live_execution_allowed=false is a hard boundary and must never be treated as a legal/compliance waiver for real-world activity.
