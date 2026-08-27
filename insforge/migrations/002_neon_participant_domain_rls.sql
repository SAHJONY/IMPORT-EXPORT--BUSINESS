-- SAHJONY Global Trade
-- Migration 002: participant-facing domain schema + Neon Auth/Data API RLS.
--
-- IMPORTANT:
-- - This file is an explicit migration artifact. It is NOT executed by /activation/health.
-- - Apply through a Neon temporary branch first, verify, then promote with migration approval.
-- - The migration fails closed unless Neon Data API has provisioned the `authenticated`
--   role and auth.user_id().
-- - Trusted backend/database-owner operations are intentionally separate from browser Data API access.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    RAISE EXCEPTION 'Neon Data API role authenticated is not provisioned';
  END IF;
  IF to_regprocedure('auth.user_id()') IS NULL THEN
    RAISE EXCEPTION 'Neon Data API auth.user_id() is not provisioned';
  END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- Communications
-- ---------------------------------------------------------------------------
create table if not exists public.communications (
  id bigserial primary key,
  message_id text not null unique,
  thread_id text not null,
  sender_role text not null check (sender_role in ('owner','employee','customer')),
  sender_id text not null,
  recipient_role text not null check (recipient_role in ('owner','employee','customer')),
  recipient_id text,
  customer_id text,
  trade_case_id text,
  subject text not null,
  body text not null,
  priority text not null default 'normal' check (priority in ('normal','high','urgent')),
  status text not null default 'sent' check (status in ('sent','read','resolved')),
  escalation_requested boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_communications_thread on public.communications(thread_id, created_at desc);
create index if not exists idx_communications_customer on public.communications(customer_id, created_at desc);
create index if not exists idx_communications_case on public.communications(trade_case_id, created_at desc);
create index if not exists idx_communications_recipient on public.communications(recipient_role, recipient_id, created_at desc);

create table if not exists public.business_events (
  id bigserial primary key,
  event_id text not null unique,
  event_type text not null check (event_type in ('message','document','shipment','payment','compliance','approval','task','system')),
  source_type text not null,
  source_id text,
  trade_case_id text,
  customer_id text,
  actor_role text not null check (actor_role in ('owner','employee','customer','system')),
  actor_id text not null,
  visibility text not null default 'internal' check (visibility in ('owner','internal','customer')),
  title text not null,
  summary text,
  action_required boolean not null default false,
  action_label text,
  priority text not null default 'normal' check (priority in ('normal','high','urgent')),
  event_status text not null default 'open' check (event_status in ('open','acknowledged','resolved')),
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_preferences (
  id bigserial primary key,
  participant_role text not null check (participant_role in ('owner','employee','customer')),
  participant_id text not null,
  portal_enabled boolean not null default true,
  email_enabled boolean not null default false,
  sms_enabled boolean not null default false,
  whatsapp_enabled boolean not null default false,
  urgent_only_external boolean not null default false,
  email_address text,
  phone_e164 text,
  locale text not null default 'en',
  timezone text not null default 'America/Chicago',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(participant_role, participant_id)
);

create table if not exists public.outbound_notifications (
  id bigserial primary key,
  notification_id text not null unique,
  event_id text not null,
  recipient_role text not null check (recipient_role in ('owner','employee','customer')),
  recipient_id text not null,
  channel text not null check (channel in ('portal','email','sms','whatsapp')),
  destination text,
  subject text,
  body text not null,
  delivery_status text not null default 'queued' check (delivery_status in ('queued','suppressed','sent','delivered','failed')),
  provider text,
  provider_message_id text,
  attempts integer not null default 0,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_business_events_case on public.business_events(trade_case_id, created_at desc);
create index if not exists idx_business_events_customer on public.business_events(customer_id, created_at desc);
create index if not exists idx_business_events_visibility on public.business_events(visibility, created_at desc);
create index if not exists idx_business_events_action on public.business_events(action_required, event_status, created_at desc);
create index if not exists idx_outbound_notifications_recipient on public.outbound_notifications(recipient_role, recipient_id, created_at desc);
create index if not exists idx_outbound_notifications_status on public.outbound_notifications(delivery_status, created_at asc);

-- ---------------------------------------------------------------------------
-- Governed documents
-- ---------------------------------------------------------------------------
create table if not exists public.trade_documents (
  id bigserial primary key,
  document_id text not null unique,
  trade_case_id text not null,
  customer_id text,
  document_type text not null,
  title text not null,
  original_filename text,
  storage_object_key text,
  content_type text,
  size_bytes bigint,
  object_etag text,
  checksum_sha256 text,
  version integer not null default 1 check (version >= 1),
  supersedes_document_id text references public.trade_documents(document_id),
  storage_status text not null default 'metadata_only' check (storage_status in ('metadata_only','upload_authorized','uploaded','scan_pending','clean','quarantined','rejected')),
  malware_scan_status text not null default 'not_started' check (malware_scan_status in ('not_started','pending','clean','infected','error','waived')),
  malware_scan_provider text,
  malware_scan_reference text,
  retention_until timestamptz,
  legal_hold boolean not null default false,
  status text not null check (status in ('requested','customer_submitted','employee_review','correction_requested','owner_review','approved','released','rejected','archived')),
  customer_visible boolean not null default false,
  created_by_role text not null check (created_by_role in ('owner','employee','customer')),
  created_by_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.document_movements (
  id bigserial primary key,
  event_id text not null unique,
  document_id text not null references public.trade_documents(document_id),
  actor_role text not null check (actor_role in ('owner','employee','customer','system')),
  actor_id text not null,
  from_status text,
  to_status text not null,
  note text,
  created_at timestamptz not null default now()
);

create table if not exists public.document_storage_events (
  id bigserial primary key,
  storage_event_id text not null unique,
  document_id text not null references public.trade_documents(document_id),
  event_type text not null check (event_type in ('upload_authorized','upload_verified','download_authorized','scan_requested','scan_result','quarantined','retention_changed','legal_hold_changed')),
  actor_role text not null,
  actor_id text not null,
  object_key text,
  content_type text,
  size_bytes bigint,
  object_etag text,
  detail text,
  created_at timestamptz not null default now()
);
create index if not exists idx_trade_documents_case on public.trade_documents(trade_case_id, updated_at desc);
create index if not exists idx_trade_documents_customer on public.trade_documents(customer_id, updated_at desc);
create index if not exists idx_trade_documents_status on public.trade_documents(status, updated_at desc);
create index if not exists idx_trade_documents_storage_status on public.trade_documents(storage_status, updated_at desc);
create index if not exists idx_document_movements_doc on public.document_movements(document_id, created_at asc);
create index if not exists idx_document_storage_events_doc on public.document_storage_events(document_id, created_at asc);

create or replace function public.reject_document_audit_mutation() returns trigger
language plpgsql
as $$
begin
  raise exception 'document audit tables are append-only';
end;
$$;

drop trigger if exists document_movements_append_only on public.document_movements;
create trigger document_movements_append_only
before update or delete on public.document_movements
for each row execute function public.reject_document_audit_mutation();

drop trigger if exists document_storage_events_append_only on public.document_storage_events;
create trigger document_storage_events_append_only
before update or delete on public.document_storage_events
for each row execute function public.reject_document_audit_mutation();

-- ---------------------------------------------------------------------------
-- Shipment tracking
-- ---------------------------------------------------------------------------
create table if not exists public.shipments (
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

create table if not exists public.shipment_milestones (
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

create table if not exists public.shipment_sync_events (
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
create index if not exists idx_shipments_case on public.shipments(trade_case_id, updated_at desc);
create index if not exists idx_shipments_customer on public.shipments(customer_id, updated_at desc);
create index if not exists idx_shipments_tracking on public.shipments(provider, tracking_reference);
create index if not exists idx_shipments_stage on public.shipments(current_stage, current_status, updated_at desc);
create index if not exists idx_milestones_shipment on public.shipment_milestones(shipment_id, event_time asc, created_at asc);
create index if not exists idx_sync_shipment on public.shipment_sync_events(shipment_id, synced_at desc);

-- ---------------------------------------------------------------------------
-- Compliance control plane
-- ---------------------------------------------------------------------------
create table if not exists public.trade_compliance_cases (
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

create table if not exists public.compliance_requirements (
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

create table if not exists public.compliance_screenings (
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

create table if not exists public.regulatory_determinations (
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

create table if not exists public.compliance_audit_events (
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
create index if not exists idx_trade_compliance_case on public.trade_compliance_cases(trade_case_id, updated_at desc);
create index if not exists idx_trade_compliance_customer on public.trade_compliance_cases(customer_id, updated_at desc);
create index if not exists idx_compliance_requirements_case on public.compliance_requirements(compliance_id, status, category);
create index if not exists idx_compliance_screenings_case on public.compliance_screenings(compliance_id, screened_at desc);
create index if not exists idx_regulatory_determinations_case on public.regulatory_determinations(compliance_id, created_at desc);
create index if not exists idx_compliance_audit_case on public.compliance_audit_events(compliance_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Neon Auth membership boundary
-- ---------------------------------------------------------------------------
create table if not exists public.app_memberships (
  id bigserial primary key,
  membership_id text not null unique,
  user_id text not null,
  role text not null check (role in ('owner','employee','customer')),
  customer_id text,
  employee_id text,
  status text not null default 'active' check (status in ('active','suspended','revoked')),
  mfa_required boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((role='customer' and customer_id is not null) or role<>'customer')
);
create unique index if not exists app_memberships_user_role_scope_idx
  on public.app_memberships(user_id, role, coalesce(customer_id,''), coalesce(employee_id,''));

create or replace function public.requesting_user_id() returns text
language sql stable
as $$
  select nullif(auth.user_id()::text, '');
$$;

create or replace function public.app_has_role(required_role text) returns boolean
language sql stable security definer
set search_path = public, pg_catalog
as $$
  select exists (
    select 1 from public.app_memberships m
    where m.user_id = public.requesting_user_id()
      and m.role = required_role
      and m.status = 'active'
  );
$$;

create or replace function public.app_can_access_customer(target_customer_id text) returns boolean
language sql stable security definer
set search_path = public, pg_catalog
as $$
  select public.app_has_role('owner')
      or public.app_has_role('employee')
      or exists (
        select 1 from public.app_memberships m
        where m.user_id = public.requesting_user_id()
          and m.role='customer'
          and m.status='active'
          and m.customer_id=target_customer_id
      );
$$;

create or replace function public.app_is_internal() returns boolean
language sql stable
as $$
  select public.app_has_role('owner') or public.app_has_role('employee');
$$;

-- ---------------------------------------------------------------------------
-- Least-privilege browser/Data API grants
-- ---------------------------------------------------------------------------
grant usage on schema public to authenticated;

revoke insert, update, delete on public.app_memberships from authenticated;
grant select on public.app_memberships to authenticated;

revoke update, delete on public.trade_documents from authenticated;
grant select, insert on public.trade_documents to authenticated;
grant usage, select on sequence public.trade_documents_id_seq to authenticated;

revoke insert, update, delete on public.document_movements from authenticated;
grant select on public.document_movements to authenticated;

revoke insert, update, delete on public.shipments from authenticated;
grant select on public.shipments to authenticated;

revoke insert, update, delete on public.shipment_milestones from authenticated;
grant select on public.shipment_milestones to authenticated;

revoke insert, update, delete on public.trade_compliance_cases from authenticated;
grant select on public.trade_compliance_cases to authenticated;

revoke insert, update, delete on public.business_events from authenticated;
grant select on public.business_events to authenticated;

revoke insert, update, delete on public.communications from authenticated;
grant select on public.communications to authenticated;

-- ---------------------------------------------------------------------------
-- Row-level security policies
-- ---------------------------------------------------------------------------
alter table public.app_memberships enable row level security;
drop policy if exists app_memberships_self_select on public.app_memberships;
create policy app_memberships_self_select on public.app_memberships
for select to authenticated
using (user_id = public.requesting_user_id());

alter table public.trade_documents enable row level security;
drop policy if exists trade_documents_read on public.trade_documents;
create policy trade_documents_read on public.trade_documents
for select to authenticated
using (public.app_is_internal() or (customer_visible=true and public.app_can_access_customer(customer_id)));

drop policy if exists trade_documents_customer_insert on public.trade_documents;
create policy trade_documents_customer_insert on public.trade_documents
for insert to authenticated
with check (
  public.app_is_internal()
  or (
    created_by_role='customer'
    and created_by_id=public.requesting_user_id()
    and public.app_can_access_customer(customer_id)
  )
);

alter table public.document_movements enable row level security;
drop policy if exists document_movements_read on public.document_movements;
create policy document_movements_read on public.document_movements
for select to authenticated
using (exists (
  select 1 from public.trade_documents d
  where d.document_id=public.document_movements.document_id
    and (public.app_is_internal() or (d.customer_visible=true and public.app_can_access_customer(d.customer_id)))
));

alter table public.shipments enable row level security;
drop policy if exists shipments_read on public.shipments;
create policy shipments_read on public.shipments
for select to authenticated
using (public.app_is_internal() or (customer_visible=true and public.app_can_access_customer(customer_id)));

alter table public.shipment_milestones enable row level security;
drop policy if exists shipment_milestones_read on public.shipment_milestones;
create policy shipment_milestones_read on public.shipment_milestones
for select to authenticated
using (exists (
  select 1 from public.shipments s
  where s.shipment_id=public.shipment_milestones.shipment_id
    and (public.app_is_internal() or (s.customer_visible=true and public.app_can_access_customer(s.customer_id)))
));

alter table public.trade_compliance_cases enable row level security;
drop policy if exists compliance_cases_read on public.trade_compliance_cases;
create policy compliance_cases_read on public.trade_compliance_cases
for select to authenticated
using (public.app_is_internal() or (customer_visible=true and public.app_can_access_customer(customer_id)));

alter table public.business_events enable row level security;
drop policy if exists business_events_read on public.business_events;
create policy business_events_read on public.business_events
for select to authenticated
using (
  public.app_has_role('owner')
  or (public.app_has_role('employee') and visibility in ('internal','customer'))
  or (visibility='customer' and public.app_can_access_customer(customer_id))
);

alter table public.communications enable row level security;
drop policy if exists communications_read on public.communications;
create policy communications_read on public.communications
for select to authenticated
using (public.app_is_internal() or public.app_can_access_customer(customer_id));

comment on table public.app_memberships is
  'Maps verified Neon Auth JWT subject (sub) to application roles and tenant/customer scope. Browser-supplied role or customer identifiers are never trusted as authorization evidence.';

comment on table public.trade_documents is
  'Governed trade-document metadata. Object keys are server-derived; raw storage credentials never reach clients.';
comment on table public.document_movements is 'Append-only document lifecycle audit.';
comment on table public.document_storage_events is 'Append-only upload/download/scan/retention/legal-hold audit.';
