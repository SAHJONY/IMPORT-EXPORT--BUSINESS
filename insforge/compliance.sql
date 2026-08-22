-- SAHJONY Global Trade compliance and legal control plane
create table if not exists trade_compliance_cases (
  id bigserial primary key,
  compliance_id text not null unique,
  trade_case_id text not null,
  shipment_id text,
  customer_id text,
  direction text not null check (direction in ('import','export','domestic','cross_trade')),
  origin_country text,
  destination_country text,
  importer_of_record text,
  exporter_usppi text,
  consignee text,
  end_user text,
  incoterm text,
  customs_broker text,
  freight_forwarder text,
  hts_code text,
  schedule_b text,
  eccn text,
  ear99 boolean,
  customs_value numeric,
  customs_currency text,
  country_of_origin text,
  valuation_method text,
  sanctions_status text not null default 'pending' check (sanctions_status in ('pending','clear','review','blocked')),
  export_control_status text not null default 'pending' check (export_control_status in ('pending','nrl','license_required','licensed','blocked')),
  customs_status text not null default 'pending' check (customs_status in ('pending','ready','filed','released','hold','blocked')),
  agency_status text not null default 'pending' check (agency_status in ('pending','not_applicable','ready','approved','hold','blocked')),
  legal_status text not null default 'pending' check (legal_status in ('pending','ready','approved','hold','blocked')),
  release_status text not null default 'blocked' check (release_status in ('blocked','review','ready','released')),
  customer_visible boolean not null default false,
  created_by_role text not null,
  created_by_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists compliance_requirements (
  id bigserial primary key,
  requirement_id text not null unique,
  compliance_id text not null,
  category text not null,
  authority text,
  requirement_name text not null,
  applicability text not null default 'review' check (applicability in ('required','not_applicable','review')),
  status text not null default 'open' check (status in ('open','in_progress','satisfied','waived','blocked')),
  evidence_document_id text,
  filing_reference text,
  due_at timestamptz,
  completed_at timestamptz,
  completed_by_role text,
  completed_by_id text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists compliance_screenings (
  id bigserial primary key,
  screening_id text not null unique,
  compliance_id text not null,
  party_role text not null,
  party_name text not null,
  source text not null,
  result text not null check (result in ('clear','candidate_match','blocked','error')),
  raw_reference text,
  screened_at timestamptz not null default now(),
  screened_by text not null
);

create table if not exists regulatory_determinations (
  id bigserial primary key,
  determination_id text not null unique,
  compliance_id text not null,
  determination_type text not null,
  value text,
  authority text,
  rationale text,
  confidence text not null default 'review' check (confidence in ('review','supported','authoritative')),
  evidence_document_id text,
  approved_by_role text,
  approved_by_id text,
  created_at timestamptz not null default now()
);

create table if not exists compliance_audit_events (
  id bigserial primary key,
  event_id text not null unique,
  compliance_id text not null,
  actor_role text not null,
  actor_id text not null,
  event_type text not null,
  detail text,
  release_effect text not null default 'none' check (release_effect in ('none','review','block','unblock')),
  created_at timestamptz not null default now()
);

create index if not exists idx_trade_compliance_case on trade_compliance_cases(trade_case_id, updated_at desc);
create index if not exists idx_trade_compliance_customer on trade_compliance_cases(customer_id, updated_at desc);
create index if not exists idx_compliance_requirements_case on compliance_requirements(compliance_id, status, category);
create index if not exists idx_compliance_screenings_case on compliance_screenings(compliance_id, screened_at desc);
create index if not exists idx_regulatory_determinations_case on regulatory_determinations(compliance_id, created_at desc);
create index if not exists idx_compliance_audit_case on compliance_audit_events(compliance_id, created_at desc);

-- Browser-facing production must add tenant-scoped RLS before customer exposure.
