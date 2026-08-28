from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Cuba Logistics Network OS", version="1.0.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"

PROVINCES = [
    "Pinar del Río", "Artemisa", "La Habana", "Mayabeque", "Matanzas",
    "Villa Clara", "Cienfuegos", "Sancti Spíritus", "Ciego de Ávila",
    "Camagüey", "Las Tunas", "Holguín", "Granma", "Santiago de Cuba",
    "Guantánamo", "Isla de la Juventud",
]

LOGISTICS_TERMS = (
    "logistic", "logística", "aduana", "aduanal", "transitari", "freight", "cargo",
    "paquete", "distrib", "mariel", "contenedor", "container", "almac", "warehouse",
    "last mile", "última milla", "puerta a puerta", "door-to-door", "transport",
)


def _db_url() -> str:
    for key in ("DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL", "NEON_POSTGRES_URL", "POSTGRES_PRISMA_URL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _blob(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(k) or "") for k in (
        "buyer_company", "buyer_name", "opportunity_title", "product_category",
        "product_description", "evidence_summary", "next_action", "destination",
        "verification_status", "qualification_stage", "risk_level",
    )).lower()


def _is_logistics(row: dict[str, Any]) -> bool:
    text = _blob(row)
    return any(term in text for term in LOGISTICS_TERMS)


