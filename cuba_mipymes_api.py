from __future__ import annotations

from fastapi import FastAPI

from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Cuba Private Sector CRM", version="1.2.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"

_PRIVATE_ACTOR_TYPES = {
    "MIPYME_PRIVADA",
    "CNA",
    "EMPRESA_PRIVADA",
    "OTHER_NON_STATE_VERIFIED",
}


def _is_mipyme(row: dict) -> bool:
    src = " ".join([
        str(row.get("source_platform") or ""),
        str(row.get("source_type") or ""),
        str(row.get("source_name") or ""),
        str(row.get("source_provenance") or ""),
        str(row.get("external_reference") or ""),
        str(row.get("evidence_summary") or ""),
    ]).lower()
    name = str(row.get("buyer_company") or row.get("company_name") or row.get("business_name") or "").strip()
    actor_type = str(row.get("actor_type") or "").upper().strip()
    if not name:
        return False
    lowered_name = name.lower()
    if lowered_name.startswith("minjus registro mercantil") or lowered_name.startswith("public mipyme/cna registry"):
        return False
    if actor_type in _PRIVATE_ACTOR_TYPES:
        return True
    return (
        "minjus" in src
        or "registro mercantil" in src
        or "ministerio de economía y planificación" in src
        or "ministerio de economia y planificacion" in src
        or "mep public" in src
        or "actores económicos" in src
        or "actores economicos" in src
        or str(row.get("external_reference") or "").upper().startswith("RM-")
    )


def _public_record(row: dict) -> dict:
    normalized = dict(row)
    normalized.setdefault("buyer_company", row.get("company_name") or row.get("business_name"))
    normalized.setdefault("buyer_country", row.get("country") or "Cuba")
    normalized.setdefault("product_category", row.get("primary_activity") or row.get("activity"))
    normalized.setdefault("product_description", row.get("activity") or row.get("primary_activity"))
    if not normalized.get("destination"):
        municipality = str(row.get("municipality") or "").strip()
        province = str(row.get("province") or "").strip()
        normalized["destination"] = ", ".join(part for part in (municipality, province, "Cuba") if part)
    normalized.setdefault("buyer_contact", row.get("public_phone") or row.get("phone") or row.get("contact"))
    allowed = [
        "id", "prospect_id", "external_reference", "buyer_company", "buyer_name",
        "buyer_country", "buyer_contact", "public_email", "public_phone", "website",
        "actor_type", "province", "municipality", "opportunity_title", "product_category",
        "product_description", "destination", "source_type", "source_platform", "source_name",
        "source_provenance", "source_url", "verification_status", "registry_status",
        "verification_date", "qualification_stage", "risk_level", "import_export_relevance",
        "evidence_summary", "next_action", "created_at", "updated_at",
    ]
    return {k: normalized.get(k) for k in allowed}


async def _records() -> list[dict]:
    backend = get_backend()
    rows = await backend.select(
        "external_trade_prospects",
        params={"organization_id": f"eq.{ORG_ID}", "order": "created_at.desc", "limit": "5000"},
    ) or []
    records = [_public_record(dict(r)) for r in rows if _is_mipyme(dict(r))]
    records.sort(key=lambda r: (str(r.get("buyer_company") or "").casefold(), str(r.get("external_reference") or "")))
    return records


@app.get("/cuba-mipymes-api/health")
@app.get("/crm/cuba-mipymes/health")
async def health():
    records = await _records()
    return {
        "status": "ok",
        "service": "cuba-private-sector-read-only-crm",
        "record_count": len(records),
        "source_scope": "public_registry_and_official_actor_lists_research",
        "binding_actions": False,
    }


@app.get("/cuba-mipymes-api/list")
@app.get("/crm/cuba-mipymes")
@app.get("/crm/cuba-mipymes/list")
async def list_mipymes():
    records = await _records()
    return {
        "status": "ok",
        "count": len(records),
        "records": records,
        "classification": "RESEARCH / VERIFIED PUBLIC SOURCE",
        "notice": "A listed or registered private-sector actor is not a qualified buyer or current RFQ unless separately verified.",
    }
