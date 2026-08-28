from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


MIGRATION_ID = "2026-08-28-neon-participant-domain-rls-v1"

_REQUIRED_TABLES = (
    "app_memberships",
    "business_events",
    "communications",
    "document_movements",
    "shipment_milestones",
    "shipments",
    "trade_compliance_cases",
    "trade_documents",
)

_REQUIRED_POLICIES = (
    "app_memberships_self_select",
    "business_events_read",
    "communications_read",
    "compliance_cases_read",
    "document_movements_read",
    "shipment_milestones_read",
    "shipments_read",
    "trade_documents_customer_insert",
    "trade_documents_read",
)

_REQUIRED_FUNCTIONS = (
    "app_can_access_customer",
    "app_has_role",
    "app_is_internal",
    "requesting_user_id",
)


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


RLS_DDL = r"""
CREATE OR REPLACE FUNCTION public.requesting_user_id() RETURNS text
LANGUAGE sql STABLE
AS $$
  SELECT nullif(auth.user_id()::text, '');
$$;

CREATE OR REPLACE FUNCTION public.app_has_role(required_role text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.app_memberships m
    WHERE m.user_id = public.requesting_user_id()
      AND m.role = required_role
      AND m.status = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION public.app_can_access_customer(target_customer_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT public.app_has_role('owner')
      OR public.app_has_role('employee')
      OR EXISTS (
        SELECT 1
        FROM public.app_memberships m
        WHERE m.user_id = public.requesting_user_id()
          AND m.role = 'customer'
          AND m.status = 'active'
          AND m.customer_id = target_customer_id
      );
$$;

CREATE OR REPLACE FUNCTION public.app_is_internal() RETURNS boolean
LANGUAGE sql STABLE
AS $$
  SELECT public.app_has_role('owner') OR public.app_has_role('employee');
$$;

GRANT USAGE ON SCHEMA public TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.app_memberships FROM authenticated;
GRANT SELECT ON public.app_memberships TO authenticated;

REVOKE UPDATE, DELETE ON public.trade_documents FROM authenticated;
GRANT SELECT, INSERT ON public.trade_documents TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE public.trade_documents_id_seq TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.document_movements FROM authenticated;
GRANT SELECT ON public.document_movements TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.shipments FROM authenticated;
GRANT SELECT ON public.shipments TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.shipment_milestones FROM authenticated;
GRANT SELECT ON public.shipment_milestones TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.trade_compliance_cases FROM authenticated;
GRANT SELECT ON public.trade_compliance_cases TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.business_events FROM authenticated;
GRANT SELECT ON public.business_events TO authenticated;

REVOKE INSERT, UPDATE, DELETE ON public.communications FROM authenticated;
GRANT SELECT ON public.communications TO authenticated;

ALTER TABLE public.app_memberships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS app_memberships_self_select ON public.app_memberships;
CREATE POLICY app_memberships_self_select ON public.app_memberships
FOR SELECT TO authenticated
USING (user_id = public.requesting_user_id());

ALTER TABLE public.trade_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS trade_documents_read ON public.trade_documents;
CREATE POLICY trade_documents_read ON public.trade_documents
FOR SELECT TO authenticated
USING (
  public.app_is_internal()
  OR (customer_visible = true AND public.app_can_access_customer(customer_id))
);

DROP POLICY IF EXISTS trade_documents_customer_insert ON public.trade_documents;
CREATE POLICY trade_documents_customer_insert ON public.trade_documents
FOR INSERT TO authenticated
WITH CHECK (
  public.app_is_internal()
  OR (
    created_by_role = 'customer'
    AND created_by_id = public.requesting_user_id()
    AND public.app_can_access_customer(customer_id)
  )
);

ALTER TABLE public.document_movements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_movements_read ON public.document_movements;
CREATE POLICY document_movements_read ON public.document_movements
FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1
  FROM public.trade_documents d
  WHERE d.document_id = document_movements.document_id
    AND (
      public.app_is_internal()
      OR (d.customer_visible = true AND public.app_can_access_customer(d.customer_id))
    )
));

ALTER TABLE public.shipments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS shipments_read ON public.shipments;
CREATE POLICY shipments_read ON public.shipments
FOR SELECT TO authenticated
USING (
  public.app_is_internal()
  OR (customer_visible = true AND public.app_can_access_customer(customer_id))
);

ALTER TABLE public.shipment_milestones ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS shipment_milestones_read ON public.shipment_milestones;
CREATE POLICY shipment_milestones_read ON public.shipment_milestones
FOR SELECT TO authenticated
USING (EXISTS (
  SELECT 1
  FROM public.shipments s
  WHERE s.shipment_id = shipment_milestones.shipment_id
    AND (
      public.app_is_internal()
      OR (s.customer_visible = true AND public.app_can_access_customer(s.customer_id))
    )
));

ALTER TABLE public.trade_compliance_cases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS compliance_cases_read ON public.trade_compliance_cases;
CREATE POLICY compliance_cases_read ON public.trade_compliance_cases
FOR SELECT TO authenticated
USING (
  public.app_is_internal()
  OR (customer_visible = true AND public.app_can_access_customer(customer_id))
);

ALTER TABLE public.business_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS business_events_read ON public.business_events;
CREATE POLICY business_events_read ON public.business_events
FOR SELECT TO authenticated
USING (
  public.app_has_role('owner')
  OR (public.app_has_role('employee') AND visibility IN ('internal', 'customer'))
  OR (visibility = 'customer' AND public.app_can_access_customer(customer_id))
);

ALTER TABLE public.communications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS communications_read ON public.communications;
CREATE POLICY communications_read ON public.communications
FOR SELECT TO authenticated
USING (
  public.app_is_internal()
  OR public.app_can_access_customer(customer_id)
);

COMMENT ON TABLE public.app_memberships IS
  'Maps verified Neon Auth JWT subject (sub) to application roles and tenant/customer scope. Browser-supplied role or customer identifiers are never trusted as authorization evidence.';
"""


