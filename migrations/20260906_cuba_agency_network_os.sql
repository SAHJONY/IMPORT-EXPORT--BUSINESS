create table if not exists logistics_agency_packages (
  package_id text primary key, agency_id text not null, tracking_reference text not null, recipient_name text not null, recipient_phone text, destination_province text not null, description text not null, pieces integer not null default 1, weight_lb numeric, declared_value numeric, service_mode text, customer_reference text, stage text not null, status text not null, public_tracking_token text not null unique, last_location text, weight_variance_lb numeric, created_at timestamptz not null, updated_at timestamptz not null
);
create index if not exists idx_agency_packages_tenant on logistics_agency_packages(agency_id, updated_at desc);
create table if not exists logistics_agency_custody_events (
  custody_event_id text primary key, agency_id text not null, package_id text not null, action text not null, stage text not null, employee_id text, from_party text, to_party text, location text, weight_lb numeric, photo_refs jsonb not null default '[]', offline_event_id text not null, client_captured_at timestamptz, notes text, server_recorded_at timestamptz not null, immutable boolean not null default true, unique(agency_id, offline_event_id)
);
create index if not exists idx_custody_package on logistics_agency_custody_events(agency_id, package_id, server_recorded_at desc);
create table if not exists logistics_agency_exceptions (
  exception_id text primary key, agency_id text not null, package_id text not null, exception_type text not null, severity text not null, description text not null, evidence_refs jsonb not null default '[]', status text not null, created_at timestamptz not null, updated_at timestamptz not null
);
create index if not exists idx_exceptions_open on logistics_agency_exceptions(agency_id,status,severity);
create table if not exists logistics_agency_deliveries (
  delivery_id text primary key, agency_id text not null, package_id text not null, recipient_name text not null, parcel_count integer not null, condition text not null, recipient_confirmation text not null, signature_method text, signature_hash text, photo_refs jsonb not null default '[]', offline_event_id text not null, comments text, stage text not null, server_recorded_at timestamptz not null, unique(agency_id, offline_event_id)
);
create index if not exists idx_delivery_package on logistics_agency_deliveries(agency_id, package_id, server_recorded_at desc);
