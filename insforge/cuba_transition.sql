-- SAHJONY Global Trade · Cuba transition-to-ready governance
-- This schema manages a future lawful transition of the real CU jurisdiction from LIVE/LIMITED to LIVE/READY.
-- It does not remove or override sanctions, embargoes, export controls, customs rules, banking restrictions, or licensing requirements.

create table if not exists cuba_transition_evidence (
  id bigserial primary key,
  evidence_id text not null unique,
  authority text not null,
  legal_instrument text not null,
  reference_url text,
  effective_date date,
  evidence_status text not null default 'PENDING' check (evidence_status in ('PENDING','VERIFIED','REJECTED','SUPERSEDED')),
  change_type text not null check (change_type in ('OFAC_CACR','EXECUTIVE_ORDER','STATUTE','BIS_PART_746','STATE_RESTRICTED_LIST','BANKING','CUSTOMS','OTHER')),
  removes_restriction boolean not null default false,
  scope_summary text not null,
  verified_by text,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_transition_gates (
  id bigserial primary key,
  gate_key text not null unique,
  gate_label text not null,
  status text not null default 'BLOCKED' check (status in ('READY','LIMITED','BLOCKED','NOT_APPLICABLE')),
  required boolean not null default true,
  evidence_summary text,
  evidence_ids jsonb not null default '[]'::jsonb,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cuba_transition_events (
  id bigserial primary key,
  event_id text not null unique,
  event_type text not null,
  actor_id text not null,
  prior_status text,
  new_status text,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists cuba_transition_state (
  singleton_key text primary key default 'CU',
  country_code text not null default 'CU',
  current_operating_status text not null default 'LIMITED' check (current_operating_status in ('READY','LIMITED','BLOCKED')),
  transition_candidate boolean not null default false,
  owner_approved boolean not null default false,
  owner_approved_at timestamptz,
  last_evaluated_at timestamptz,
  last_evaluation_summary text,
  updated_at timestamptz not null default now()
);

insert into cuba_transition_state (singleton_key,country_code,current_operating_status)
values ('CU','CU','LIMITED')
on conflict (singleton_key) do nothing;

-- Required transition gates. All required gates must be READY before CU can be promoted to LIVE/READY.
insert into cuba_transition_gates (gate_key,gate_label,required) values
  ('ofac_cacr_status','OFAC Cuban Assets Control Regulations status',true),
  ('statutory_embargo_status','Statutory embargo / governing statutes status',true),
  ('executive_sanctions_status','Cuba-related executive sanctions status',true),
  ('bis_part_746_status','BIS Part 746 Cuba special controls status',true),
  ('restricted_party_framework','Cuba-specific restricted-party framework status',true),
  ('banking_settlement_normalized','Banking and settlement availability normalized',true),
  ('customs_trade_normalized','Customs and trade procedures normalized',true),
  ('carrier_insurance_normalized','Carrier and insurance market access normalized',true),
  ('country_controls_reverified','All 16 CU country controls reverified under new law',true),
  ('corridor_controls_reverified','Required live CU corridors reverified',true),
  ('legal_effective_dates_passed','All relied-upon legal changes are effective',true),
  ('production_safety_test','CU transition E2E and rollback safety test passed',true)
on conflict (gate_key) do nothing;

create index if not exists idx_cuba_transition_evidence_status on cuba_transition_evidence(evidence_status, change_type);
create index if not exists idx_cuba_transition_events_created on cuba_transition_events(created_at desc);