def _evidence(cur: psycopg.Cursor[Any]) -> dict[str, Any]:
    cur.execute(
        """
        SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
        """,
        (list(_REQUIRED_TABLES),),
    )
    table_rows = {row["table_name"]: bool(row["rls_enabled"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT policyname
        FROM pg_policies
        WHERE schemaname = 'public' AND policyname = ANY(%s)
        """,
        (list(_REQUIRED_POLICIES),),
    )
    policies = {row["policyname"] for row in cur.fetchall()}

    cur.execute(
        """
        SELECT DISTINCT p.proname
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = ANY(%s)
        """,
        (list(_REQUIRED_FUNCTIONS),),
    )
    functions = {row["proname"] for row in cur.fetchall()}

    missing_tables = sorted(set(_REQUIRED_TABLES) - set(table_rows))
    rls_not_enabled = sorted(name for name in _REQUIRED_TABLES if not table_rows.get(name))
    missing_policies = sorted(set(_REQUIRED_POLICIES) - policies)
    missing_functions = sorted(set(_REQUIRED_FUNCTIONS) - functions)
    verified = not (missing_tables or rls_not_enabled or missing_policies or missing_functions)
    return {
        "verified": verified,
        "rls_table_count": len(_REQUIRED_TABLES) - len(rls_not_enabled),
        "required_rls_table_count": len(_REQUIRED_TABLES),
        "policy_count": len(_REQUIRED_POLICIES) - len(missing_policies),
        "required_policy_count": len(_REQUIRED_POLICIES),
        "function_count": len(_REQUIRED_FUNCTIONS) - len(missing_functions),
        "required_function_count": len(_REQUIRED_FUNCTIONS),
        "missing_tables": missing_tables,
        "rls_not_enabled": rls_not_enabled,
        "missing_policies": missing_policies,
        "missing_functions": missing_functions,
    }


def _apply() -> dict[str, Any]:
    with psycopg.connect(_database_url(), connect_timeout=10, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') AS role_ready,
                       to_regprocedure('auth.user_id()') IS NOT NULL AS user_id_ready
                """
            )
            prerequisites = cur.fetchone() or {}
            if not prerequisites.get("role_ready") or not prerequisites.get("user_id_ready"):
                return {
                    "completed": False,
                    "migration_id": MIGRATION_ID,
                    "prerequisites": {
                        "authenticated_role": bool(prerequisites.get("role_ready")),
                        "auth_user_id_function": bool(prerequisites.get("user_id_ready")),
                    },
                    "reason": "Neon Data API authentication prerequisites are incomplete",
                    "fail_closed": True,
                    "credential_values_exposed": False,
                }

            cur.execute("SELECT to_regclass('public.sahjony_schema_migrations') AS relation")
            if cur.fetchone()["relation"] is None:
                cur.execute(
                    """
                    CREATE TABLE public.sahjony_schema_migrations (
                        migration_id text PRIMARY KEY,
                        applied_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )

            cur.execute(
                "SELECT 1 FROM public.sahjony_schema_migrations WHERE migration_id = %s",
                (MIGRATION_ID,),
            )
            already_applied = cur.fetchone() is not None
            evidence = _evidence(cur) if already_applied else None
            repaired_existing_migration = bool(already_applied and not evidence["verified"])
            if not already_applied or repaired_existing_migration:
                cur.execute(RLS_DDL)
                if not already_applied:
                    cur.execute(
                        "INSERT INTO public.sahjony_schema_migrations (migration_id) VALUES (%s) ON CONFLICT DO NOTHING",
                        (MIGRATION_ID,),
                    )

            evidence = _evidence(cur)
        conn.commit()

    return {
        "completed": bool(evidence["verified"]),
        "migration_id": MIGRATION_ID,
        "already_applied": already_applied,
        "applied_this_run": not already_applied,
        "repaired_existing_migration": repaired_existing_migration,
        "canonical_database": "active_vercel_database_url",
        "destructive_operations": False,
        "credential_values_exposed": False,
        **evidence,
    }


async def ensure_production_rls() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_apply)
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown RLS migration error"
        return {
            "completed": False,
            "migration_id": MIGRATION_ID,
            "canonical_database": "active_vercel_database_url",
            "reason": f"{type(exc).__name__}: {detail}",
            "fail_closed": True,
            "destructive_operations": False,
            "credential_values_exposed": False,
        }
