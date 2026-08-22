-- SAHJONY governed multi-model AI brain audit and decision-support ledger.
-- AI outputs are advisory. They cannot directly approve payments, compliance,
-- supplier commitments, country activation, shipment release, or legal roles.

create table if not exists ai_brain_runs (
  run_id text primary key,
  actor_role text not null,
  actor_id text not null,
  task_type text not null,
  risk_tier text not null default 'STANDARD',
  routing_mode text not null,
  primary_provider text,
  primary_model text,
  secondary_provider text,
  secondary_model text,
  input_summary text,
  output_summary text,
  status text not null default 'STARTED',
  human_approval_required boolean not null default false,
  prohibited_execution boolean not null default false,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists ai_brain_runs_created_idx on ai_brain_runs(created_at desc);
create index if not exists ai_brain_runs_task_idx on ai_brain_runs(task_type, created_at desc);

comment on table ai_brain_runs is 'Audit ledger for governed advisory AI runs. Never use this table as transaction authorization evidence by itself.';
