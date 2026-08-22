-- Cuba private-sector business eligibility and transaction linkage
create table if not exists cuba_private_businesses (
  id bigserial primary key,
  private_business_id text not null unique,
  legal_name text not null,
  trade_name text,
  business_type text not null check (business_type in ('SOLE_PROPRIETOR','SMALL_PRIVATE_BUSINESS','PRIVATE_COOPERATIVE','INDEPENDENT_CONTRACTOR','CONSULTANT','SMALL_FARMER','USUFRUCT_FARMER','OTHER_PRIVATE')),
  registration_reference text,
  province text,
  municipality text,
  employee_count integer not null default 0 check (employee_count >= 0),
  owner_names jsonb not null default '[]'::jsonb,
  ownership_evidence_document_ids jsonb not null default '[]'::jsonb,
  prohibited_official_owner boolean not null default false,
  prohibited_party_member_owner boolean not null default false,
  government_owned boolean not null default false,
  government_operated boolean not null default false,
  government_controlled boolean not null default false,
  state_entity_involvement text,
  state_entity_involvement_level text not null default 'NONE' check (state_entity_involvement_level in ('NONE','PACKING_ONLY','EXPORT_AGENT_ONLY','DISTRIBUTION_ONLY','PROCESSING','MANUFACTURING','CONTROL','OTHER')),
  business_categories jsonb not null default '[]'::jsonb,
  eligible_independent_private_sector boolean not null default false,
  eligibility_status text not null default 'PENDING' check (eligibility_status in ('PENDING','ELIGIBLE','INELIGIBLE','REVIEW_REQUIRED')),
  eligibility_basis text,
  ofac_definition_reference text not null default '31 CFR 515.340',
  ofac_reviewed_at timestamptz,
  bis_scp_eligible_end_user boolean not null default false,
  bis_scp_reviewed_at timestamptz,
  banking_path_verified boolean not null default false,
  uses_cuban_owned_bank boolean not null default false,
  restricted_party_screening_status text not null default 'PENDING' check (restricted_party_screening_status in ('PENDING','CLEAR','HIT','REVIEW_REQUIRED')),
  restricted_party_screened_at timestamptz,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','SUSPENDED','CLOSED')),
  verified_by text,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_private_business_evidence (
  id bigserial primary key,
  evidence_id text not null unique,
  private_business_id text not null references cuba_private_businesses(private_business_id) on delete cascade,
  evidence_type text not null,
  source text,
  reference text,
  document_id text,
  summary text not null,
  status text not null default 'PENDING' check (status in ('PENDING','VERIFIED','REJECTED','SUPERSEDED')),
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);

alter table cuba_trade_cases add column if not exists private_business_id text references cuba_private_businesses(private_business_id);

create index if not exists idx_cuba_private_business_eligibility on cuba_private_businesses(eligibility_status,status);
create index if not exists idx_cuba_private_business_screening on cuba_private_businesses(restricted_party_screening_status);
create index if not exists idx_cuba_private_business_evidence on cuba_private_business_evidence(private_business_id,status);
create index if not exists idx_cuba_trade_cases_private_business on cuba_trade_cases(private_business_id);

-- Current policy model as of 2026-08-22:
-- * OFAC 31 CFR 515.340 independent private sector entrepreneur generally includes qualifying private businesses/cooperatives up to 100 employees,
--   owned by eligible individuals and excluding prohibited Government of Cuba officials / prohibited Cuban Communist Party members.
-- * Government-owned, operated, or controlled enterprises are not treated as private-sector entities for this eligibility record.
-- * State involvement in goods can require additional review; processing/manufacturing/control by a state entity is not treated as equivalent to mere packing/export-agent involvement.
-- * BIS SCP eligibility remains transaction-specific and does not authorize every private-sector transaction.
-- * As of 2026-03-04 BIS suspended SCP 740.21(b)(1) for transactions involving deposit of foreign funds into a Cuban-owned bank.
