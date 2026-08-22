-- SAHJONY Intermediary / Middleman operating layer
-- Applies explicit commercial-role, compensation and title/funds controls to managed-trade cases.

alter table managed_trade_cases add column if not exists intermediary_mode boolean not null default true;
alter table managed_trade_cases add column if not exists takes_title_to_goods boolean not null default false;
alter table managed_trade_cases add column if not exists controls_client_funds boolean not null default false;
alter table managed_trade_cases add column if not exists engagement_agreement_id text;
alter table managed_trade_cases add column if not exists economics_id text;

-- Expand SAHJONY roles without silently changing exporter/importer-of-record responsibility.
alter table managed_trade_cases drop constraint if exists managed_trade_cases_sahjony_role_check;
alter table managed_trade_cases add constraint managed_trade_cases_sahjony_role_check check (
  sahjony_role in (
    'MANAGED_TRADE_ORCHESTRATOR',
    'BROKER_INTERMEDIARY',
    'SOURCING_AGENT',
    'BUYING_AGENT',
    'SELLING_AGENT',
    'DISTRIBUTOR',
    'PRINCIPAL_RESELLER',
    'EXPORTER_OF_RECORD',
    'IMPORTER_OF_RECORD',
    'PRINCIPAL'
  )
);

create table if not exists managed_trade_engagements (
  id bigserial primary key,
  engagement_id text not null unique,
  request_id text references managed_trade_requests(request_id),
  managed_case_id text,
  principal_side text not null check (principal_side in ('BUYER','SUPPLIER','BOTH_DISCLOSED','SAHJONY_PRINCIPAL')),
  client_party_ref text,
  client_party_name text not null,
  sahjony_role text not null check (sahjony_role in ('MANAGED_TRADE_ORCHESTRATOR','BROKER_INTERMEDIARY','SOURCING_AGENT','BUYING_AGENT','SELLING_AGENT','DISTRIBUTOR','PRINCIPAL_RESELLER','PRINCIPAL')),
  agreement_document_id text,
  scope_summary text not null,
  compensation_disclosed boolean not null default false,
  dual_agency_disclosed boolean not null default false,
  authority_to_bind_client boolean not null default false,
  authority_to_receive_funds boolean not null default false,
  authority_to_take_title boolean not null default false,
  status text not null default 'DRAFT' check (status in ('DRAFT','PENDING_SIGNATURE','ACTIVE','SUSPENDED','EXPIRED','TERMINATED')),
  effective_at timestamptz,
  expires_at timestamptz,
  owner_approved boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists managed_trade_economics (
  id bigserial primary key,
  economics_id text not null unique,
  managed_case_id text not null references managed_trade_cases(managed_case_id) on delete cascade,
  payer_side text not null check (payer_side in ('BUYER','SUPPLIER','BOTH','SAHJONY_MARGIN')),
  compensation_type text not null check (compensation_type in ('FIXED_FEE','PERCENT_COMMISSION','SOURCING_FEE','MANAGEMENT_FEE','SUCCESS_FEE','BUY_SELL_MARGIN')),
  currency text not null default 'USD',
  base_amount numeric,
  rate_pct numeric,
  fixed_amount numeric,
  estimated_compensation numeric,
  final_compensation numeric,
  supplier_price numeric,
  customer_price numeric,
  third_party_costs numeric not null default 0,
  gross_margin numeric,
  gross_margin_pct numeric,
  disclosed_to_buyer boolean not null default false,
  disclosed_to_supplier boolean not null default false,
  owner_approved boolean not null default false,
  status text not null default 'DRAFT' check (status in ('DRAFT','APPROVED','INVOICED','PARTIALLY_PAID','PAID','VOID')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists managed_trade_role_assignments (
  id bigserial primary key,
  assignment_id text not null unique,
  managed_case_id text not null references managed_trade_cases(managed_case_id) on delete cascade,
  role_key text not null check (role_key in ('SELLER_OF_RECORD','BUYER_OF_RECORD','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','CUSTOMS_BROKER','FREIGHT_FORWARDER','CARRIER','SETTLEMENT_PROVIDER','INSURER','SAHJONY_COMMERCIAL_ROLE')),
  party_name text not null,
  party_ref text,
  evidence_document_id text,
  verified boolean not null default false,
  verified_by text,
  verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(managed_case_id, role_key)
);

create index if not exists idx_managed_engagements_case on managed_trade_engagements(managed_case_id,status);
create index if not exists idx_managed_economics_case on managed_trade_economics(managed_case_id,status);
create index if not exists idx_managed_role_assignments_case on managed_trade_role_assignments(managed_case_id,role_key);

-- Hard fail-closed release guard. A managed-trade case cannot become releasable unless
-- the intermediary engagement, compensation economics, and essential legal roles are verified.
create or replace function enforce_managed_intermediary_release()
returns trigger language plpgsql as $$
declare
  engagement_ready boolean;
  economics_ready boolean;
  verified_role_count integer;
begin
  if new.release_allowed is true and coalesce(old.release_allowed,false) is distinct from true then
    select exists(
      select 1 from managed_trade_engagements e
      where e.engagement_id = new.engagement_agreement_id
        and e.status = 'ACTIVE'
        and e.owner_approved = true
        and e.compensation_disclosed = true
    ) into engagement_ready;

    select exists(
      select 1 from managed_trade_economics x
      where x.economics_id = new.economics_id
        and x.managed_case_id = new.managed_case_id
        and x.status = 'APPROVED'
        and x.owner_approved = true
    ) into economics_ready;

    select count(distinct role_key) into verified_role_count
    from managed_trade_role_assignments r
    where r.managed_case_id = new.managed_case_id
      and r.verified = true
      and r.role_key in ('SELLER_OF_RECORD','BUYER_OF_RECORD','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','SAHJONY_COMMERCIAL_ROLE');

    if not engagement_ready then
      raise exception 'Managed trade release denied: active approved intermediary engagement required';
    end if;
    if not economics_ready then
      raise exception 'Managed trade release denied: approved intermediary economics required';
    end if;
    if verified_role_count < 5 then
      raise exception 'Managed trade release denied: verified seller, buyer, exporter, importer, and SAHJONY commercial role assignments required';
    end if;
    if new.intermediary_mode = true and new.takes_title_to_goods = true then
      raise exception 'Managed trade release denied: intermediary mode cannot take title to goods';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_enforce_managed_intermediary_release on managed_trade_cases;
create trigger trg_enforce_managed_intermediary_release
before update of release_allowed on managed_trade_cases
for each row execute function enforce_managed_intermediary_release();
