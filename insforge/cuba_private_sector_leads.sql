-- SAHJONY Cuba Private Sector Acquisition Funnel
-- Public commercial intake only. Does not itself establish OFAC/BIS eligibility or transaction authorization.

create table if not exists cuba_private_sector_leads (
  lead_id text primary key,
  business_name text not null,
  contact_name text not null,
  contact_method text not null,
  email text,
  phone_whatsapp text,
  province text,
  municipality text,
  employee_count integer,
  business_activity text,
  product_need text not null,
  specifications text,
  quantity numeric,
  target_budget numeric,
  currency text not null default 'USD',
  target_delivery_date text,
  preferred_origin_countries jsonb not null default '[]'::jsonb,
  accepts_global_sourcing boolean not null default true,
  payment_preference text,
  notes text,
  source text not null default 'CUBA_PRIVATE_SECTOR_PORTAL',
  status text not null default 'NEW' check (status in ('NEW','QUALIFICATION','KYB_REQUIRED','QUALIFIED','SOURCING','HOLD','CLOSED')),
  compliance_status text not null default 'NOT_REVIEWED' check (compliance_status in ('NOT_REVIEWED','REVIEW_REQUIRED','PASS','FAIL')),
  managed_request_id text,
  assigned_employee_id text,
  consent_to_business_contact boolean not null default false,
  submitted_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists cuba_private_sector_leads_status_idx on cuba_private_sector_leads(status, submitted_at desc);
create index if not exists cuba_private_sector_leads_business_idx on cuba_private_sector_leads(business_name);

-- Keep public submissions structurally separate from eligibility records and managed execution cases.
-- Promotion into managed_trade_requests must be an authenticated employee/owner action after qualification.
