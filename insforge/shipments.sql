-- SAHJONY Global Trade end-to-end shipment tracking
-- Apply in InsForge before enabling production shipment tracking.

create table if not exists shipments (
  id bigserial primary key,
  shipment_id text not null unique,
  trade_case_id text not null,
  customer_id text,
  transport_mode text not null check (transport_mode in ('ocean','air','ground','lcl','parcel','multimodal')),
  provider text not null default 'maersk',
  tracking_reference text not null,
  booking_reference text,
  container_number text,
  bill_of_lading text,
  air_waybill text,
  origin_name text,
  origin_code text,
  destination_name text,
  destination_code text,
  current_stage text not null default 'booked',
  current_status text not null default 'pending',
  current_location text,
  estimated_departure_at timestamptz,
  actual_departure_at timestamptz,
  estimated_arrival_at timestamptz,
  actual_arrival_at timestamptz,
  estimated_delivery_at timestamptz,
  actual_delivery_at timestamptz,
  delay_minutes integer not null default 0,
  exception_code text,
  exception_detail text,
  customer_visible boolean not null default true,
  last_provider_sync_at timestamptz,
  last_event_at timestamptz,
  created_by_role text not null check (created_by_role in ('owner','employee','customer','system')),
  created_by_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider, tracking_reference, trade_case_id)
);

create table if not exists shipment_milestones (
  id bigserial primary key,
  milestone_id text not null unique,
  shipment_id text not null,
  sequence_no integer,
  stage text not null,
  event_code text,
  event_label text not null,
  status text not null default 'confirmed' check (status in ('planned','estimated','confirmed','exception','cancelled')),
  location_name text,
  location_code text,
  terminal text,
  transport_mode text,
  event_time timestamptz,
  event_time_type text,
  source text not null default 'provider',
  raw_reference text,
  customer_visible boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists shipment_sync_events (
  id bigserial primary key,
  sync_id text not null unique,
  shipment_id text not null,
  provider text not null,
  sync_status text not null check (sync_status in ('success','partial','error','skipped')),
  new_milestones integer not null default 0,
  eta_changed boolean not null default false,
  exception_detected boolean not null default false,
  detail text,
  synced_at timestamptz not null default now()
);

create index if not exists idx_shipments_case on shipments(trade_case_id, updated_at desc);
create index if not exists idx_shipments_customer on shipments(customer_id, updated_at desc);
create index if not exists idx_shipments_tracking on shipments(provider, tracking_reference);
create index if not exists idx_shipments_stage on shipments(current_stage, current_status, updated_at desc);
create index if not exists idx_milestones_shipment on shipment_milestones(shipment_id, event_time asc, created_at asc);
create index if not exists idx_sync_shipment on shipment_sync_events(shipment_id, synced_at desc);

-- Production RLS requirements:
-- 1. Customers may select only shipments whose customer_id maps to their authenticated participant identity and customer_visible=true.
-- 2. Customers may select only customer_visible milestones for those shipments.
-- 3. Employees may operate shipments but may not alter owner-governed approval/release records.
-- 4. Owner retains executive visibility across all shipments.
