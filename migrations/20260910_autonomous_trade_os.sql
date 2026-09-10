create table if not exists trade_os_opportunities (
  opportunity_id text primary key,
  canonical_deal_id text,
  stage text not null check (stage in ('DEMAND','RFQ','SUPPLIER','VERIFICATION','LANDED_COST','MARGIN','LOGISTICS','KYB','QUOTE','NEGOTIATION','PO','SHIPMENT','COLLECTION')),
  buyer_ref text,
  supplier_ref text,
  product_ref text,
  product_name text,
  specification text,
  quantity numeric,
  quantity_unit text,
  destination_port_ref text,
  destination_text text,
  incoterm text,
  required_by timestamptz,
  payment_terms text,
  currency text not null default 'USD',
  supplier_unit_cost numeric,
  freight_cost numeric,
  duties_cost numeric,
  insurance_cost numeric,
  inspection_cost numeric,
  banking_cost numeric,
  other_cost numeric,
  landed_cost_total numeric,
  buyer_unit_price numeric,
  protected_fee_usd numeric,
  projected_gross_profit_usd numeric,
  capital_at_risk_usd numeric not null default 0 check (capital_at_risk_usd >= 0),
  confidence numeric check (confidence is null or (confidence >= 0 and confidence <= 1)),
  blocker text,
  next_action text,
  source_of_truth text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_os_evidence (
  evidence_id text primary key,
  opportunity_id text references trade_os_opportunities(opportunity_id) on delete cascade,
  evidence_type text not null,
  evidence_status text not null check (evidence_status in ('VERIFIED','UNVERIFIED','REFERENCE','MISSING')),
  source_name text,
  source_ref text,
  observed_at timestamptz,
  expires_at timestamptz,
  confidence numeric check (confidence is null or (confidence >= 0 and confidence <= 1)),
  content_hash text,
  note text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists trade_os_business_nodes (
  node_id text primary key,
  node_type text not null check (node_type in ('BUYER','SUPPLIER','RFQ','QUOTE','SHIPMENT','PRODUCT','PORT','PAYMENT','COUNTERPARTY','EVIDENCE')),
  canonical_ref text,
  display_name text,
  status text not null,
  source_of_truth text not null,
  verified_at timestamptz,
  confidence numeric check (confidence is null or (confidence >= 0 and confidence <= 1)),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_os_business_edges (
  edge_id text primary key,
  from_node_id text not null references trade_os_business_nodes(node_id) on delete cascade,
  to_node_id text not null references trade_os_business_nodes(node_id) on delete cascade,
  relation text not null,
  verified boolean not null default false,
  evidence_ids jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (from_node_id,to_node_id,relation)
);

create table if not exists trade_os_agent_jobs (
  job_id text primary key,
  idempotency_key text not null unique,
  opportunity_id text references trade_os_opportunities(opportunity_id) on delete set null,
  agent text not null,
  department text not null,
  goal text not null,
  execution_provider text,
  state text not null check (state in ('QUEUED','RUNNING','WAITING_AUTH','WAITING_PROVIDER','RETRYING','BLOCKED','SUCCEEDED','FAILED','CANCELLED')),
  attempt integer not null default 0 check (attempt >= 0),
  max_attempts integer not null default 3 check (max_attempts >= 1),
  checkpoint jsonb not null default '{}'::jsonb,
  resume_cursor text,
  credential_expires_at timestamptz,
  next_retry_at timestamptz,
  last_error text,
  terminal_outcome text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_os_action_traces (
  trace_id text primary key,
  job_id text references trade_os_agent_jobs(job_id) on delete set null,
  opportunity_id text references trade_os_opportunities(opportunity_id) on delete set null,
  action_id text not null,
  agent text not null,
  department text not null,
  tool_name text not null,
  provider text,
  goal text not null,
  risk text not null check (risk in ('LOW','MEDIUM','HIGH','CRITICAL')),
  decision text not null,
  approval text not null check (approval in ('NOT_REQUIRED','PENDING','APPROVED','REJECTED')),
  state text not null check (state in ('QUEUED','RUNNING','WAITING','RETRYING','BLOCKED','SUCCEEDED','FAILED','CANCELLED')),
  evidence_ids jsonb not null default '[]'::jsonb,
  cost_usd numeric check (cost_usd is null or cost_usd >= 0),
  outcome text,
  business_impact jsonb not null default '{}'::jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists trade_os_approvals (
  approval_id text primary key,
  opportunity_id text references trade_os_opportunities(opportunity_id) on delete cascade,
  job_id text references trade_os_agent_jobs(job_id) on delete set null,
  approval_type text not null,
  requested_by text not null,
  state text not null check (state in ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  requested_payload jsonb not null default '{}'::jsonb,
  approved_by text,
  decided_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_trade_os_opportunities_stage on trade_os_opportunities(stage,updated_at desc);
create index if not exists idx_trade_os_evidence_opportunity on trade_os_evidence(opportunity_id,evidence_type,evidence_status);
create index if not exists idx_trade_os_nodes_type_ref on trade_os_business_nodes(node_type,canonical_ref);
create index if not exists idx_trade_os_edges_from on trade_os_business_edges(from_node_id,relation);
create index if not exists idx_trade_os_edges_to on trade_os_business_edges(to_node_id,relation);
create index if not exists idx_trade_os_jobs_state_retry on trade_os_agent_jobs(state,next_retry_at,updated_at);
create index if not exists idx_trade_os_traces_job on trade_os_action_traces(job_id,created_at desc);
create index if not exists idx_trade_os_traces_opportunity on trade_os_action_traces(opportunity_id,created_at desc);
create index if not exists idx_trade_os_approvals_state on trade_os_approvals(state,created_at desc);

alter table trade_os_opportunities enable row level security;
alter table trade_os_evidence enable row level security;
alter table trade_os_business_nodes enable row level security;
alter table trade_os_business_edges enable row level security;
alter table trade_os_agent_jobs enable row level security;
alter table trade_os_action_traces enable row level security;
alter table trade_os_approvals enable row level security;

comment on table trade_os_opportunities is 'Canonical evidence-gated autonomous trade opportunity state. Server-controlled until owner RLS policies are explicitly installed.';
comment on table trade_os_agent_jobs is 'Durable resumable agent jobs with idempotency, checkpoint, auth/provider wait states and terminal outcomes.';
comment on table trade_os_action_traces is 'Enterprise action observability: tool, evidence, cost, decision, approval, outcome and business impact.';
comment on table trade_os_business_nodes is 'Canonical trade business graph nodes. A CRM record alone does not imply qualified demand or revenue.';
