-- SAHJONY Global Trade customer CRM + sourcing intake
-- Apply to production InsForge before enabling persistence-dependent live operations.

create table if not exists customer_accounts (
  customer_id text primary key,
  legal_name text not null,
  trade_name text,
  contact_name text not null,
  email text not null,
  phone text,
  country_code text,
  website text,
  status text not null default 'PROSPECT',
  assigned_employee_id text,
  source text default 'WEB',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists customer_accounts_email_idx on customer_accounts(lower(email));
create index if not exists customer_accounts_status_idx on customer_accounts(status);

create table if not exists customer_trade_intakes (
  intake_id text primary key,
  customer_id text references customer_accounts(customer_id),
  product_need text not null,
  specifications text,
  quantity numeric,
  target_budget numeric,
  currency text not null default 'USD',
  destination_country text not null,
  target_delivery_date date,
  preferred_incoterm text,
  notes text,
  status text not null default 'NEW',
  qualification_status text not null default 'PENDING',
  assigned_employee_id text,
  managed_trade_request_id text,
  sourcing_request_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists customer_trade_intakes_customer_idx on customer_trade_intakes(customer_id);
create index if not exists customer_trade_intakes_status_idx on customer_trade_intakes(status);
create index if not exists customer_trade_intakes_assignee_idx on customer_trade_intakes(assigned_employee_id);

create table if not exists customer_crm_audit (
  event_id text primary key,
  customer_id text,
  intake_id text,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists customer_crm_audit_intake_idx on customer_crm_audit(intake_id, created_at desc);
