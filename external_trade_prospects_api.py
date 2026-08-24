from __future__ import annotations

from fastapi import FastAPI, Header

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY External Trade Prospects", version="1.0.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


def priority_tier(row: dict) -> str:
    title = str(row.get("opportunity_title") or "").lower()
    risk = str(row.get("risk_level") or "medium").lower()
    quantity = float(row.get("quantity") or 0)
    if "motor" in title or "charger" in title:
        return "A"
    if "rmg-380" in title or "lsfo" in title:
        return "A-POTENTIAL"
    if quantity >= 25 and risk != "high":
        return "A-"
    return "B"


@app.get("/crm/external-prospects/health")
async def external_prospects_health():
    return {
        "status": "ok",
        "service": "external-trade-prospects",
        "scope": "research_only",
        "promotion": "fail_closed",
        "customer_intake_isolation": True,
    }


@app.get("/crm/external-prospects")
async def list_external_prospects(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select(
        "external_trade_prospects",
        params={
            "organization_id": f"eq.{ORG_ID}",
            "order": "created_at.desc",
            "limit": "500",
        },
    ) or []
    prospects = []
    for row in rows:
        item = dict(row)
        item["revenue_priority_tier"] = priority_tier(item)
        item["record_type"] = "EXTERNAL_RESEARCH"
        item["customer_intake"] = False
        prospects.append(item)
    return {
        "status": "ok",
        "scope": actor["role"],
        "research_only": True,
        "count": len(prospects),
        "prospects": prospects,
    }
