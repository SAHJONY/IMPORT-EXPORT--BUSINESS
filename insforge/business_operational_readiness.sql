-- SAHJONY Business Operational Readiness
-- Operational records required before the platform may claim 100% real-business readiness.

create table if not exists operating_partners (
  id bigserial primary key,
  partner_id text not null unique,
  partner_type text not null check (partner_type in ('CUSTOMS_BROKER','FREIGHT_FORWARDER','CARRIER','CARGO_INSURER','TRADE_CREDIT_INSURER','PAYMENT_PROVIDER','BANK','WAREHOUSE_3PL','LEGAL_COUNSEL','ACCOUNTING_TAX','INSPECTION_QC')),
  legal_name text not null,
  country_code text,
  contact_name text,
  contact_email text,
  contact_phone text,
  license_or_registration text,
  coverage_scope jsonb not null default '{}'::jsonb,
  evidence_document_ids jsonb not null default '[]'::jsonb,
  due_diligence_status text not null default 'PENDING' check (due_diligence_status in ('PENDING','PASS','FAIL','REVIEW')),
  contract_status text not null default 'NONE' check (contract_status in ('NONE','DRAFT','SIGNED','EXPIRED','TERMINATED')),
  active boolean not null default false,
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists business_agreement_templates (
  id bigserial primary key,
  template_id text not null unique,
  template_type text not null check (template_type in ('INTERMEDIARY_AGREEMENT','BUYING_AGENT_AGREEMENT','SELLING_AGENT_AGREEMENT','SOURCING_AGREEMENT','SUPPLIER_TERMS','CUSTOMER_TERMS','NDA','FEE_SCHEDULE','REFUND_CLAIMS_POLICY','COMPLIANCE_ACKNOWLEDGEMENT')),
  version text not null,
  title text not null,
  document_id text,
  status text not null default 'DRAFT' check (status in ('DRAFT','LEGAL_REVIEW','APPROVED','RETIRED')),
  owner_approved boolean not null default false,
  approved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(template_type,version)
);

create table if not exists counterparty_due_diligence (
  id bigserial primary key,
  dossier_id text not null unique,
  counterparty_type text not null check (counterparty_type in ('CUSTOMER','PRIVATE_BUSINESS','SUPPLIER','PARTNER')),
  counterparty_ref text,
  legal_name text not null,
  country_code text,
  beneficial_owners jsonb not null default '[]'::jsonb,
  identity_documents jsonb not null default '[]'::jsonb,
  registration_documents jsonb not null default '[]'::jsonb,
  tax_registration text,
  bank_evidence_document_ids jsonb not null default '[]'::jsonb,
  sanctions_screening_status text not null default 'PENDING' check (sanctions_screening_status in ('PENDING','CLEAR','HIT','REVIEW')),
  kyb_status text not null default 'PENDING' check (kyb_status in ('PENDING','PASS','FAIL','REVIEW')),
  risk_rating text not null default 'UNRATED' check (risk_rating in ('UNRATED','LOW','MEDIUM','HIGH','PROHIBITED')),
  reviewed_by text,
  reviewed_at timestamptz,
  active boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trade_product_dossiers (
  id bigserial primary key,
  dossier_id text not null unique,
  product_id text,
  sku text,
  product_name text not null,
  origin_country text,
  destination_country text,
  hts_code text,
  schedule_b text,
  eccn text,
  ear99 boolean,
  authorization_basis text,
  license_or_exception_reference text,
  prohibited_or_restricted boolean not null default false,
  classification_evidence_document_ids jsonb not null default '[]'::jsonb,
  labeling_requirements jsonb not null default '{}'::jsonb,
  permit_requirements jsonb not null default '{}'::jsonb,
  status text not null default 'PENDING' check (status in ('PENDING','PASS','FAIL','REVIEW')),
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists business_incident_cases (
  id bigserial primary key,
  incident_id text not null unique,
  managed_case_id text,
  trade_case_id text,
  incident_type text not null check (incident_type in ('CUSTOMS_HOLD','DOCUMENT_ERROR','DAMAGE','SUPPLIER_DELAY','MISSED_SAILING','PAYMENT_FAILURE','SANCTIONS_HIT','DEMURRAGE_DETENTION','CLAIM','REFUND_DISPUTE','QUALITY_FAILURE','OTHER')),
  severity text not null default 'MEDIUM' check (severity in ('LOW','MEDIUM','HIGH','CRITICAL')),
  status text not null default 'OPEN' check (status in ('OPEN','INVESTIGATING','ACTION_REQUIRED','RESOLVED','CLOSED')),
  summary text not null,
  owner_required boolean not null default false,
  resolution_summary text,
  evidence_document_ids jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table if not exists first_live_trade_certification (
  id bigserial primary key,
  certification_id text not null unique,
  managed_case_id text not null,
  trade_case_id text,
  customer_ref text,
  supplier_ref text,
  started_at timestamptz,
  delivered_at timestamptz,
  reconciled_at timestamptz,
  customer_paid boolean not null default false,
  supplier_paid boolean not null default false,
  freight_duty_reconciled boolean not null default false,
  sahjony_fee_collected boolean not null default false,
  final_pnl numeric,
  audit_closed boolean not null default false,
  unresolved_incidents integer not null default 0,
  e2e_status text not null default 'IN_PROGRESS' check (e2e_status in ('IN_PROGRESS','FAILED','PASSED')),
  owner_certified boolean not null default false,
  owner_certified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_operating_partners_type on operating_partners(partner_type,active);
create index if not exists idx_counterparty_dd_status on counterparty_due_diligence(counterparty_type,kyb_status,risk_rating);
create index if not exists idx_product_dossiers_status on trade_product_dossiers(status,owner_approved);
create index if not exists idx_business_incidents_case on business_incident_cases(managed_case_id,status,severity);
