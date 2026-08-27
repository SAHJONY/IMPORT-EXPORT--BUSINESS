-- SAHJONY Communications Platform
-- Migration 006: industry-agnostic workspace, context, policy and capability layer.
--
-- IMPORTANT:
-- - Explicit migration artifact only; never execute from a health endpoint.
-- - Apply after migrations 004 and 005 on a Neon temporary branch first.
-- - Global Trade remains a first-party Industry Pack; the communication core no longer
--   depends on trade-specific nouns for identity, routing, missions or governance.
-- - Existing trade_case_id / supplier_id / lead_id columns remain compatibility fields.

create table if not exists public.communication_industry_packs (
  id bigserial primary key,
  pack_id text not null unique,
  name text not null,
  version text not null default '1.0.0',
  description text,
  context_nouns jsonb not null default '[]'::jsonb,
  restricted_actions jsonb not null default '[]'::jsonb,
  approval_actions jsonb not null default '[]'::jsonb,
  tool_allowlist jsonb not null default '[]'::jsonb,
  system_instructions text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_workspaces (
  id bigserial primary key,
  workspace_id text not null unique,
  name text not null,
  slug text not null unique,
  brand_name text not null default 'SAHJONY',
  industry_pack_id text not null references public.communication_industry_packs(pack_id) on delete restrict,
  default_language text not null default 'auto',
  timezone text,
  status text not null default 'ACTIVE' check (status in ('ACTIVE','SUSPENDED','ARCHIVED')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_contexts (
  id bigserial primary key,
  context_id text not null unique,
  workspace_id text not null references public.communication_workspaces(workspace_id) on delete cascade,
  context_type text not null,
  external_id text,
  display_name text,
  status text not null default 'OPEN' check (status in ('OPEN','ACTIVE','HOLD','CLOSED','ARCHIVED')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id, context_type, external_id)
);

create table if not exists public.communication_contact_contexts (
  id bigserial primary key,
  link_id text not null unique,
  workspace_id text not null references public.communication_workspaces(workspace_id) on delete cascade,
  contact_id text not null references public.communication_contacts(contact_id) on delete cascade,
  context_id text not null references public.communication_contexts(context_id) on delete cascade,
  relationship_role text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(contact_id, context_id, relationship_role)
);

create table if not exists public.communication_capabilities (
  id bigserial primary key,
  capability_key text not null unique,
  display_name text not null,
  risk_tier text not null check (risk_tier in ('READ','INTERNAL_WRITE','EXTERNAL_NONBINDING','BINDING','REGULATED')),
  description text,
  default_enabled boolean not null default false,
  default_requires_human_approval boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.communication_workspace_capabilities (
  id bigserial primary key,
  workspace_id text not null references public.communication_workspaces(workspace_id) on delete cascade,
  capability_key text not null references public.communication_capabilities(capability_key) on delete cascade,
  enabled boolean not null default false,
  requires_human_approval boolean not null default true,
  policy_note text,
  updated_at timestamptz not null default now(),
  unique(workspace_id, capability_key)
);

create table if not exists public.communication_policy_events (
  id bigserial primary key,
  event_id text not null unique,
  workspace_id text not null references public.communication_workspaces(workspace_id) on delete cascade,
  contact_id text,
  context_id text,
  mission_id text,
  capability_key text,
  decision text not null check (decision in ('ALLOW','REQUIRE_APPROVAL','DENY','HOLD')),
  reason text not null,
  actor_type text not null default 'system',
  actor_id text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

insert into public.communication_industry_packs (
  pack_id,name,version,description,context_nouns,restricted_actions,approval_actions,tool_allowlist,system_instructions,active
) values (
  'pack_general','General Business','1.0.0',
  'Industry-neutral communication policy pack for general business workflows.',
  '["account","case","deal","matter","order","project","ticket","appointment","opportunity","custom"]'::jsonb,
  '["move_funds","change_bank_details","sign_contract","make_legal_admission","approve_regulated_status"]'::jsonb,
  '["send_external_message","place_outbound_call","schedule_external_meeting","share_document"]'::jsonb,
  '["get_contact_context","get_business_context","route_contact","create_follow_up","record_note","request_human_handoff"]'::jsonb,
  'Operate as an industry-neutral communication assistant. Preserve verified facts, honor consent, do not invent authority, and escalate binding or regulated decisions.',
  true
) on conflict (pack_id) do update set
  name=excluded.name, version=excluded.version, description=excluded.description,
  context_nouns=excluded.context_nouns, restricted_actions=excluded.restricted_actions,
  approval_actions=excluded.approval_actions, tool_allowlist=excluded.tool_allowlist,
  system_instructions=excluded.system_instructions, active=true, updated_at=now();

insert into public.communication_industry_packs (
  pack_id,name,version,description,context_nouns,restricted_actions,approval_actions,tool_allowlist,system_instructions,active
) values (
  'pack_global_trade','Global Trade','1.0.0',
  'SAHJONY Global Trade adapter with trade-specific safety and execution boundaries.',
  '["lead","buyer","supplier","rfq","trade_case","shipment","payment","compliance_case"]'::jsonb,
  '["accept_price","sign_contract","move_funds","change_bank_details","approve_financing","approve_kyc","approve_sanctions","approve_export_control","make_legal_admission"]'::jsonb,
  '["send_external_message","place_outbound_call","share_trade_document","schedule_external_meeting"]'::jsonb,
  '["get_contact_context","get_business_context","get_trade_context","route_contact","create_follow_up","record_note","request_human_handoff"]'::jsonb,
  'Use Global Trade context when present. Never authorize price acceptance, contracts, payments, bank changes, financing, KYC, sanctions, export-control decisions, legal admissions, or regulatory conclusions.',
  true
) on conflict (pack_id) do update set
  name=excluded.name, version=excluded.version, description=excluded.description,
  context_nouns=excluded.context_nouns, restricted_actions=excluded.restricted_actions,
  approval_actions=excluded.approval_actions, tool_allowlist=excluded.tool_allowlist,
  system_instructions=excluded.system_instructions, active=true, updated_at=now();

insert into public.communication_workspaces (
  workspace_id,name,slug,brand_name,industry_pack_id,default_language,timezone,status,metadata
) values (
  'ws_sahjony_global_trade','SAHJONY Global Trade','sahjony-global-trade','SAHJONY LLC.','pack_global_trade','auto','America/Chicago','ACTIVE',
  '{"adapter":"global_trade","legacy_compatibility":true}'::jsonb
) on conflict (workspace_id) do update set
  name=excluded.name, slug=excluded.slug, brand_name=excluded.brand_name,
  industry_pack_id=excluded.industry_pack_id, status='ACTIVE', metadata=excluded.metadata, updated_at=now();

insert into public.communication_capabilities (capability_key,display_name,risk_tier,description,default_enabled,default_requires_human_approval) values
  ('read_contact_context','Read contact context','READ','Read approved contact and relationship context.',true,false),
  ('read_business_context','Read business context','READ','Read workspace-scoped generic business context.',true,false),
  ('route_contact','Route contact','READ','Select a consent-compatible communication route without sending.',true,false),
  ('record_internal_note','Record internal note','INTERNAL_WRITE','Store a text-only internal note.',true,false),
  ('create_follow_up','Create follow-up','INTERNAL_WRITE','Queue an internal follow-up task.',true,false),
  ('request_human_handoff','Request human handoff','INTERNAL_WRITE','Escalate to an authorized human.',true,false),
  ('send_external_message','Send external message','EXTERNAL_NONBINDING','Dispatch an externally visible non-binding message.',false,true),
  ('place_outbound_call','Place outbound call','EXTERNAL_NONBINDING','Initiate an outbound call where lawful and consented.',false,true),
  ('share_document','Share document','EXTERNAL_NONBINDING','Share an approved document with an external participant.',false,true),
  ('binding_commitment','Binding commitment','BINDING','Any action that may bind the organization commercially or legally.',false,true),
  ('regulated_decision','Regulated decision','REGULATED','Any regulated, compliance, clinical, financial, legal or similarly controlled decision.',false,true)
on conflict (capability_key) do update set
  display_name=excluded.display_name,risk_tier=excluded.risk_tier,description=excluded.description,
  default_enabled=excluded.default_enabled,default_requires_human_approval=excluded.default_requires_human_approval,updated_at=now();

insert into public.communication_workspace_capabilities (workspace_id,capability_key,enabled,requires_human_approval,policy_note)
select 'ws_sahjony_global_trade', capability_key, default_enabled, default_requires_human_approval,
       case when risk_tier in ('BINDING','REGULATED') then 'Fail closed: governed backend or authorized human only.' else null end
from public.communication_capabilities
on conflict (workspace_id,capability_key) do nothing;

alter table public.communication_contacts add column if not exists workspace_id text;
alter table public.communication_missions add column if not exists workspace_id text;
alter table public.communication_missions add column if not exists context_id text;
alter table public.communication_action_queue add column if not exists workspace_id text;
alter table public.communication_action_queue add column if not exists context_id text;
alter table public.communication_agent_notes add column if not exists workspace_id text;
alter table public.communication_agent_notes add column if not exists context_id text;
alter table public.communication_conversations add column if not exists workspace_id text;
alter table public.communication_rooms add column if not exists workspace_id text;

update public.communication_contacts set workspace_id='ws_sahjony_global_trade' where workspace_id is null;
update public.communication_missions set workspace_id='ws_sahjony_global_trade' where workspace_id is null;
update public.communication_action_queue set workspace_id='ws_sahjony_global_trade' where workspace_id is null;
update public.communication_agent_notes set workspace_id='ws_sahjony_global_trade' where workspace_id is null;
update public.communication_conversations set workspace_id='ws_sahjony_global_trade' where workspace_id is null;
update public.communication_rooms set workspace_id='ws_sahjony_global_trade' where workspace_id is null;

alter table public.communication_contacts alter column workspace_id set default 'ws_sahjony_global_trade';
alter table public.communication_missions alter column workspace_id set default 'ws_sahjony_global_trade';
alter table public.communication_action_queue alter column workspace_id set default 'ws_sahjony_global_trade';
alter table public.communication_agent_notes alter column workspace_id set default 'ws_sahjony_global_trade';
alter table public.communication_conversations alter column workspace_id set default 'ws_sahjony_global_trade';
alter table public.communication_rooms alter column workspace_id set default 'ws_sahjony_global_trade';

create index if not exists idx_comm_contexts_workspace on public.communication_contexts(workspace_id, context_type, updated_at desc);
create index if not exists idx_comm_contact_contexts_contact on public.communication_contact_contexts(contact_id, context_id);
create index if not exists idx_comm_policy_events_workspace on public.communication_policy_events(workspace_id, created_at desc);
create index if not exists idx_comm_contacts_workspace on public.communication_contacts(workspace_id, updated_at desc);
create index if not exists idx_comm_missions_workspace on public.communication_missions(workspace_id, status, updated_at desc);
create index if not exists idx_comm_actions_workspace on public.communication_action_queue(workspace_id, status, created_at desc);

comment on table public.communication_workspaces is 'Industry-agnostic tenant/workspace boundary for SAHJONY Communications Platform.';
comment on table public.communication_industry_packs is 'Pluggable vocabulary, safety policy and tool surface for an industry or operating model.';
comment on table public.communication_contexts is 'Generic business context object; examples include deal, matter, property, order, project, ticket or appointment.';
comment on table public.communication_workspace_capabilities is 'Workspace-scoped tool/capability authority. Binding and regulated actions remain human/governed-backend controlled.';
