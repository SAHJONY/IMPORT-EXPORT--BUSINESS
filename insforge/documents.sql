-- SAHJONY Global Trade governed document movement
-- File bytes live in private InsForge Storage. Application code derives object keys and issues short-lived signed URLs.

create table if not exists trade_documents (
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
  supersedes_document_id text references trade_documents(document_id),
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

create table if not exists document_movements (
  id bigserial primary key,
  event_id text not null unique,
  document_id text not null references trade_documents(document_id),
  actor_role text not null check (actor_role in ('owner','employee','customer','system')),
  actor_id text not null,
  from_status text,
  to_status text not null,
  note text,
  created_at timestamptz not null default now()
);

create table if not exists document_storage_events (
  id bigserial primary key,
  storage_event_id text not null unique,
  document_id text not null references trade_documents(document_id),
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

create index if not exists idx_trade_documents_case on trade_documents(trade_case_id, updated_at desc);
create index if not exists idx_trade_documents_customer on trade_documents(customer_id, updated_at desc);
create index if not exists idx_trade_documents_status on trade_documents(status, updated_at desc);
create index if not exists idx_trade_documents_storage_status on trade_documents(storage_status, updated_at desc);
create index if not exists idx_document_movements_doc on document_movements(document_id, created_at asc);
create index if not exists idx_document_storage_events_doc on document_storage_events(document_id, created_at asc);

-- Append-only audit: movement/storage event history must not be updated or deleted.
create or replace function reject_document_audit_mutation() returns trigger language plpgsql as $$
begin
  raise exception 'document audit tables are append-only';
end;
$$;

drop trigger if exists document_movements_append_only on document_movements;
create trigger document_movements_append_only before update or delete on document_movements
for each row execute function reject_document_audit_mutation();

drop trigger if exists document_storage_events_append_only on document_storage_events;
create trigger document_storage_events_append_only before update or delete on document_storage_events
for each row execute function reject_document_audit_mutation();

comment on table trade_documents is 'Governed trade-document metadata. Object keys are server-derived; raw storage credentials never reach clients.';
comment on table document_movements is 'Append-only document lifecycle audit.';
comment on table document_storage_events is 'Append-only upload/download/scan/retention/legal-hold audit.';