def _capability(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def _project(row: dict[str, Any]) -> dict[str, Any]:
    text = _blob(row)
    risk = str(row.get("risk_level") or "VERIFY").upper()
    verified = "verified" in str(row.get("verification_status") or "").lower()
    capabilities = {
        "national_distribution": _capability(text, "todas las provincias", "nacional", "168 municipios", "todo el territorio", "nationwide"),
        "customs_clearance": _capability(text, "aduana", "aduanal", "customs"),
        "container_handling": _capability(text, "contenedor", "container", "extracción", "devolución del contenedor"),
        "mariel_port": _capability(text, "mariel"),
        "air_cargo": _capability(text, "aérea", "aereo", "air cargo", "aerovaradero"),
        "warehousing": _capability(text, "almac", "warehouse", "depósito", "deposito"),
        "last_mile": _capability(text, "última milla", "last mile", "puerta a puerta", "door-to-door", "entrega"),
        "commercial_b2b": _capability(text, "b2b", "comercial", "pallet", "mayorista", "carga comercial"),
    }
    weights = {
        "national_distribution": 20, "customs_clearance": 20, "container_handling": 15,
        "mariel_port": 15, "air_cargo": 5, "warehousing": 10, "last_mile": 5,
        "commercial_b2b": 5,
    }
    score = sum(weights[key] for key, value in capabilities.items() if value) + (5 if verified else 0)
    blockers: list[str] = []
    if not capabilities["customs_clearance"]:
        blockers.append("Customs-clearance authority/partner not evidenced")
    if not capabilities["commercial_b2b"]:
        blockers.append("Commercial B2B/pallet/container scope not evidenced")
    if not capabilities["container_handling"]:
        blockers.append("Container extraction/return capability not evidenced")
    if not capabilities["national_distribution"]:
        blockers.append("Nationwide province/municipality coverage not evidenced")
    if risk == "CRITICAL":
        score = min(score, 25)
        blockers.insert(0, "Critical sanctions/ownership/compliance review")
    readiness = "ROUTE_CANDIDATE" if score >= 70 and risk != "CRITICAL" else ("PARTIAL_CHAIN" if score >= 40 else "RESEARCH_ONLY")
    return {
        **row,
        "record_type": "CUBA_LOGISTICS_RESEARCH",
        "read_only": True,
        "binding_actions_allowed": False,
        "capabilities": capabilities,
        "route_readiness_score": min(score, 100),
        "route_readiness": readiness,
        "route_blockers": blockers,
        "source_evidence_required": True,
    }


def _physical_rows_sync() -> list[dict[str, Any]]:
    url = _db_url()
    if not url:
        return []
    import psycopg
    from psycopg.rows import dict_row
    query = """
        SELECT * FROM public.external_trade_prospects
        WHERE organization_id = %s
        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        LIMIT 5000
    """
    try:
        with psycopg.connect(url, connect_timeout=10, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(query, (ORG_ID,))
            return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []


async def _all_external_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        logical = await get_backend().select("external_trade_prospects", params={"organization_id": f"eq.{ORG_ID}", "order": "updated_at.desc", "limit": "5000"}) or []
        rows.extend(dict(row) for row in logical)
    except Exception:
        pass
    rows.extend(await asyncio.to_thread(_physical_rows_sync))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("id") or row.get("prospect_id") or row.get("external_reference") or row.get("buyer_company") or row.get("source_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        if _is_logistics(row):
            deduped.append(row)
    return deduped


def _actor(x_role: str | None, authorization: str | None, x_employee_id: str | None) -> dict[str, str]:
    return identity(x_role, authorization, x_employee_id)


@app.get("/cuba-logistics/health")
async def health():
    return {
        "status": "ok",
        "service": "sahjony-cuba-logistics-network-os",
        "mode": "research_and_route_readiness_only",
        "binding_actions_allowed": False,
        "booking_allowed": False,
        "payment_authorization_allowed": False,
        "counterparty_disclosure_allowed": False,
        "province_count": 16,
        "fail_closed": True,
    }


@app.get("/cuba-logistics/network")
async def network(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _actor(x_role, authorization, x_employee_id)
    rows = [_project(row) for row in await _all_external_rows()]
    rows.sort(key=lambda row: (int(row.get("route_readiness_score") or 0), str(row.get("updated_at") or row.get("created_at") or "")), reverse=True)
    route_candidates = [row for row in rows if row["route_readiness"] == "ROUTE_CANDIDATE"]
    customs_nodes = [row for row in rows if row["capabilities"]["customs_clearance"]]
    national_nodes = [row for row in rows if row["capabilities"]["national_distribution"]]
    return {
        "status": "ok",
        "scope": actor["role"],
        "research_only": True,
        "count": len(rows),
        "route_candidate_count": len(route_candidates),
        "customs_node_count": len(customs_nodes),
        "national_distribution_count": len(national_nodes),
        "operators": rows,
    }


@app.get("/cuba-logistics/route-blueprint")
async def route_blueprint(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _actor(x_role, authorization, x_employee_id)
    rows = [_project(row) for row in await _all_external_rows()]
    return {
        "status": "ok",
        "corridor": "Houston/New Orleans → Mariel/Havana → customs release → national distribution → buyer",
        "stages": [
            {"stage": 1, "name": "Origin supplier/exporter", "gate": "KYB + product/export eligibility + executable commercial terms"},
            {"stage": 2, "name": "Ocean carrier", "gate": "Firm rate + booking only after owner-approved transaction"},
            {"stage": 3, "name": "Cuban importer/consignee", "gate": "Legal importer authority + end-user/ownership/compliance"},
            {"stage": 4, "name": "Customs/transitary node", "gate": "Authority + declaration + permits + duties/taxes + inspection as applicable"},
            {"stage": 5, "name": "Container release/extraction", "gate": "Released cargo + terminal charges + equipment-return plan"},
            {"stage": 6, "name": "National distributor", "gate": "B2B cargo scope + warehouse/fleet + province/municipality coverage + insurance"},
            {"stage": 7, "name": "Buyer delivery", "gate": "Proof of delivery + documentary reconciliation"},
        ],
        "customs_candidates": [row for row in rows if row["capabilities"]["customs_clearance"]],
        "distribution_candidates": [row for row in rows if row["capabilities"]["national_distribution"] or row["capabilities"]["last_mile"]],
        "release_policy": "fail_closed",
        "binding_actions_allowed": False,
    }


@app.get("/cuba-logistics/coverage")
async def coverage(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _actor(x_role, authorization, x_employee_id)
    rows = [_project(row) for row in await _all_external_rows()]
    national = [row.get("buyer_company") or row.get("buyer_name") or row.get("opportunity_title") for row in rows if row["capabilities"]["national_distribution"]]
    return {
        "status": "ok",
        "coverage_basis": "Public evidence only; national claims require written commercial verification before use.",
        "provinces": [{"province": province, "candidate_operators": national} for province in PROVINCES],
        "province_count": len(PROVINCES),
    }


@app.get("/cuba-logistics/quote-requirements")
async def quote_requirements(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _actor(x_role, authorization, x_employee_id)
    return {
        "status": "ok",
        "non_binding_template": True,
        "required_inputs": [
            "Legal importer/consignee and tax/registry identifiers",
            "Commodity, HS code, country of origin, gross/net weight and packaging",
            "Container type, count, reefer requirements and dangerous-goods status",
            "Port/terminal and bill-of-lading details",
            "Required sanitary, veterinary, phytosanitary or technical permits",
            "Customs agency/transitary scope and authorization",
            "Destination handling, terminal, inspection, storage/demurrage assumptions",
            "Container extraction and empty-return charges",
            "Warehouse, pallet handling and cross-dock charges",
            "Delivery province, municipality and exact commercial delivery point",
            "Truck/reefer requirements, transit time, insurance and proof of delivery",
            "Quote validity, taxes, currency, payment terms and exclusions",
        ],
        "economics_formula": "supplier + origin + ocean + destination/customs + inland distribution + compliance/inspection + protected SAHJONY economics = buyer landed price",
        "owner_approval_required_for": ["booking", "contract", "payment", "binding quote", "protected counterparty disclosure"],
    }
