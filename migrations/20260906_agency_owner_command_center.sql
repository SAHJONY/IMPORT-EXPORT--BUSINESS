create table if not exists logistics_agencies (
  agency_id text primary key, organization_id text not null, legal_name text not null, display_name text,
  owner_name text not null, owner_phone text, owner_email text, country text default 'US', status text not null default 'active',
  carrier_mode text not null default 'OPEN_CHOICE', preferred_provider text, use_sahjony_when_better boolean not null default true,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists logistics_agency_owner_credentials (
  credential_id text primary key, agency_id text not null references logistics_agencies(agency_id), owner_id text not null,
  owner_name text not null, token_hash text not null unique, status text not null default 'active', created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists logistics_agency_employees (
  employee_id text primary key, agency_id text not null references logistics_agencies(agency_id), full_name text not null,
  phone text, photo_url text, emergency_phone text, branch_id text, role text not null default 'operator', permissions jsonb not null default '[]'::jsonb, employee_qr_token text not null unique,
  status text not null default 'pending_verification', access_granted_by_owner_id text, access_granted_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists logistics_agency_shipments (
  agency_shipment_id text primary key, agency_id text not null references logistics_agencies(agency_id), tracking_reference text not null,
  customer_name text, origin text, destination text, carrier_choice text not null default 'AGENCY_CHOICE', weight_lb numeric,
  customer_price numeric, agency_cost numeric, status text not null default 'CREATED', created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  unique (agency_id, tracking_reference)
);
create index if not exists idx_agency_employees_tenant on logistics_agency_employees(agency_id,status);
create index if not exists idx_agency_shipments_tenant on logistics_agency_shipments(agency_id,status,updated_at desc);
