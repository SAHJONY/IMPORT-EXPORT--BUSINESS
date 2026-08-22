-- SAHJONY Global Trade commercial execution layer
-- Apply in InsForge before enabling live commercial operations.

create table if not exists trade_suppliers (
  id bigserial primary key,
  supplier_id text not null unique,
  legal_name text not null,
  country text,
  contact_name text,
  contact_email text,
  contact_phone text,
  payment_terms text,
  currency text,
  default_incoterm text,
  moq_notes text,
  lead_time_days integer,
  bank_verified boolean not null default false,
  compliance_status text not null default 'pending',
  quality_status text not null default 'pending',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_buyers (
  id bigserial primary key,
  buyer_id text not null unique,
  legal_name text not null,
  country text,
  contact_name text,
  contact_email text,
  contact_phone text,
  currency text,
  payment_terms text,
  credit_limit numeric,
  credit_status text not null default 'pending',
  compliance_status text not null default 'pending',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_products (
  id bigserial primary key,
  product_id text not null unique,
  sku text not null unique,
  name text not null,
  description text,
  origin_country text,
  hts_code text,
  schedule_b text,
  eccn text,
  uom text,
  dangerous_goods boolean not null default false,
  regulatory_profile jsonb not null default '{}'::jsonb,
  target_landed_cost numeric,
  target_sell_price numeric,
  minimum_margin_pct numeric,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_corridors (
  id bigserial primary key,
  corridor_id text not null unique,
  origin_country text not null,
  destination_country text not null,
  default_incoterm text,
  preferred_broker text,
  preferred_forwarder text,
  transit_days integer,
  customs_notes text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists commercial_quotes (
  id bigserial primary key,
  quote_id text not null unique,
  trade_case_id text not null,
  buyer_id text,
  product_id text,
  corridor_id text,
  quantity numeric not null,
  unit_price numeric not null,
  currency text not null default 'USD',
  incoterm text,
  freight_estimate numeric not null default 0,
  duty_estimate numeric not null default 0,
  insurance_estimate numeric not null default 0,
  finance_cost_estimate numeric not null default 0,
  other_cost_estimate numeric not null default 0,
  estimated_landed_cost numeric,
  estimated_margin numeric,
  estimated_margin_pct numeric,
  status text not null default 'draft',
  expires_at timestamptz,
  owner_approved boolean not null default false,
  created_by_role text,
  created_by_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists sales_orders (
  id bigserial primary key,
  sales_order_id text not null unique,
  trade_case_id text not null,
  quote_id text,
  buyer_id text not null,
  product_id text not null,
  quantity numeric not null,
  unit_price numeric not null,
  currency text not null default 'USD',
  incoterm text,
  payment_terms text,
  status text not null default 'pending',
  deposit_required numeric not null default 0,
  amount_collected numeric not null default 0,
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists purchase_orders (
  id bigserial primary key,
  purchase_order_id text not null unique,
  trade_case_id text not null,
  sales_order_id text,
  supplier_id text not null,
  product_id text not null,
  quantity numeric not null,
  unit_cost numeric not null,
  currency text not null default 'USD',
  incoterm text,
  payment_terms text,
  deposit_required numeric not null default 0,
  amount_paid numeric not null default 0,
  production_due_at timestamptz,
  status text not null default 'pending',
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists quality_inspections (
  id bigserial primary key,
  inspection_id text not null unique,
  trade_case_id text not null,
  purchase_order_id text,
  supplier_id text,
  product_id text,
  inspection_type text not null,
  inspector text,
  result text not null default 'pending',
  defect_rate numeric,
  evidence_document_id text,
  notes text,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists landed_costs (
  id bigserial primary key,
  landed_cost_id text not null unique,
  trade_case_id text not null,
  product_id text,
  supplier_cost numeric not null default 0,
  inland_origin numeric not null default 0,
  export_fees numeric not null default 0,
  international_freight numeric not null default 0,
  cargo_insurance numeric not null default 0,
  duty numeric not null default 0,
  customs_fees numeric not null default 0,
  broker_fees numeric not null default 0,
  warehouse numeric not null default 0,
  last_mile numeric not null default 0,
  fx_cost numeric not null default 0,
  financing_cost numeric not null default 0,
  other_cost numeric not null default 0,
  total_landed_cost numeric not null default 0,
  sales_revenue numeric not null default 0,
  gross_profit numeric not null default 0,
  gross_margin_pct numeric not null default 0,
  finalized boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_payments (
  id bigserial primary key,
  payment_id text not null unique,
  trade_case_id text not null,
  direction text not null check (direction in ('payable','receivable')),
  counterparty_type text not null check (counterparty_type in ('supplier','buyer','carrier','broker','other')),
  counterparty_id text,
  amount numeric not null,
  currency text not null default 'USD',
  payment_method text,
  beneficiary_verified boolean not null default false,
  approval_status text not null default 'pending',
  settlement_status text not null default 'pending',
  due_at timestamptz,
  settled_at timestamptz,
  evidence_document_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists inventory_positions (
  id bigserial primary key,
  inventory_id text not null unique,
  product_id text not null,
  location_name text not null,
  lot_number text,
  quantity_on_hand numeric not null default 0,
  quantity_reserved numeric not null default 0,
  quantity_damaged numeric not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists trade_incidents (
  id bigserial primary key,
  incident_id text not null unique,
  trade_case_id text not null,
  category text not null,
  severity text not null default 'medium',
  title text not null,
  detail text,
  status text not null default 'open',
  owner_action_required boolean not null default false,
  resolution text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table if not exists trade_readiness_checks (
  id bigserial primary key,
  check_id text not null unique,
  trade_case_id text not null,
  check_key text not null,
  label text not null,
  status text not null default 'pending',
  evidence_ref text,
  notes text,
  updated_at timestamptz not null default now(),
  unique(trade_case_id, check_key)
);

create index if not exists idx_quotes_case on commercial_quotes(trade_case_id, created_at desc);
create index if not exists idx_sales_case on sales_orders(trade_case_id, created_at desc);
create index if not exists idx_po_case on purchase_orders(trade_case_id, created_at desc);
create index if not exists idx_quality_case on quality_inspections(trade_case_id, created_at desc);
create index if not exists idx_landed_case on landed_costs(trade_case_id, created_at desc);
create index if not exists idx_payments_case on trade_payments(trade_case_id, created_at desc);
create index if not exists idx_incidents_case on trade_incidents(trade_case_id, created_at desc);
create index if not exists idx_readiness_case on trade_readiness_checks(trade_case_id, updated_at desc);
