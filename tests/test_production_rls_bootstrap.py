from production_rls_bootstrap import (
    MIGRATION_ID,
    RLS_DDL,
    _REQUIRED_FUNCTIONS,
    _REQUIRED_POLICIES,
    _REQUIRED_TABLES,
)


def test_rls_migration_covers_the_production_evidence_contract():
    assert MIGRATION_ID
    assert len(_REQUIRED_TABLES) == 8
    assert len(_REQUIRED_POLICIES) == 9
    assert len(_REQUIRED_FUNCTIONS) == 4

    sql = RLS_DDL.lower()
    for table in _REQUIRED_TABLES:
        assert f"alter table public.{table} enable row level security" in sql
    for policy in _REQUIRED_POLICIES:
        assert f"create policy {policy}" in sql
    for function in _REQUIRED_FUNCTIONS:
        assert f"function public.{function}" in sql


def test_rls_migration_keeps_authenticated_writes_fail_closed():
    sql = RLS_DDL.lower()
    assert "revoke insert, update, delete on public.app_memberships" in sql
    assert "revoke insert, update, delete on public.shipments" in sql
    assert "revoke insert, update, delete on public.trade_compliance_cases" in sql
    assert "grant select, insert on public.trade_documents" in sql
    assert "trade_documents_customer_insert" in sql
