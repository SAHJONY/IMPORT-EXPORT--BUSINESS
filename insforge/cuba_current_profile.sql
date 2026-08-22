-- SAHJONY Global Trade · real Cuba jurisdiction profile safeguards
-- Baseline date: 2026-08-22
-- Real Cuba is a restricted LIVE jurisdiction. This schema does not create exemptions,
-- licenses, sanctions waivers, payment workarounds, or any legal override.

create table if not exists cuba_current_compliance_snapshot (
  id bigserial primary key,
  snapshot_id text not null unique,
  as_of_date date not null,
  authority text not null,
  authority_reference text not null,
  summary text not null,
  created_at timestamptz not null default now()
);

-- Real Cuba live corridors cannot be globally READY. They remain LIMITED or BLOCKED
-- and must pass the normal compliance, product, counterparty, banking and customs gates.
create or replace function enforce_real_cuba_corridor_limit()
returns trigger language plpgsql as $$
begin
  if (new.origin_country_code = 'CU' or new.destination_country_code = 'CU')
     and coalesce(new.execution_mode, 'LIVE') = 'LIVE'
     and new.status = 'READY' then
    raise exception 'Real Cuba corridors cannot be globally READY; use LIMITED or BLOCKED and satisfy applicable legal/compliance gates';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_enforce_real_cuba_corridor_limit on trade_corridor_activations;
create trigger trg_enforce_real_cuba_corridor_limit
before insert or update on trade_corridor_activations
for each row execute function enforce_real_cuba_corridor_limit();
