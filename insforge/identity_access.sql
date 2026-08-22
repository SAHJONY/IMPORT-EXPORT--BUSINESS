-- SAHJONY Global Trade identity and RLS foundation.
-- Apply after the domain schemas. JWT identities are scoped by the `sub` claim.

create table if not exists app_memberships (
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
  on app_memberships(user_id, role, coalesce(customer_id,''), coalesce(employee_id,''));

create or replace function requesting_user_id() returns text
language sql stable as $$
  select nullif((current_setting('request.jwt.claims', true)::jsonb ->> 'sub'), '');
$$;

create or replace function app_has_role(required_role text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from app_memberships m
    where m.user_id = requesting_user_id()
      and m.role = required_role
      and m.status = 'active'
  );
$$;

create or replace function app_can_access_customer(target_customer_id text) returns boolean
language sql stable security definer set search_path = public as $$
  select app_has_role('owner') or app_has_role('employee') or exists (
    select 1 from app_memberships m
    where m.user_id = requesting_user_id()
      and m.role='customer'
      and m.status='active'
      and m.customer_id=target_customer_id
  );
$$;

create or replace function app_is_internal() returns boolean
language sql stable as $$ select app_has_role('owner') or app_has_role('employee'); $$;

alter table app_memberships enable row level security;
drop policy if exists app_memberships_self_select on app_memberships;
create policy app_memberships_self_select on app_memberships for select to authenticated
using (user_id=requesting_user_id());

-- Participant-visible domain policies. Server/admin operations may continue through the trusted admin API;
-- browser/user JWT access is constrained here.
alter table trade_documents enable row level security;
drop policy if exists trade_documents_read on trade_documents;
create policy trade_documents_read on trade_documents for select to authenticated
using (app_is_internal() or (customer_visible=true and app_can_access_customer(customer_id)));

drop policy if exists trade_documents_customer_insert on trade_documents;
create policy trade_documents_customer_insert on trade_documents for insert to authenticated
with check (app_is_internal() or (created_by_role='customer' and app_can_access_customer(customer_id)));

alter table document_movements enable row level security;
drop policy if exists document_movements_read on document_movements;
create policy document_movements_read on document_movements for select to authenticated
using (exists (
  select 1 from trade_documents d
  where d.document_id=document_movements.document_id
    and (app_is_internal() or (d.customer_visible=true and app_can_access_customer(d.customer_id)))
));

alter table shipments enable row level security;
drop policy if exists shipments_read on shipments;
create policy shipments_read on shipments for select to authenticated
using (app_is_internal() or (customer_visible=true and app_can_access_customer(customer_id)));

alter table shipment_milestones enable row level security;
drop policy if exists shipment_milestones_read on shipment_milestones;
create policy shipment_milestones_read on shipment_milestones for select to authenticated
using (exists (
  select 1 from shipments s where s.shipment_id=shipment_milestones.shipment_id
    and (app_is_internal() or (s.customer_visible=true and app_can_access_customer(s.customer_id)))
));

alter table trade_compliance_cases enable row level security;
drop policy if exists compliance_cases_read on trade_compliance_cases;
create policy compliance_cases_read on trade_compliance_cases for select to authenticated
using (app_is_internal() or (customer_visible=true and app_can_access_customer(customer_id)));

alter table business_events enable row level security;
drop policy if exists business_events_read on business_events;
create policy business_events_read on business_events for select to authenticated
using (
  app_has_role('owner')
  or (app_has_role('employee') and visibility in ('internal','customer'))
  or (visibility='customer' and app_can_access_customer(customer_id))
);

alter table communications enable row level security;
drop policy if exists communications_read on communications;
create policy communications_read on communications for select to authenticated
using (app_is_internal() or app_can_access_customer(customer_id));

comment on table app_memberships is 'Maps verified JWT subject (`sub`) to application roles and tenant/customer scope. Never trust browser-supplied role/customer IDs without this membership boundary.';
