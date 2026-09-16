create table if not exists public.browser_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid null,
  mode text not null default 'business' check (mode in ('business','personal')),
  title text not null,
  target_url text not null,
  goal text not null,
  provider text not null default 'tinyfish',
  browser_profile text not null default 'lite' check (browser_profile in ('lite','stealth')),
  risk_level text not null default 'low' check (risk_level in ('low','medium','high','critical')),
  approval_state text not null default 'not_required' check (approval_state in ('not_required','required','approved','rejected')),
  state text not null default 'queued' check (state in ('queued','running','waiting','blocked','requires_approval','completed','verified','failed','cancelled')),
  run_id text null,
  evidence jsonb not null default '[]'::jsonb,
  result jsonb null,
  error text null,
  max_steps integer not null default 80 check (max_steps between 1 and 500),
  budget_cents integer not null default 100 check (budget_cents between 0 and 100000),
  spent_cents integer not null default 0 check (spent_cents >= 0),
  attempts integer not null default 0 check (attempts between 0 and 10),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.browser_jobs enable row level security;
revoke all on public.browser_jobs from anon, authenticated;
create index if not exists browser_jobs_state_created_idx on public.browser_jobs(state, created_at desc);
create index if not exists browser_jobs_approval_idx on public.browser_jobs(approval_state, created_at desc);

create table if not exists public.browser_job_events (
  id bigint generated always as identity primary key,
  job_id uuid not null references public.browser_jobs(id) on delete cascade,
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.browser_job_events enable row level security;
revoke all on public.browser_job_events from anon, authenticated;
create index if not exists browser_job_events_job_created_idx on public.browser_job_events(job_id, created_at desc);
