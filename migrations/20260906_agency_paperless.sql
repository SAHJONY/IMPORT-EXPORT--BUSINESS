create table if not exists logistics_agency_paperless_records (
  record_id text primary key,
  agency_id text not null,
  record_type text not null,
  title text not null,
  related_type text,
  related_id text,
  content jsonb not null default '{}'::jsonb,
  signer_name text,
  signer_phone text,
  signature_method text,
  signature_hash text,
  status text not null default 'DRAFT',
  status_note text,
  customer_visible boolean not null default false,
  created_by_owner_id text not null,
  updated_by_owner_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_agency_paperless_agency on logistics_agency_paperless_records(agency_id, created_at desc);
create index if not exists idx_agency_paperless_related on logistics_agency_paperless_records(agency_id, related_type, related_id);
