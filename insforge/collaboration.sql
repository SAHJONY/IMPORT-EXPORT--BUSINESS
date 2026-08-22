-- Governed external collaboration and scoped sharing for SAHJONY Global Trade.
-- Grants are revocable, expiring and least-privilege. Raw access tokens are never stored.

create table if not exists collaboration_participants (
  id bigserial primary key,
  participant_id text not null unique,
  participant_type text not null check (participant_type in (
    'customer','buyer','supplier','customs_broker','freight_forwarder','carrier','inspector','warehouse_3pl',
    'insurer','bank_finance','attorney','accountant','government_agency','agent','consultant','other'
  )),
  legal_name text,
  contact_name text,
  email text,
  phone_e164 text,
  company_name text,
  preferred_locale text default 'en-US',
  verification_status text not null default 'pending' check (verification_status in ('pending','verified','rejected','suspended')),
  created_by_role text not null,
  created_by_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists collaboration_grants (
  id bigserial primary key,
  grant_id text not null unique,
  participant_id text references collaboration_participants(participant_id),
  trade_case_id text,
  scope_modules text[] not null default '{}',
  permissions text[] not null default '{view}',
  allowed_resource_ids text[] not null default '{}',
  customer_id text,
  recipient_email text,
  token_hash text not null unique,
  token_hint text,
  preferred_locale text default 'en-US',
  allow_download boolean not null default false,
  allow_upload boolean not null default false,
  allow_comment boolean not null default true,
  allow_reshare boolean not null default false,
  require_verified_identity boolean not null default true,
  max_uses integer,
  use_count integer not null default 0,
  expires_at timestamptz not null,
  status text not null default 'active' check (status in ('active','revoked','expired','exhausted')),
  created_by_role text not null,
  created_by_id text not null,
  created_at timestamptz not null default now(),
  revoked_at timestamptz,
  revoked_by_role text,
  revoked_by_id text
);
create index if not exists collaboration_grants_case_idx on collaboration_grants(trade_case_id);
create index if not exists collaboration_grants_participant_idx on collaboration_grants(participant_id);
create index if not exists collaboration_grants_status_idx on collaboration_grants(status, expires_at);

create table if not exists collaboration_shared_items (
  id bigserial primary key,
  item_id text not null unique,
  grant_id text not null references collaboration_grants(grant_id) on delete cascade,
  module text not null,
  resource_type text not null,
  resource_id text,
  title text not null,
  summary text,
  payload jsonb not null default '{}'::jsonb,
  source_locale text default 'en-US',
  legal_or_regulatory boolean not null default false,
  created_by_role text not null,
  created_by_id text not null,
  created_at timestamptz not null default now()
);
create index if not exists collaboration_shared_items_grant_idx on collaboration_shared_items(grant_id, created_at);

create table if not exists collaboration_access_events (
  id bigserial primary key,
  event_id text not null unique,
  grant_id text not null references collaboration_grants(grant_id),
  participant_id text,
  action text not null,
  resource_type text,
  resource_id text,
  outcome text not null check (outcome in ('allowed','denied','revoked','expired')),
  ip_hash text,
  user_agent_hash text,
  detail text,
  created_at timestamptz not null default now()
);
create index if not exists collaboration_access_grant_idx on collaboration_access_events(grant_id, created_at desc);

create table if not exists collaboration_comments (
  id bigserial primary key,
  comment_id text not null unique,
  grant_id text not null references collaboration_grants(grant_id),
  trade_case_id text,
  participant_id text,
  resource_type text,
  resource_id text,
  body text not null,
  source_locale text,
  created_at timestamptz not null default now()
);
create index if not exists collaboration_comments_case_idx on collaboration_comments(trade_case_id, created_at desc);

comment on table collaboration_grants is 'Least-privilege participant sharing grants. Store only SHA-256 token hashes; never persist raw bearer tokens.';
comment on table collaboration_shared_items is 'Curated share-safe snapshots. Never mirror raw internal tables into external grants.';
comment on table collaboration_access_events is 'Append-only audit of participant share access, denials, expiration and revocation.';
