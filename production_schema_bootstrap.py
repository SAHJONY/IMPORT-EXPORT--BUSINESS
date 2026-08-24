from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg


MIGRATION_ID = "2026-08-23-canonical-vercel-trade-schema-v1"


def _database_url() -> str:
    for name in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "NEON_DATABASE_URL",
        "NEON_POSTGRES_URL",
        "POSTGRES_PRISMA_URL",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError("Production database URL is not configured")


DDL = r"""
CREATE TABLE IF NOT EXISTS sahjony_schema_migrations (
    migration_id text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_payment_ledger (
    id bigserial PRIMARY KEY,
    payment_case_id text NOT NULL UNIQUE,
    audience text NOT NULL,
    customer_reference text NOT NULL,
    source_reference text,
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    total_amount numeric(18,4) NOT NULL CHECK (total_amount >= 0),
    deposit_amount numeric(18,4) NOT NULL DEFAULT 0 CHECK (deposit_amount >= 0),
    customer_paid numeric(18,4) NOT NULL DEFAULT 0 CHECK (customer_paid >= 0),
    outstanding_balance numeric(18,4) NOT NULL DEFAULT 0 CHECK (outstanding_balance >= 0),
    payment_status text NOT NULL,
    payment_rail text,
    quote_approved boolean NOT NULL DEFAULT false,
    compliance_cleared boolean NOT NULL DEFAULT false,
    payment_allowed boolean NOT NULL DEFAULT false,
    supplier_payout_allowed boolean NOT NULL DEFAULT false,
    shipment_release_allowed boolean NOT NULL DEFAULT false,
    supplier_payout_authorized_at timestamptz,
    shipment_release_authorized_at timestamptz,
    supplier_payout_owner_note text,
    shipment_release_owner_note text,
    funds_external_reference text,
    funds_note text,
    owner_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_payment_ledger_created_idx ON trade_payment_ledger(created_at DESC);
CREATE INDEX IF NOT EXISTS trade_payment_ledger_status_idx ON trade_payment_ledger(payment_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS trade_payment_events (
    id bigserial PRIMARY KEY,
    event_id text NOT NULL UNIQUE,
    payment_case_id text NOT NULL REFERENCES trade_payment_ledger(payment_case_id) ON DELETE RESTRICT,
    event_type text NOT NULL,
    amount numeric(18,4),
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    external_reference text,
    owner_note text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trade_payment_events_case_idx ON trade_payment_events(payment_case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS trade_payment_events_type_idx ON trade_payment_events(event_type, created_at DESC);

CREATE TABLE IF NOT EXISTS cuba_partner_accounts (
    id bigserial PRIMARY KEY,
    partner_id text NOT NULL UNIQUE,
    full_name text NOT NULL,
    phone text,
    email text,
    province text,
    municipality text,
    preferred_language text NOT NULL DEFAULT 'es',
    experience text,
    network_description text,
    payment_method_note text,
    status text NOT NULL DEFAULT 'APPLIED',
    referral_token_hash text NOT NULL,
    automatic_commission_payout boolean NOT NULL DEFAULT false,
    owner_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cuba_partner_accounts_status_idx ON cuba_partner_accounts(status, created_at DESC);

CREATE TABLE IF NOT EXISTS cuba_partner_referrals (
    id bigserial PRIMARY KEY,
    referral_id text NOT NULL UNIQUE,
    partner_id text NOT NULL REFERENCES cuba_partner_accounts(partner_id) ON DELETE RESTRICT,
    prospect_name text NOT NULL,
    prospect_phone text,
    prospect_email text,
    opportunity_type text NOT NULL,
    description text NOT NULL,
    estimated_value_usd numeric(18,4),
    notes text,
    referral_status text NOT NULL DEFAULT 'SUBMITTED',
    commission_status text NOT NULL DEFAULT 'NOT_EARNED',
    commission_amount_usd numeric(18,4),
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    owner_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cuba_partner_referrals_partner_idx ON cuba_partner_referrals(partner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS cuba_partner_referrals_status_idx ON cuba_partner_referrals(referral_status, commission_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS cuba_consumer_marketplace_requests (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    request_type text NOT NULL DEFAULT 'INDIVIDUAL_CONSUMER',
    country text NOT NULL DEFAULT 'CU',
    full_name text NOT NULL,
    phone text,
    email text,
    preferred_language text NOT NULL DEFAULT 'es',
    province text,
    municipality text,
    delivery_address text,
    category text NOT NULL,
    product_description text NOT NULL,
    quantity numeric(18,4),
    unit text,
    intended_use text NOT NULL,
    personal_or_family_use boolean NOT NULL DEFAULT true,
    budget_amount numeric(18,4),
    budget_currency text NOT NULL DEFAULT 'USD' CHECK (budget_currency = 'USD'),
    notes text,
    status text NOT NULL DEFAULT 'RECEIVED',
    eligibility_route text NOT NULL DEFAULT 'NOT_YET_CLASSIFIED',
    quote_amount numeric(18,4),
    quote_currency text NOT NULL DEFAULT 'USD' CHECK (quote_currency = 'USD'),
    customer_message text,
    owner_note text,
    release_allowed boolean NOT NULL DEFAULT false,
    payment_allowed boolean NOT NULL DEFAULT false,
    shipment_allowed boolean NOT NULL DEFAULT false,
    status_token_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cuba_consumer_requests_status_idx ON cuba_consumer_marketplace_requests(status, created_at DESC);
CREATE INDEX IF NOT EXISTS cuba_consumer_requests_category_idx ON cuba_consumer_marketplace_requests(category, updated_at DESC);

CREATE TABLE IF NOT EXISTS ledger_accounts (
    id bigserial PRIMARY KEY,
    account_id text NOT NULL UNIQUE,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    account_type text NOT NULL CHECK (account_type IN ('asset','liability','equity','revenue','expense','contra')),
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ledger_journals (
    id bigserial PRIMARY KEY,
    journal_id text NOT NULL UNIQUE,
    trade_case_id text,
    reference_type text,
    reference_id text,
    description text NOT NULL,
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed','void')),
    source text NOT NULL DEFAULT 'manual',
    owner_approved boolean NOT NULL DEFAULT false,
    approved_by text,
    approved_at timestamptz,
    posted_at timestamptz,
    created_by_role text NOT NULL,
    created_by_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ledger_journals_case_idx ON ledger_journals(trade_case_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ledger_journals_reference_idx ON ledger_journals(reference_type, reference_id);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id bigserial PRIMARY KEY,
    entry_id text NOT NULL UNIQUE,
    journal_id text NOT NULL REFERENCES ledger_journals(journal_id) ON DELETE RESTRICT,
    account_id text NOT NULL REFERENCES ledger_accounts(account_id) ON DELETE RESTRICT,
    debit numeric(18,4) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit numeric(18,4) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    memo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
);
CREATE INDEX IF NOT EXISTS ledger_entries_journal_idx ON ledger_entries(journal_id);
CREATE INDEX IF NOT EXISTS ledger_entries_account_idx ON ledger_entries(account_id);

CREATE TABLE IF NOT EXISTS payment_reconciliations (
    id bigserial PRIMARY KEY,
    reconciliation_id text NOT NULL UNIQUE,
    trade_case_id text,
    payment_id text,
    bank_reference text,
    invoice_reference text,
    purchase_order_reference text,
    expected_amount numeric(18,4),
    received_amount numeric(18,4),
    currency text NOT NULL DEFAULT 'USD' CHECK (currency = 'USD'),
    status text NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched','partial','matched','exception')),
    exception_reason text,
    matched_journal_id text REFERENCES ledger_journals(journal_id) ON DELETE RESTRICT,
    reconciled_by_role text,
    reconciled_by_id text,
    reconciled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS payment_reconciliations_case_idx ON payment_reconciliations(trade_case_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS beneficiary_change_requests (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL UNIQUE,
    counterparty_type text NOT NULL,
    counterparty_id text NOT NULL,
    old_bank_fingerprint text,
    new_bank_fingerprint text NOT NULL,
    verification_method text,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','approved','rejected','cancelled')),
    requested_by_role text NOT NULL,
    requested_by_id text NOT NULL,
    verified_by text,
    verified_at timestamptz,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS beneficiary_changes_status_idx ON beneficiary_change_requests(status, created_at DESC);
"""


