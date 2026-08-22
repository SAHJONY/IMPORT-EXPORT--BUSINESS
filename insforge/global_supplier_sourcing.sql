-- SAHJONY Global Supplier Sourcing
-- Enables supplier sourcing from any country while keeping origin->destination corridors fail-closed.

create table if not exists global_sourcing_requests (
  id bigserial primary key,
  sourcing_request_id text not null unique,
  managed_request_id text references managed_trade_requests(request_id) on delete cascade,
  private_business_id text,
  product_need text not null,
  specifications text,
  quantity numeric,
  destination_country text not null default 'CU',
  allowed_origin_countries text[] not null default '{}',
  excluded_origin_countries text[] not null default '{}',
  worldwide_search boolean not null default true,
  target_budget numeric,
  currency text not null default 'USD',
  target_delivery_date date,
  status text not null default 'OPEN' check (status in ('OPEN','SEARCHING','SHORTLISTED','HOLD','CLOSED','CANCELLED')),
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists global_supplier_candidates (
  id bigserial primary key,
  global_candidate_id text not null unique,
  sourcing_request_id text not null references global_sourcing_requests(sourcing_request_id) on delete cascade,
  supplier_name text not null,
  supplier_country text not null,
  supplier_id text,
  website text,
  product_match text,
  unit_cost numeric,
  currency text,
  moq numeric,
  lead_time_days integer,
  incoterm text,
  payment_terms text,
  source_reference text,
  source_evidence jsonb not null default '{}'::jsonb,
  supplier_screening_status text not null default 'PENDING' check (supplier_screening_status in ('PENDING','PASS','FAIL','REVIEW')),
  origin_export_control_status text not null default 'PENDING' check (origin_export_control_status in ('PENDING','PASS','FAIL','REVIEW','NOT_APPLICABLE')),
  destination_import_control_status text not null default 'PENDING' check (destination_import_control_status in ('PENDING','PASS','FAIL','REVIEW','NOT_APPLICABLE')),
  product_restriction_status text not null default 'PENDING' check (product_restriction_status in ('PENDING','PASS','FAIL','REVIEW','NOT_APPLICABLE')),
  banking_status text not null default 'PENDING' check (banking_status in ('PENDING','PASS','FAIL','REVIEW')),
  logistics_status text not null default 'PENDING' check (logistics_status in ('PENDING','PASS','FAIL','REVIEW')),
  tax_duty_status text not null default 'PENDING' check (tax_duty_status in ('PENDING','PASS','FAIL','REVIEW','NOT_APPLICABLE')),
  us_nexus_status text not null default 'PENDING' check (us_nexus_status in ('PENDING','PASS','FAIL','REVIEW','NOT_APPLICABLE')),
  corridor_status text not null default 'BLOCKED' check (corridor_status in ('READY','LIMITED','BLOCKED')),
  landed_cost_estimate numeric,
  score numeric,
  selected boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists global_sourcing_control_evidence (
  id bigserial primary key,
  evidence_id text not null unique,
  global_candidate_id text not null references global_supplier_candidates(global_candidate_id) on delete cascade,
  control_key text not null,
  authority text,
  reference text,
  summary text not null,
  effective_at timestamptz,
  expires_at timestamptz,
  verified boolean not null default false,
  verified_by text,
  verified_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_global_sourcing_requests_status on global_sourcing_requests(status, updated_at desc);
create index if not exists idx_global_supplier_candidates_request on global_supplier_candidates(sourcing_request_id, selected, score desc);
create index if not exists idx_global_supplier_candidates_country on global_supplier_candidates(supplier_country, corridor_status);
