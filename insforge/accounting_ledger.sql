-- Double-entry accounting and reconciliation ledger for SAHJONY Global Trade.
-- Financial posting is append-only; corrections use reversing journals.

create table if not exists ledger_accounts (
  id bigserial primary key,
  account_id text not null unique,
  code text not null unique,
  name text not null,
  account_type text not null check (account_type in ('asset','liability','equity','revenue','expense','contra')),
  currency text default 'USD',
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists ledger_journals (
  id bigserial primary key,
  journal_id text not null unique,
  trade_case_id text,
  reference_type text,
  reference_id text,
  description text not null,
  currency text not null default 'USD',
  status text not null default 'draft' check (status in ('draft','posted','reversed','void')),
  source text not null default 'manual',
  owner_approved boolean not null default false,
  approved_by text,
  approved_at timestamptz,
  posted_at timestamptz,
  created_by_role text not null,
  created_by_id text not null,
  created_at timestamptz not null default now()
);

create index if not exists ledger_journals_case_idx on ledger_journals(trade_case_id, created_at desc);
create index if not exists ledger_journals_reference_idx on ledger_journals(reference_type, reference_id);

create table if not exists ledger_entries (
  id bigserial primary key,
  entry_id text not null unique,
  journal_id text not null references ledger_journals(journal_id),
  account_id text not null references ledger_accounts(account_id),
  debit numeric(18,4) not null default 0 check (debit >= 0),
  credit numeric(18,4) not null default 0 check (credit >= 0),
  memo text,
  created_at timestamptz not null default now(),
  check ((debit > 0 and credit = 0) or (credit > 0 and debit = 0))
);
create index if not exists ledger_entries_journal_idx on ledger_entries(journal_id);
create index if not exists ledger_entries_account_idx on ledger_entries(account_id);

create table if not exists payment_reconciliations (
  id bigserial primary key,
  reconciliation_id text not null unique,
  trade_case_id text,
  payment_id text,
  bank_reference text,
  invoice_reference text,
  purchase_order_reference text,
  expected_amount numeric(18,4),
  received_amount numeric(18,4),
  currency text default 'USD',
  status text not null default 'unmatched' check (status in ('unmatched','partial','matched','exception')),
  exception_reason text,
  matched_journal_id text references ledger_journals(journal_id),
  reconciled_by_role text,
  reconciled_by_id text,
  reconciled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists payment_reconciliations_case_idx on payment_reconciliations(trade_case_id, updated_at desc);

create table if not exists beneficiary_change_requests (
  id bigserial primary key,
  request_id text not null unique,
  counterparty_type text not null,
  counterparty_id text not null,
  old_bank_fingerprint text,
  new_bank_fingerprint text not null,
  verification_method text,
  status text not null default 'pending' check (status in ('pending','verified','approved','rejected','cancelled')),
  requested_by_role text not null,
  requested_by_id text not null,
  verified_by text,
  verified_at timestamptz,
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists beneficiary_changes_status_idx on beneficiary_change_requests(status, created_at desc);

comment on table ledger_journals is 'Financial journals. Posted journals are never edited; corrections require a reversing journal.';
comment on table beneficiary_change_requests is 'Maker-checker workflow for supplier/buyer bank-detail changes.';
