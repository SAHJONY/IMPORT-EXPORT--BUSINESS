create or replace function public.enforce_global_email_suppression_on_trade_record()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_email text;
  v_reason text;
begin
  if new.logical_table <> 'external_trade_prospects' then return new; end if;
  v_email := lower(trim(coalesce(new.data->>'public_email', '')));
  if v_email = '' then return new; end if;
  select s.data->>'reason' into v_reason
  from public.sahjony_trade_records s
  where s.logical_table = 'email_suppressions'
    and lower(trim(coalesce(s.data->>'email', ''))) = v_email
    and upper(coalesce(s.data->>'status', '')) = 'SUPPRESSED'
  order by s.updated_at desc limit 1;
  if found then
    new.data := jsonb_set(new.data, '{outreach_status}', '"SUPPRESSED"'::jsonb, true);
    new.data := jsonb_set(new.data, '{email_contact_status}', '"HARD_BOUNCE"'::jsonb, true);
    new.data := jsonb_set(new.data, '{do_not_contact}', 'true'::jsonb, true);
    new.data := jsonb_set(new.data, '{suppression_source}', '"email_suppressions"'::jsonb, true);
    new.data := jsonb_set(new.data, '{suppression_reason}', to_jsonb(coalesce(v_reason, 'SUPPRESSED')), true);
    new.data := jsonb_set(new.data, '{suppression_enforced_at}', to_jsonb(now()::text), true);
  end if;
  return new;
end;
$$;
revoke all on function public.enforce_global_email_suppression_on_trade_record() from public, anon, authenticated;
drop trigger if exists trg_enforce_global_email_suppression_on_trade_record on public.sahjony_trade_records;
create trigger trg_enforce_global_email_suppression_on_trade_record
before insert or update of logical_table, data on public.sahjony_trade_records
for each row execute function public.enforce_global_email_suppression_on_trade_record();

create or replace function public.propagate_global_email_suppression()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
declare v_email text;
begin
  if new.logical_table <> 'email_suppressions' or upper(coalesce(new.data->>'status', '')) <> 'SUPPRESSED' then return new; end if;
  v_email := lower(trim(coalesce(new.data->>'email', '')));
  if v_email = '' then return new; end if;
  update public.sahjony_trade_records p
  set data = p.data, updated_at = now()
  where p.logical_table = 'external_trade_prospects'
    and lower(trim(coalesce(p.data->>'public_email', ''))) = v_email;
  return new;
end;
$$;
revoke all on function public.propagate_global_email_suppression() from public, anon, authenticated;
drop trigger if exists trg_propagate_global_email_suppression on public.sahjony_trade_records;
create trigger trg_propagate_global_email_suppression
after insert or update of logical_table, data on public.sahjony_trade_records
for each row execute function public.propagate_global_email_suppression();

update public.sahjony_trade_records p
set data = p.data, updated_at = now()
where p.logical_table = 'external_trade_prospects'
  and exists (
    select 1 from public.sahjony_trade_records s
    where s.logical_table = 'email_suppressions'
      and upper(coalesce(s.data->>'status', '')) = 'SUPPRESSED'
      and lower(trim(coalesce(s.data->>'email', ''))) = lower(trim(coalesce(p.data->>'public_email', '')))
  );