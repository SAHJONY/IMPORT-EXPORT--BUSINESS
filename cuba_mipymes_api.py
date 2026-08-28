from __future__ import annotations

from fastapi import FastAPI

from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Cuba MIPYME CRM", version="1.1.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


def _is_mipyme(row: dict) -> bool:
    src = " ".join([
        str(row.get("source_platform") or ""),
        str(row.get("source_type") or ""),
        str(row.get("external_reference") or ""),
        str(row.get("evidence_summary") or ""),
    ]).lower()
    name = str(row.get("buyer_company") or "").lower()
    if name.startswith("minjus registro mercantil") or name.startswith("public mipyme/cna registry"):
        return False
    return (
        "minjus" in src
        or "registro mercantil" in src
        or str(row.get("external_reference") or "").upper().startswith("RM-")
    ) and bool(str(row.get("buyer_company") or "").strip())


def _public_record(row: dict) -> dict:
    allowed = [
        "id", "prospect_id", "external_reference", "buyer_company", "buyer_name",
        "buyer_country", "buyer_contact", "opportunity_title", "product_category",
        "product_description", "destination", "source_type", "source_platform",
        "source_url", "verification_status", "qualification_stage", "risk_level",
        "evidence_summary", "next_action", "created_at", "updated_at",
    ]
    return {k: row.get(k) for k in allowed}


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
        "service": "cuba-mipyme-read-only-crm",
        "record_count": len(records),
        "source_scope": "public_registry_research",
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
        "classification": "RESEARCH / VERIFIED PUBLIC REGISTRY",
        "notice": "A registered business is not a qualified buyer or current RFQ unless separately verified.",
    }
