from __future__ import annotations

import os
from collections import Counter, defaultdict

import httpx
from fastapi import FastAPI, HTTPException

app = FastAPI(title="SAHJONY Supabase Record Registry", version="1.1.0", docs_url=None, redoc_url=None)


def _supabase_config() -> tuple[str, str]:
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )
    return base, key


def _domain(logical_table: str) -> str:
    name = (logical_table or "").lower()
    if any(x in name for x in ("customer", "buyer", "prospect", "intake", "rfq", "lead")):
        return "buyers_and_demand"
    if any(x in name for x in ("supplier", "vendor", "manufacturer", "sourcing", "quote")):
        return "suppliers_and_quotes"
    if any(x in name for x in ("partner", "referral", "affiliate")):
        return "partners_and_referrals"
    if any(x in name for x in ("shipment", "logistic", "freight", "carrier", "port")):
        return "logistics"
    if any(x in name for x in ("compliance", "kyb", "ofac", "screen", "sanction")):
        return "compliance_and_kyb"
    if any(x in name for x in ("payment", "ledger", "invoice", "reconciliation", "revenue", "finance")):
        return "payments_and_revenue"
    if any(x in name for x in ("deal", "commercial", "managed_trade", "intermediary", "trade_case")):
        return "deals_and_trade_execution"
    if any(x in name for x in ("document", "dossier", "evidence", "certificate")):
        return "documents_and_evidence"
    if any(x in name for x in ("message", "email", "whatsapp", "communication", "voice")):
        return "communications"
    if any(x in name for x in ("country", "cuba", "mipyme", "market", "registry")):
        return "market_and_country_intelligence"
    return "other_operational_records"


@app.get("/crm/record-registry/summary")
async def summary():
    base, key = _supabase_config()
    if not base or not key:
        raise HTTPException(503, "Supabase canonical backend is not configured")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    url = f"{base}/rest/v1/sahjony_trade_records"
    rows: list[dict] = []
    offset = 0
    page_size = 1000
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            response = await client.get(
                url,
                headers=headers,
                params={
                    "select": "logical_table,record_key",
                    "order": "logical_table.asc",
                    "limit": str(page_size),
                    "offset": str(offset),
                },
            )
            response.raise_for_status()
            batch = response.json() if response.content else []
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
            if offset >= 100000:
                break
    table_counts = Counter(str(r.get("logical_table") or "UNCLASSIFIED") for r in rows)
    domain_counts: Counter[str] = Counter()
    domain_tables: dict[str, list[dict]] = defaultdict(list)
    for table, count in sorted(table_counts.items(), key=lambda item: (-item[1], item[0])):
        domain = _domain(table)
        domain_counts[domain] += count
        domain_tables[domain].append({"logical_table": table, "count": count})
    unclassified = table_counts.get("UNCLASSIFIED", 0)
    return {
        "status": "ok" if not unclassified else "needs_review",
        "canonical_backend": "supabase",
        "physical_table": "sahjony_trade_records",
        "total_records": len(rows),
        "logical_table_count": len(table_counts),
        "unclassified_records": unclassified,
        "domain_counts": dict(sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))),
        "logical_tables": [
            {"logical_table": table, "count": count, "domain": _domain(table)}
            for table, count in sorted(table_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "domain_tables": dict(domain_tables),
        "pii_exposed": False,
        "commercial_stage_mutated": False,
    }