LEDGER_ACCOUNTS = (
    ("acct_cash_operating", "1000", "Operating Cash", "asset"),
    ("acct_cash_customer", "1010", "Customer Funds Clearing", "asset"),
    ("acct_accounts_receivable", "1100", "Accounts Receivable", "asset"),
    ("acct_supplier_advances", "1200", "Supplier Advances", "asset"),
    ("acct_accounts_payable", "2000", "Accounts Payable", "liability"),
    ("acct_customer_deposits", "2100", "Customer Deposits", "liability"),
    ("acct_tax_payable", "2200", "Taxes and Duties Payable", "liability"),
    ("acct_owner_equity", "3000", "Owner Equity", "equity"),
    ("acct_trade_revenue", "4000", "Trade Revenue", "revenue"),
    ("acct_service_fee_revenue", "4100", "Service Fee Revenue", "revenue"),
    ("acct_cogs", "5000", "Cost of Goods Sold", "expense"),
    ("acct_logistics_expense", "5100", "Freight Customs and Logistics", "expense"),
)


def _bootstrap_sync() -> dict[str, Any]:
    url = _database_url()
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (84723119,))
            cur.execute(DDL)
            for account_id, code, name, account_type in LEDGER_ACCOUNTS:
                cur.execute(
                    """
                    INSERT INTO ledger_accounts (account_id, code, name, account_type, currency, active)
                    VALUES (%s, %s, %s, %s, 'USD', true)
                    ON CONFLICT (account_id) DO UPDATE
                    SET active = true, currency = 'USD'
                    """,
                    (account_id, code, name, account_type),
                )
            cur.execute(
                "INSERT INTO sahjony_schema_migrations (migration_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (MIGRATION_ID,),
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name = ANY(%s)
                """,
                ([
                    'trade_payment_ledger','trade_payment_events','cuba_partner_accounts','cuba_partner_referrals',
                    'cuba_consumer_marketplace_requests','ledger_accounts','ledger_journals','ledger_entries',
                    'payment_reconciliations','beneficiary_change_requests'
                ],),
            )
            table_count = int(cur.fetchone()[0])
            cur.execute("SELECT count(*) FROM ledger_accounts WHERE active=true AND currency='USD'")
            active_usd_accounts = int(cur.fetchone()[0])
    return {
        "migration_id": MIGRATION_ID,
        "canonical_database": "active_vercel_database_url",
        "required_tables_present": table_count,
        "active_usd_accounts": active_usd_accounts,
        "destructive_operations": False,
        "completed": table_count == 10 and active_usd_accounts >= 12,
    }


async def ensure_production_schema() -> dict[str, Any]:
    if os.getenv("VERCEL_ENV", "").strip().lower() != "production":
        return {
            "completed": False,
            "skipped": True,
            "reason": "schema bootstrap is production-only",
            "canonical_database": "active_vercel_database_url",
        }
    return await asyncio.to_thread(_bootstrap_sync)
