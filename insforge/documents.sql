-- SAHJONY Global Trade governed document movement
create table if not exists trade_documents (
  id bigserial primary key,
  document_id text not null unique,
  trade_case_id text not null,
  customer_id text,
  document_type text not null,
  title text not null,
  storage_object_key text,
  version integer not null default 1,
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
  document_id text not null,
  actor_role text not null check (actor_role in ('owner','employee','customer')),
  actor_id text not null,
  from_status text,
  to_status text not null,
  note text,
  created_at timestamptz not null default now()
);

create index if not exists idx_trade_documents_case on trade_documents(trade_case_id, updated_at desc);
create index if not exists idx_trade_documents_customer on trade_documents(customer_id, updated_at desc);
create index if not exists idx_trade_documents_status on trade_documents(status, updated_at desc);
create index if not exists idx_document_movements_doc on document_movements(document_id, created_at asc);

-- File bytes should live in private InsForge Storage. Store only the private object key here.
-- Before customer document downloads are enabled, enforce authenticated tenant-scoped storage access/RLS.
