-- SAHJONY Global Trade identity and RLS foundation for Neon Auth + Neon Data API.
-- Apply only after the participant-facing domain tables exist.
-- Neon Data API authenticates browser requests as the `authenticated` Postgres role
-- and exposes the JWT `sub` through auth.user_id(). Trusted server/database-owner
-- connections remain outside this browser-facing authorization boundary.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    RAISE EXCEPTION 'Neon Data API role authenticated is not provisioned';
  END IF;
  IF to_regprocedure('auth.user_id()') IS NULL THEN
    RAISE EXCEPTION 'Neon Data API auth.user_id() is not provisioned';
  END IF;
END;
$$;

create table if not exists public.app_memberships (
  id bigserial primary key,
  membership_id text not null unique,
  user_id text not null,
  role text not null check (role in ('owner','employee','customer')),
  customer_id text,
  employee_id text,
  status text not null default 'active' check (status in ('active','suspended','revoked')),
  mfa_required boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((role='customer' and customer_id is not null) or role<>'customer')
);
create unique index if not exists app_memberships_user_role_scope_idx
  on public.app_memberships(user_id, role, coalesce(customer_id,''), coalesce(employee_id,''));

create or replace function public.requesting_user_id() returns text
language sql stable
as $$
  select nullif(auth.user_id()::text, '');
$$;

create or replace function public.app_has_role(required_role text) returns boolean
language sql stable security definer
set search_path = public, pg_catalog
as $$
  select exists (
    select 1
    from public.app_memberships m
    where m.user_id = public.requesting_user_id()
      and m.role = required_role
      and m.status = 'active'
  );
$$;

create or replace function public.app_can_access_customer(target_customer_id text) returns boolean
language sql stable security definer
set search_path = public, pg_catalog
as $$
  select public.app_has_role('owner')
      or public.app_has_role('employee')
      or exists (
        select 1
        from public.app_memberships m
        where m.user_id = public.requesting_user_id()
          and m.role = 'customer'
          and m.status = 'active'
          and m.customer_id = target_customer_id
      );
$$;

create or replace function public.app_is_internal() returns boolean
language sql stable
as $$
  select public.app_has_role('owner') or public.app_has_role('employee');
$$;

-- Data API privileges are intentionally narrower than Neon's broad default grants.
grant usage on schema public to authenticated;

revoke insert, update, delete on public.app_memberships from authenticated;
grant select on public.app_memberships to authenticated;

revoke update, delete on public.trade_documents from authenticated;
grant select, insert on public.trade_documents to authenticated;
grant usage, select on sequence public.trade_documents_id_seq to authenticated;

revoke insert, update, delete on public.document_movements from authenticated;
grant select on public.document_movements to authenticated;

revoke insert, update, delete on public.shipments from authenticated;
grant select on public.shipments to authenticated;

revoke insert, update, delete on public.shipment_milestones from authenticated;
grant select on public.shipment_milestones to authenticated;

revoke insert, update, delete on public.trade_compliance_cases from authenticated;
grant select on public.trade_compliance_cases to authenticated;

revoke insert, update, delete on public.business_events from authenticated;
grant select on public.business_events to authenticated;

revoke insert, update, delete on public.communications from authenticated;
grant select on public.communications to authenticated;

alter table public.app_memberships enable row level security;
drop policy if exists app_memberships_self_select on public.app_memberships;
create policy app_memberships_self_select on public.app_memberships
for select to authenticated
using (user_id = public.requesting_user_id());

-- Participant-visible domain policies. Server/admin operations continue through
-- trusted backend connections; browser/user JWT access is constrained here.
alter table public.trade_documents enable row level security;
drop policy if exists trade_documents_read on public.trade_documents;
create policy trade_documents_read on public.trade_documents
for select to authenticated
using (
  public.app_is_internal()
  or (customer_visible = true and public.app_can_access_customer(customer_id))
);

drop policy if exists trade_documents_customer_insert on public.trade_documents;
create policy trade_documents_customer_insert on public.trade_documents
for insert to authenticated
with check (
  public.app_is_internal()
  or (
    created_by_role = 'customer'
    and created_by_id = public.requesting_user_id()
    and public.app_can_access_customer(customer_id)
  )
);

alter table public.document_movements enable row level security;
drop policy if exists document_movements_read on public.document_movements;
create policy document_movements_read on public.document_movements
for select to authenticated
using (exists (
  select 1
  from public.trade_documents d
  where d.document_id = document_movements.document_id
    and (
      public.app_is_internal()
      or (d.customer_visible = true and public.app_can_access_customer(d.customer_id))
    )
));

alter table public.shipments enable row level security;
drop policy if exists shipments_read on public.shipments;
create policy shipments_read on public.shipments
for select to authenticated
using (
  public.app_is_internal()
  or (customer_visible = true and public.app_can_access_customer(customer_id))
);

alter table public.shipment_milestones enable row level security;
drop policy if exists shipment_milestones_read on public.shipment_milestones;
create policy shipment_milestones_read on public.shipment_milestones
for select to authenticated
using (exists (
  select 1
  from public.shipments s
  where s.shipment_id = shipment_milestones.shipment_id
    and (
      public.app_is_internal()
      or (s.customer_visible = true and public.app_can_access_customer(s.customer_id))
    )
));

alter table public.trade_compliance_cases enable row level security;
drop policy if exists compliance_cases_read on public.trade_compliance_cases;
create policy compliance_cases_read on public.trade_compliance_cases
for select to authenticated
using (
  public.app_is_internal()
  or (customer_visible = true and public.app_can_access_customer(customer_id))
);

alter table public.business_events enable row level security;
drop policy if exists business_events_read on public.business_events;
create policy business_events_read on public.business_events
for select to authenticated
using (
  public.app_has_role('owner')
  or (public.app_has_role('employee') and visibility in ('internal','customer'))
  or (visibility = 'customer' and public.app_can_access_customer(customer_id))
);

alter table public.communications enable row level security;
drop policy if exists communications_read on public.communications;
create policy communications_read on public.communications
for select to authenticated
using (
  public.app_is_internal()
  or public.app_can_access_customer(customer_id)
);

comment on table public.app_memberships is
  'Maps verified Neon Auth JWT subject (sub) to application roles and tenant/customer scope. Browser-supplied role or customer identifiers are never trusted as authorization evidence.';
