from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg


MIGRATION_ID = "2026-08-23-canonical-vercel-trade-schema-v1"
ENERGY_INTELLIGENCE_MIGRATION_ID = "2026-08-24-energy-commercial-intelligence-v1"


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

CREATE TABLE IF NOT EXISTS energy_research_leads (
    id bigserial PRIMARY KEY,
    lead_key text NOT NULL UNIQUE,
    desk text NOT NULL CHECK (desk IN ('CUBA_FUELS','GLOBAL_CRUDE')),
    lead_type text NOT NULL,
    legal_name text NOT NULL,
    country_code text,
    product text NOT NULL,
    quantity numeric(22,4),
    unit text,
    commercial_signal text NOT NULL,
    verification_status text NOT NULL DEFAULT 'RESEARCH_ONLY',
    outreach_status text NOT NULL DEFAULT 'NOT_CONTACTED',
    contact_path text,
    source_reference text NOT NULL,
    evidence_summary text NOT NULL,
    risk_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes text,
    observed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    release_allowed boolean NOT NULL DEFAULT false,
    binding_authority boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS energy_research_leads_desk_idx ON energy_research_leads(desk, updated_at DESC);
CREATE INDEX IF NOT EXISTS energy_research_leads_status_idx ON energy_research_leads(verification_status, outreach_status, updated_at DESC);
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

ENERGY_RESEARCH_LEADS = (
    {
        "lead_key": "cuba-katapulk-fuels-2026-08",
        "desk": "CUBA_FUELS", "lead_type": "DISTRIBUTION_PARTNER", "legal_name": "Katapulk",
        "country_code": "US/CU", "product": "U.S.-origin gasoline and diesel", "quantity": None, "unit": None,
        "commercial_signal": "Operating U.S.-to-Cuba private-sector fuel delivery channel with commercial formats including ISO-tank scale.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "Public commercial channel",
        "source_reference": "https://oncubanews.com/publirreportaje/katapulk-ofrece-combustible-a-las-mipymes-cubanas-canales-seguros-para-nuestros-clientes/",
        "evidence_summary": "Public commercial reporting describes fuel delivery to Cuban MIPYMEs and structured delivery formats.",
        "risk_flags": ["TRANSACTION_SPECIFIC_SCP_REVIEW", "OWNERSHIP_SCREENING_REQUIRED", "PAYMENT_PATH_REVIEW"],
        "notes": "SAHJONY requested wholesale pricing, minimum volumes, capacity, delivery points, KYC/KYB and partner economics.",
    },
    {
        "lead_key": "cuba-mipymecombustible-fuels-2026-08",
        "desk": "CUBA_FUELS", "lead_type": "DISTRIBUTION_PARTNER", "legal_name": "MiPymeCombustible",
        "country_code": "US/CU", "product": "Gasoline and diesel", "quantity": None, "unit": None,
        "commercial_signal": "Private-sector fuel platform advertising gasoline/diesel import and direct-supply workflows.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "Public website commercial channel",
        "source_reference": "https://mipymecombustible.com/",
        "evidence_summary": "Public commercial site presents private-sector fuel supply workflows.",
        "risk_flags": ["TRANSACTION_SPECIFIC_SCP_REVIEW", "OWNERSHIP_SCREENING_REQUIRED"],
        "notes": "Qualification requested for wholesale economics and compliant payment/logistics structure.",
    },
    {
        "lead_key": "cuba-isladiesel-fuels-2026-08",
        "desk": "CUBA_FUELS", "lead_type": "DISTRIBUTION_PARTNER", "legal_name": "IslaDiesel",
        "country_code": "US/CU", "product": "Diesel and gasoline", "quantity": None, "unit": None,
        "commercial_signal": "Collective-purchase / commercial fuel channel serving Cuban demand.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "Public website commercial channel",
        "source_reference": "https://isladiesel.com/",
        "evidence_summary": "Public commercial site presents gasoline/diesel purchase coordination.",
        "risk_flags": ["TRANSACTION_SPECIFIC_SCP_REVIEW", "OWNERSHIP_SCREENING_REQUIRED"],
        "notes": "SAHJONY requested B2B/wholesale partner terms and operating requirements.",
    },
    {
        "lead_key": "cuba-a-granel-diesel-2026-08",
        "desk": "CUBA_FUELS", "lead_type": "CUBAN_PRIVATE_BUYER_DISTRIBUTOR", "legal_name": "A Granel",
        "country_code": "CU", "product": "U.S.-origin diesel", "quantity": None, "unit": None,
        "commercial_signal": "Reported private distributor selling imported U.S. diesel to registered private businesses in Havana.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "RESEARCH_ONLY", "contact_path": "Public-source identification; direct authority not yet verified",
        "source_reference": "https://www.reuters.com/business/energy/us-fuel-sales-cuban-business-bring-glimpse-capitalism-havana-2026-08-11/",
        "evidence_summary": "Reuters reported private-sector U.S.-origin fuel sales and identified A Granel as an operating distributor.",
        "risk_flags": ["BENEFICIAL_OWNERSHIP_REQUIRED", "DIRECT_CONTACT_NOT_VERIFIED", "TRANSACTION_SPECIFIC_SCP_REVIEW"],
        "notes": "High-priority buyer/distributor prospect; no binding outreach until authority and ownership are verified.",
    },
    {
        "lead_key": "crude-hpcl-4m-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "INSTITUTIONAL_BUYER", "legal_name": "Hindustan Petroleum Corporation Limited (HPCL)",
        "country_code": "IN", "product": "Crude oil", "quantity": 4000000, "unit": "BBL",
        "commercial_signal": "Public procurement signal for up to 4 million barrels for September/October delivery.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "corphqo@hpcl.in",
        "source_reference": "https://www.reuters.com/business/energy/indias-hpcl-mrpl-seek-up-six-million-barrels-crude-documents-show-2026-08-12/",
        "evidence_summary": "Reuters reported HPCL seeking up to 4 MMbbl; SAHJONY requested counterparty registration and procurement requirements.",
        "risk_flags": ["APPROVED_COUNTERPARTY_REGISTRATION_REQUIRED", "SELLER_TITLE_EVIDENCE_REQUIRED"],
        "notes": "Crude pipeline is global and explicitly outside Cuba.",
    },
    {
        "lead_key": "crude-mrpl-2m-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "INSTITUTIONAL_BUYER", "legal_name": "Mangalore Refinery and Petrochemicals Limited (MRPL)",
        "country_code": "IN", "product": "Crude oil", "quantity": 2000000, "unit": "BBL",
        "commercial_signal": "Public procurement signal for up to 2 million barrels with October delivery window.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "eps@mrpl.co.in",
        "source_reference": "https://www.reuters.com/business/energy/indias-hpcl-mrpl-seek-up-six-million-barrels-crude-documents-show-2026-08-12/",
        "evidence_summary": "Reuters reported MRPL seeking up to 2 MMbbl; SAHJONY requested registration, tender and KYC/KYB requirements.",
        "risk_flags": ["APPROVED_COUNTERPARTY_REGISTRATION_REQUIRED", "SELLER_TITLE_EVIDENCE_REQUIRED"],
        "notes": "Current institutional buyer path; no cargo representation made by SAHJONY.",
    },
    {
        "lead_key": "crude-indianoil-registration-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "APPROVED_TRADER_REGISTRATION", "legal_name": "Indian Oil Corporation Limited (IndianOil)",
        "country_code": "IN", "product": "Crude oil", "quantity": None, "unit": None,
        "commercial_signal": "Ongoing institutional crude import program with approved supplier/buyer registration route.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "QUALIFICATION_SENT", "contact_path": "avraghunadhan@indianoil.in",
        "source_reference": "https://www.iocl.com/import-export",
        "evidence_summary": "IndianOil publishes an approved mailing-list/counterparty route for crude procurement participation.",
        "risk_flags": ["COUNTERPARTY_APPROVAL_REQUIRED", "TENDER_SPECIFIC_TERMS_REQUIRED"],
        "notes": "SAHJONY requested the current direct institutional registration path.",
    },
    {
        "lead_key": "crude-adnoc-spot-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "NOC_SELL_SIDE_TENDER", "legal_name": "ADNOC",
        "country_code": "AE", "product": "Upper Zakum / Umm Lulu / Das crude", "quantity": None, "unit": "BBL",
        "commercial_signal": "Publicly reported spot crude tender signal; window requires current confirmation before action.",
        "verification_status": "DEADLINE_REVIEW", "outreach_status": "RESEARCH_ONLY", "contact_path": "Official ADNOC trading/tender channel required",
        "source_reference": "https://economictimes.indiatimes.com/industry/energy/oil-gas/adnoc-launches-ninth-spot-crude-tender-since-june-sources-say/articleshow/133364799.cms",
        "evidence_summary": "Reported spot tender covering multiple ADNOC grades; timing is perishable and must be revalidated.",
        "risk_flags": ["DEADLINE_CONFIRMATION_REQUIRED", "APPROVED_BIDDER_STATUS_REQUIRED"],
        "notes": "Do not treat as open until the official tender window is independently confirmed.",
    },
    {
        "lead_key": "crude-joel-campble-1m-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "MARKETPLACE_BUYER_SIGNAL", "legal_name": "Joel Campble / buyer entity TBD",
        "country_code": "US", "product": "Crude oil", "quantity": 1000000, "unit": "BBL",
        "commercial_signal": "Marketplace RFQ for 1 million barrels, CIF or FOB, worldwide supply, L/C or SBLC indicated.",
        "verification_status": "QUALIFICATION_PENDING", "outreach_status": "QUALIFICATION_SENT", "contact_path": "go4WorldBusiness buyer feed / direct qualification request",
        "source_reference": "Gmail buyer feed dated 2026-08-24 from go4WorldBusiness",
        "evidence_summary": "Marketplace feed reports a crude RFQ but public role information is inconsistent; buyer authority remains unverified.",
        "risk_flags": ["BUYER_ENTITY_UNVERIFIED", "ROLE_INCONSISTENCY", "LOI_ICPO_RWA_REQUIRED"],
        "notes": "Do not source cargo until buyer entity, authority, destination, grade and financial capability are verified.",
    },
    {
        "lead_key": "crude-asia-demand-cluster-2026-08",
        "desk": "GLOBAL_CRUDE", "lead_type": "MARKET_DEMAND_CLUSTER", "legal_name": "GS Caltex / Eneos / Cosmo / CPC demand cluster",
        "country_code": "KR/JP/TW", "product": "U.S. and West African crude grades", "quantity": None, "unit": "BBL",
        "commercial_signal": "Recent refinery buying activity indicates active Asian demand for alternatives to Middle East barrels.",
        "verification_status": "VERIFIED_SIGNAL", "outreach_status": "RESEARCH_ONLY", "contact_path": "Refinery procurement channels",
        "source_reference": "https://www.reuters.com/business/energy/asian-refiners-buy-more-us-crude-hormuz-remains-blocked-traders-say-2026-08-14/",
        "evidence_summary": "Reuters reported current buying by major Asian refiners including GS Caltex and other regional refiners.",
        "risk_flags": ["COUNTERPARTY_SPECIFIC_QUALIFICATION_REQUIRED"],
        "notes": "Market intelligence signal, not a single confirmed RFQ.",
    },
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
            for lead in ENERGY_RESEARCH_LEADS:
                cur.execute(
                    """
                    INSERT INTO energy_research_leads (
                        lead_key, desk, lead_type, legal_name, country_code, product, quantity, unit,
                        commercial_signal, verification_status, outreach_status, contact_path,
                        source_reference, evidence_summary, risk_flags, notes, observed_at,
                        release_allowed, binding_authority, updated_at
                    ) VALUES (
                        %(lead_key)s, %(desk)s, %(lead_type)s, %(legal_name)s, %(country_code)s,
                        %(product)s, %(quantity)s, %(unit)s, %(commercial_signal)s,
                        %(verification_status)s, %(outreach_status)s, %(contact_path)s,
                        %(source_reference)s, %(evidence_summary)s, %(risk_flags)s::jsonb,
                        %(notes)s, now(), false, false, now()
                    )
                    ON CONFLICT (lead_key) DO UPDATE SET
                        desk=EXCLUDED.desk,
                        lead_type=EXCLUDED.lead_type,
                        legal_name=EXCLUDED.legal_name,
                        country_code=EXCLUDED.country_code,
                        product=EXCLUDED.product,
                        quantity=EXCLUDED.quantity,
                        unit=EXCLUDED.unit,
                        commercial_signal=EXCLUDED.commercial_signal,
                        verification_status=EXCLUDED.verification_status,
                        outreach_status=EXCLUDED.outreach_status,
                        contact_path=EXCLUDED.contact_path,
                        source_reference=EXCLUDED.source_reference,
                        evidence_summary=EXCLUDED.evidence_summary,
                        risk_flags=EXCLUDED.risk_flags,
                        notes=EXCLUDED.notes,
                        release_allowed=false,
                        binding_authority=false,
                        updated_at=now()
                    """,
                    {**lead, "risk_flags": __import__("json").dumps(lead["risk_flags"])},
                )
            cur.execute(
                "INSERT INTO sahjony_schema_migrations (migration_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (MIGRATION_ID,),
            )
            cur.execute(
                "INSERT INTO sahjony_schema_migrations (migration_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (ENERGY_INTELLIGENCE_MIGRATION_ID,),
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
            cur.execute("SELECT count(*) FROM energy_research_leads")
            energy_research_lead_count = int(cur.fetchone()[0])
    return {
        "migration_id": MIGRATION_ID,
        "energy_intelligence_migration_id": ENERGY_INTELLIGENCE_MIGRATION_ID,
        "canonical_database": "active_vercel_database_url",
        "required_tables_present": table_count,
        "active_usd_accounts": active_usd_accounts,
        "energy_research_lead_count": energy_research_lead_count,
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
