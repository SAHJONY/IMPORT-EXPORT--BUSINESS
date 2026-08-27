-- SAHJONY Global Trade
-- Migration 005: Agentic Communication OS core.
--
-- Explicit migration artifact only. Apply to a Neon temporary branch first.
-- The communication agent may automate research, routing, notes and follow-ups,
-- but cannot obtain authority to bind price, contracts, payments, banking,
-- financing, KYC/sanctions/export-control decisions, or legal admissions.

create table if not exists public.communication_contacts (
  id bigserial primary key,
  contact_id text not null unique,
  display_name text not null,
  company text,
  title text,
  country_code text,
  preferred_language text not null default 'auto',
  timezone text,
  lead_id text,
  customer_id text,
  supplier_id text,
  trade_case_id text,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','INACTIVE','DO_NOT_CONTACT','ARCHIVED')),
  notes text,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_contact_endpoints (
  id bigserial primary key,
  endpoint_id text not null unique,
  contact_id text not null references public.communication_contacts(contact_id) on delete cascade,
  channel text not null check (channel in ('browser','phone','whatsapp','sms','email','portal')),
  destination text not null,
  normalized_destination text,
  label text,
  preferred boolean not null default false,
  verified boolean not null default false,
  verification_source text,
  verified_at timestamptz,
  consent_status text not null default 'UNKNOWN' check (consent_status in ('UNKNOWN','CONSENTED','TRANSACTIONAL_ONLY','REVOKED','DO_NOT_CONTACT')),
  consent_source text,
  consented_at timestamptz,
  revoked_at timestamptz,
  last_success_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(contact_id, channel, destination)
);

create table if not exists public.communication_missions (
  id bigserial primary key,
  mission_id text not null unique,
  contact_id text references public.communication_contacts(contact_id) on delete set null,
  conversation_id text,
  trade_case_id text,
  objective text not null,
  success_criteria text,
  status text not null default 'DRAFT' check (status in ('DRAFT','READY','RUNNING','WAITING_HUMAN','HOLD','COMPLETED','CANCELLED')),
  priority text not null default 'normal' check (priority in ('urgent','high','normal','low')),
  autonomy_mode text not null default 'ASSIST' check (autonomy_mode in ('ADVISORY','ASSIST','AUTONOMOUS_NONBINDING')),
  allowed_channels jsonb not null default '[]'::jsonb,
  max_outbound_attempts integer not null default 3 check (max_outbound_attempts between 0 and 20),
  binding_actions_allowed boolean not null default false check (binding_actions_allowed = false),
  owner_approved boolean not null default false,
  approved_at timestamptz,
  next_action_at timestamptz,
  created_by text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_action_queue (
  id bigserial primary key,
  action_id text not null unique,
  mission_id text references public.communication_missions(mission_id) on delete cascade,
  contact_id text references public.communication_contacts(contact_id) on delete set null,
  conversation_id text,
  trade_case_id text,
  action_type text not null check (action_type in ('CALL_INVITE','PRIVATE_ROOM_INVITE','AI_ROOM_INVITE','EMAIL_DRAFT','WHATSAPP_DRAFT','SMS_DRAFT','PORTAL_MESSAGE','FOLLOW_UP_TASK','HUMAN_HANDOFF','INTERNAL_NOTE')),
  channel text,
  destination text,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'QUEUED' check (status in ('QUEUED','WAITING_APPROVAL','APPROVED','DISPATCHED','COMPLETED','FAILED','CANCELLED','HOLD')),
  requires_owner_approval boolean not null default false,
  owner_approved boolean not null default false,
  approved_by text,
  approved_at timestamptz,
  attempt_count integer not null default 0,
  scheduled_at timestamptz,
  completed_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_agent_notes (
  id bigserial primary key,
  note_id text not null unique,
  contact_id text references public.communication_contacts(contact_id) on delete set null,
  conversation_id text,
  room_id text,
  trade_case_id text,
  note_type text not null check (note_type in ('SUMMARY','FOLLOW_UP','QUALIFICATION','RISK','HANDOFF','CUSTOMER_REQUEST','SUPPLIER_REQUEST')),
  content text not null,
  source text not null default 'agentic_communication_os',
  contains_recording boolean not null default false check (contains_recording = false),
  created_at timestamptz not null default now()
);

create index if not exists idx_comm_contacts_company on public.communication_contacts(company, updated_at desc);
create index if not exists idx_comm_contacts_case on public.communication_contacts(trade_case_id, updated_at desc);
create index if not exists idx_comm_endpoints_contact on public.communication_contact_endpoints(contact_id, preferred desc, channel);
create index if not exists idx_comm_endpoints_consent on public.communication_contact_endpoints(consent_status, channel, updated_at desc);
create index if not exists idx_comm_missions_status on public.communication_missions(status, priority, next_action_at);
create index if not exists idx_comm_actions_status on public.communication_action_queue(status, scheduled_at, created_at);
create index if not exists idx_comm_notes_contact on public.communication_agent_notes(contact_id, created_at desc);

comment on table public.communication_contacts is 'Contact 360 directory for buyers, suppliers, customers, partners and other business counterparties.';
comment on table public.communication_contact_endpoints is 'Per-channel destinations with verification and consent state. Unknown/revoked consent must not be treated as marketing permission.';
comment on table public.communication_missions is 'Agentic communication objectives. binding_actions_allowed is structurally false.';
comment on table public.communication_action_queue is 'Governed communication actions; provider dispatch remains separate and approval-aware.';
