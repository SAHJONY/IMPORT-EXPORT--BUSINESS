-- SAHJONY Global Trade tri-role communications
-- Apply in InsForge database before enabling production messaging.

create table if not exists communications (
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

create index if not exists idx_communications_thread on communications(thread_id, created_at desc);
create index if not exists idx_communications_customer on communications(customer_id, created_at desc);
create index if not exists idx_communications_case on communications(trade_case_id, created_at desc);
create index if not exists idx_communications_recipient on communications(recipient_role, recipient_id, created_at desc);

-- The trusted server API enforces role routing today.
-- When browser-facing InsForge Auth is enabled, add RLS policies that bind
-- customer_id to the authenticated user's tenant/participant identity and
-- staff visibility to approved employee roles only.
