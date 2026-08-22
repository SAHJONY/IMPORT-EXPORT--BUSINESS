-- SAHJONY Global Trade unified business communications hub
-- Apply after communications.sql and documents.sql.

create table if not exists business_events (
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

create table if not exists communication_preferences (
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

create table if not exists outbound_notifications (
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

create index if not exists idx_business_events_case on business_events(trade_case_id, created_at desc);
create index if not exists idx_business_events_customer on business_events(customer_id, created_at desc);
create index if not exists idx_business_events_visibility on business_events(visibility, created_at desc);
create index if not exists idx_business_events_action on business_events(action_required, event_status, created_at desc);
create index if not exists idx_outbound_notifications_recipient on outbound_notifications(recipient_role, recipient_id, created_at desc);
create index if not exists idx_outbound_notifications_status on outbound_notifications(delivery_status, created_at asc);

-- Portal delivery is native. External channels remain fail-closed until a provider
-- is explicitly configured and the destination is consented/verified.
-- Add InsForge Auth/RLS policies before exposing browser-direct database access.