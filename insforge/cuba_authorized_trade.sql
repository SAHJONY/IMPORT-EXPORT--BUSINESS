-- Cuba Authorized Trade Desk: lawful U.S. -> Cuba transaction governance
create table if not exists cuba_trade_employees (
  id bigserial primary key,
  employee_id text not null unique,
  display_name text not null,
  email text,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','SUSPENDED','REVOKED')),
  may_prepare boolean not null default true,
  may_submit boolean not null default false,
  may_release boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_trade_authorizations (
  id bigserial primary key,
  authorization_id text not null unique,
  employee_id text references cuba_trade_employees(employee_id),
  authorization_type text not null,
  authority text not null,
  reference_number text,
  license_exception text,
  legal_basis text not null,
  effective_at timestamptz,
  expires_at timestamptz,
  scope_products jsonb not null default '[]'::jsonb,
  scope_eccns jsonb not null default '[]'::jsonb,
  scope_end_users jsonb not null default '[]'::jsonb,
  scope_end_uses jsonb not null default '[]'::jsonb,
  max_value numeric,
  currency text,
  evidence_document_id text,
  status text not null default 'PENDING' check (status in ('PENDING','VERIFIED','REJECTED','EXPIRED','REVOKED')),
  verified_by text,
  verified_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_trade_cases (
  id bigserial primary key,
  trade_case_id text not null unique,
  employee_id text not null references cuba_trade_employees(employee_id),
  authorization_id text references cuba_trade_authorizations(authorization_id),
  origin_country text not null default 'US',
  destination_country text not null default 'CU',
  product_description text not null,
  product_id text,
  eccn text,
  ear99 boolean,
  quantity numeric,
  transaction_value numeric,
  currency text not null default 'USD',
  consignee_name text not null,
  end_user_name text not null,
  end_use text not null,
  payment_path text,
  bank_name text,
  status text not null default 'DRAFT' check (status in ('DRAFT','COMPLIANCE_REVIEW','HOLD','AUTHORIZED','RELEASED','CANCELLED','CLOSED')),
  release_allowed boolean not null default false,
  release_reason text,
  owner_approved boolean not null default false,
  owner_approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_trade_case_gates (
  id bigserial primary key,
  gate_id text not null unique,
  trade_case_id text not null references cuba_trade_cases(trade_case_id) on delete cascade,
  gate_key text not null,
  gate_label text not null,
  status text not null default 'PENDING' check (status in ('PENDING','PASS','FAIL','NOT_APPLICABLE')),
  evidence_summary text,
  evidence_reference text,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(trade_case_id, gate_key)
);

create table if not exists cuba_trade_audit (
  id bigserial primary key,
  event_id text not null unique,
  trade_case_id text,
  employee_id text,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_cuba_trade_employee on cuba_trade_cases(employee_id,status);
create index if not exists idx_cuba_trade_auth on cuba_trade_authorizations(employee_id,status,expires_at);
create index if not exists idx_cuba_trade_case_gates on cuba_trade_case_gates(trade_case_id,status);

-- Release rule: a Cuba trade case must never be released merely because an employee is assigned.
-- Release requires a verified authorization plus PASS/NOT_APPLICABLE on all required transaction gates,
-- including product classification, authorization scope, end-user/end-use, sanctions screening,
-- banking/payment, documents, logistics, and owner release approval.
