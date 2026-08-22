-- SAHJONY Managed Trade Gateway
-- SAHJONY acts as transaction orchestrator/gatekeeper unless a case explicitly assigns another legal role.
create table if not exists managed_trade_requests (
  id bigserial primary key,
  request_id text not null unique,
  requester_type text not null check (requester_type in ('PRIVATE_BUSINESS','BUYER','EMPLOYEE','OTHER')),
  requester_ref text,
  private_business_id text,
  employee_id text,
  product_need text not null,
  specifications text,
  quantity numeric,
  target_budget numeric,
  currency text not null default 'USD',
  destination_country text not null default 'CU',
  target_delivery_date date,
  status text not null default 'INTAKE' check (status in ('INTAKE','SOURCING','SUPPLIER_SHORTLIST','DUE_DILIGENCE','QUOTE_READY','APPROVAL','EXECUTION','HOLD','CLOSED','CANCELLED')),
  assigned_owner_id text,
  assigned_employee_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists managed_supplier_candidates (
  id bigserial primary key,
  candidate_id text not null unique,
  request_id text not null references managed_trade_requests(request_id) on delete cascade,
  supplier_id text,
  supplier_name text not null,
  supplier_country text,
  product_match text,
  unit_cost numeric,
  moq numeric,
  lead_time_days integer,
  payment_terms text,
  incoterm text,
  compliance_status text not null default 'PENDING' check (compliance_status in ('PENDING','PASS','FAIL','REVIEW')),
  quality_status text not null default 'PENDING' check (quality_status in ('PENDING','PASS','FAIL','REVIEW')),
  bank_status text not null default 'PENDING' check (bank_status in ('PENDING','PASS','FAIL','REVIEW')),
  score numeric,
  evidence jsonb not null default '{}'::jsonb,
  selected boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists managed_trade_cases (
  id bigserial primary key,
  managed_case_id text not null unique,
  request_id text not null references managed_trade_requests(request_id),
  cuba_trade_case_id text,
  private_business_id text,
  supplier_candidate_id text,
  supplier_id text,
  buyer_id text,
  product_id text,
  quote_id text,
  purchase_order_id text,
  sales_order_id text,
  shipment_id text,
  compliance_case_id text,
  orchestrator_name text not null default 'SAHJONY',
  sahjony_role text not null default 'MANAGED_TRADE_ORCHESTRATOR' check (sahjony_role in ('MANAGED_TRADE_ORCHESTRATOR','AGENT','DISTRIBUTOR','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','PRINCIPAL')),
  exporter_of_record text,
  importer_of_record text,
  customs_broker text,
  freight_forwarder text,
  settlement_provider text,
  status text not null default 'OPEN' check (status in ('OPEN','READY_FOR_EXECUTION','EXECUTING','HOLD','DELIVERED','RECONCILED','CLOSED','CANCELLED')),
  release_allowed boolean not null default false,
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists managed_trade_milestones (
  id bigserial primary key,
  milestone_id text not null unique,
  managed_case_id text not null references managed_trade_cases(managed_case_id) on delete cascade,
  milestone_key text not null,
  label text not null,
  status text not null default 'PENDING' check (status in ('PENDING','PASS','FAIL','NOT_APPLICABLE')),
  evidence_reference text,
  notes text,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(managed_case_id, milestone_key)
);

create table if not exists managed_trade_audit (
  id bigserial primary key,
  event_id text not null unique,
  managed_case_id text,
  request_id text,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_managed_requests_status on managed_trade_requests(status, updated_at desc);
create index if not exists idx_managed_candidates_request on managed_supplier_candidates(request_id, selected, score desc);
create index if not exists idx_managed_cases_status on managed_trade_cases(status, updated_at desc);
create index if not exists idx_managed_milestones_case on managed_trade_milestones(managed_case_id, milestone_key);
