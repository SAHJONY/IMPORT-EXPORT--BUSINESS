-- SAHJONY United States Import Desk
create table if not exists us_import_cases (
  id bigserial primary key,
  import_case_id text not null unique,
  managed_trade_case_id text,
  customer_ref text,
  assigned_employee_id text,
  product_description text not null,
  supplier_name text,
  supplier_country text not null,
  origin_country text not null,
  destination_country text not null default 'US',
  port_of_entry text,
  importer_of_record text,
  customs_broker text,
  freight_forwarder text,
  carrier text,
  incoterm text,
  hts_code text,
  country_of_origin_marking text,
  pga_agencies jsonb not null default '[]'::jsonb,
  entry_number text,
  estimated_customs_value numeric,
  estimated_duty numeric,
  estimated_freight numeric,
  estimated_insurance numeric,
  estimated_other_costs numeric,
  estimated_landed_cost numeric,
  currency text not null default 'USD',
  status text not null default 'INTAKE' check (status in ('INTAKE','SOURCING','DUE_DILIGENCE','CUSTOMS_REVIEW','READY_FOR_ENTRY','IN_TRANSIT','ARRIVED','CUSTOMS_HOLD','RELEASED','DELIVERED','RECONCILED','HOLD','CANCELLED')),
  release_allowed boolean not null default false,
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists us_import_gates (
  id bigserial primary key,
  gate_id text not null unique,
  import_case_id text not null references us_import_cases(import_case_id) on delete cascade,
  gate_key text not null,
  label text not null,
  status text not null default 'PENDING' check (status in ('PENDING','PASS','FAIL','NOT_APPLICABLE')),
  evidence_reference text,
  notes text,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(import_case_id, gate_key)
);

create table if not exists us_import_audit (
  id bigserial primary key,
  event_id text not null unique,
  import_case_id text,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_us_import_cases_status on us_import_cases(status, updated_at desc);
create index if not exists idx_us_import_gates_case on us_import_gates(import_case_id, gate_key);
