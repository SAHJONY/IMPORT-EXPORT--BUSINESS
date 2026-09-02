from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI

from insforge_backend import get_backend

app = FastAPI(title="SAHJONY LATAM Trade Research", version="1.0.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


RESEARCH = [
    {
        "prospect_id":"latam_colombia_undp_machinery_fertilizer_20260904",
        "organization_id":ORG_ID,
        "opportunity_title":"Colombia UNDP — machinery, tools, inputs and fertilizers",
        "product_category":"Agricultural machinery / tools / fertilizers",
        "product_description":"UNDP procurement for machinery, tools, various inputs and fertilizers for productive projects in Honda, Tolima.",
        "buyer_company":"United Nations Development Programme (UNDP) Colombia",
        "buyer_country":"CO",
        "destination":"Honda, Tolima, Colombia",
        "verification_status":"official_public_procurement",
        "qualification_stage":"research_active_procurement",
        "risk_level":"medium",
        "confidence":92,
        "opportunity_score":84,
        "revenue_priority_tier":"A",
        "source_url":"https://www.ungm.org/Public/Notice/311004",
        "evidence_summary":"Official UNGM RFQ UNDP-COL-03399,1; published 14-Aug-2026; deadline 04-Sep-2026.",
        "supplier_outreach":[
            {"supplier":"AGCO","status":"SUPPLIER_CANDIDATE","source":"https://www.agcocorp.com/us/en/home/about-us/manufacturing.html"},
            {"supplier":"Kirloskar Americas Corporation","status":"SUPPLIER_CANDIDATE","source":"https://www.kirloskarlimitless.com/en/global/america"},
            {"supplier":"WeCan Global America","status":"SUPPLIER_CANDIDATE","source":"https://wecan-america.com/"},
            {"supplier":"Nutrien","status":"SUPPLIER_CANDIDATE","source":"https://www.nutrien.com/"}
        ],
        "next_action":"Review exact line items and eligibility immediately; only then request non-binding supplier pricing and confirm whether SAHJONY can participate directly or via an eligible local prime.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"No supplier net, award value or protected SAHJONY compensation is evidenced yet.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
    {
        "prospect_id":"latam_colombia_fao_forestry_equipment_20260910",
        "organization_id":ORG_ID,
        "opportunity_title":"Colombia FAO — forestry machinery and equipment",
        "product_category":"Forestry machinery / industrial tools",
        "product_description":"FAO invitation to bid for forestry machinery and equipment for La Tagua, Puerto Leguizamo, Putumayo.",
        "buyer_company":"FAO Colombia",
        "buyer_country":"CO",
        "destination":"La Tagua, Puerto Leguizamo, Putumayo, Colombia",
        "verification_status":"official_public_procurement",
        "qualification_stage":"research_active_procurement",
        "risk_level":"medium",
        "confidence":94,
        "opportunity_score":87,
        "revenue_priority_tier":"A",
        "source_url":"https://www.ungm.org/Public/Notice/311966",
        "evidence_summary":"Official FAO UNGM tender 2026/FLCOL/FLCOL/138048; published 21-Aug-2026; deadline 10-Sep-2026.",
        "supplier_outreach":[
            {"supplier":"Husqvarna Colombia","status":"SUPPLIER_CANDIDATE","source":"https://www.husqvarna.com/co/"},
            {"supplier":"The Stumpster Co.","status":"SUPPLIER_CANDIDATE","source":"https://www.stumpster.com/"}
        ],
        "next_action":"Pull specifications and lot structure; match exact machinery models and certifications before any quote request.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"Exact equipment list, supplier net and compensation protection remain pending.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
    {
        "prospect_id":"latam_guatemala_fao_wildfire_ppe_20260908",
        "organization_id":ORG_ID,
        "opportunity_title":"Guatemala FAO — wildfire personal protective equipment",
        "product_category":"Safety / PPE / firefighting",
        "product_description":"FAO procurement for personal protective equipment for forest fires.",
        "buyer_company":"FAO Guatemala",
        "buyer_country":"GT",
        "destination":"Guatemala",
        "verification_status":"official_public_procurement",
        "qualification_stage":"research_active_procurement",
        "risk_level":"medium",
        "confidence":95,
        "opportunity_score":86,
        "revenue_priority_tier":"A",
        "source_url":"https://www.ungm.org/Public/Notice/311341",
        "evidence_summary":"Official FAO UNGM tender 2026/FLGUA/FLGUA/137999; published 18-Aug-2026; deadline 08-Sep-2026.",
        "supplier_outreach":[
            {"supplier":"MSA Safety","status":"SUPPLIER_CANDIDATE","source":"https://us.msasafety.com/globe?locale=en"},
            {"supplier":"Husqvarna Guatemala","status":"SUPPLIER_CANDIDATE","source":"https://www.husqvarna.com/gt/industries-and-solutions/forestry/"}
        ],
        "next_action":"Review required certifications, sizing, quantities and delivery terms; source only compliant PPE lines.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"Tender quantities and supplier pricing are not yet extracted.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
    {
        "prospect_id":"latam_guatemala_fao_fire_alert_kits_20260908",
        "organization_id":ORG_ID,
        "opportunity_title":"Guatemala FAO — 24 early-warning system kits for fire brigades",
        "product_category":"Safety electronics / emergency response equipment",
        "product_description":"FAO procurement for 24 early-warning system kits for integrated fire-management brigades.",
        "buyer_company":"FAO Guatemala",
        "buyer_country":"GT",
        "destination":"Guatemala",
        "quantity":24,
        "unit":"kits",
        "verification_status":"official_public_procurement",
        "qualification_stage":"research_active_procurement",
        "risk_level":"medium",
        "confidence":95,
        "opportunity_score":84,
        "revenue_priority_tier":"A",
        "source_url":"https://www.ungm.org/Public/Notice/311342",
        "evidence_summary":"Official FAO UNGM tender 2026/FLGUA/FLGUA/138000; published 18-Aug-2026; deadline 08-Sep-2026.",
        "supplier_outreach":[
            {"supplier":"MSA Safety","status":"SUPPLIER_CANDIDATE","source":"https://us.msasafety.com/"}
        ],
        "next_action":"Extract technical BOM for each kit and identify exact detection/communications components before supplier outreach.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"Technical bill of materials and supplier net pricing remain pending.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
    {
        "prospect_id":"latam_honduras_fao_industrial_gases_20260911",
        "organization_id":ORG_ID,
        "opportunity_title":"Honduras FAO — industrial gases in cylinders",
        "product_category":"Industrial gases / cylinders",
        "product_description":"FAO tender for cylinder gas supply, cylinder rental and replenishment according to consumption.",
        "buyer_company":"FAO Honduras",
        "buyer_country":"HN",
        "destination":"Honduras",
        "verification_status":"official_public_procurement",
        "qualification_stage":"research_active_procurement",
        "risk_level":"medium",
        "confidence":96,
        "opportunity_score":89,
        "revenue_priority_tier":"A",
        "source_url":"https://www.ungm.org/Public/Notice/311113",
        "evidence_summary":"Official FAO UNGM tender 2026/FLHON/FLHON/137968; published 14-Aug-2026; deadline 11-Sep-2026.",
        "supplier_outreach":[
            {"supplier":"INFRA de Honduras","status":"LOCAL_SUPPLIER_CANDIDATE","source":"https://www.infradehonduras.com.hn/"}
        ],
        "next_action":"Extract gas types, cylinder sizes, expected consumption, rental conditions and delivery locations; verify supplier eligibility before any pricing request.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"Consumption profile and supplier commercial terms are pending.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
    {
        "prospect_id":"latam_colombia_construction_framework_20260828",
        "organization_id":ORG_ID,
        "opportunity_title":"Colombia public sector — construction materials and hardware demand",
        "product_category":"Construction materials / hardware",
        "product_description":"Active public-sector demand signal under Colombia's construction-materials and hardware framework; a new order was issued 28-Aug-2026 for COP 88,500,314.",
        "buyer_company":"Colombian public-sector entities via Colombia Compra Eficiente",
        "buyer_country":"CO",
        "destination":"Colombia",
        "verification_status":"official_public_purchase_order",
        "qualification_stage":"research_market_demand",
        "risk_level":"medium",
        "confidence":93,
        "opportunity_score":78,
        "revenue_priority_tier":"A-",
        "source_url":"https://operaciones.colombiacompra.gov.co/tienda-virtual-del-estado-colombiano/ordenes-compra/168401",
        "evidence_summary":"Official purchase order 168401 issued 28-Aug-2026 for construction materials/hardware under the national framework.",
        "supplier_outreach":[
            {"supplier":"Cacique Supply Group LLC","status":"EXPORT_SUPPLIER_CANDIDATE","source":"https://www.caciquesupply.com/"},
            {"supplier":"CEMEX","status":"MANUFACTURER_CANDIDATE","source":"https://www.cemexusa.com/homepage"}
        ],
        "next_action":"Use as a demand signal, not an open RFQ; monitor the replacement framework and identify eligible Colombian prime/distribution partners.",
        "possible_profit_status":"INPUTS_REQUIRED",
        "possible_profit_basis":"This is a market-demand signal, not a currently awarded SAHJONY opportunity.",
        "source_record":"latam_trade_research",
        "created_at":"2026-09-01T23:43:00-05:00",
        "updated_at":now(),
    },
]


async def sync_research() -> dict:
    backend = get_backend()
    inserted = 0
    updated = 0
    failures: list[str] = []
    for raw in RESEARCH:
        try:
            existing = await backend.select("external_trade_prospects", params={"prospect_id":f"eq.{raw['prospect_id']}","limit":"1"}) or []
            row = dict(existing[0]) if existing else {}
            row.update(raw)
            row["updated_at"] = now()
            await backend.insert("external_trade_prospects", row)
            if existing: updated += 1
            else: inserted += 1
        except Exception as exc:
            failures.append(f"{raw['prospect_id']}: {type(exc).__name__}: {str(exc)[:160]}")
    return {"status":"ok" if not failures else "partial","expected":len(RESEARCH),"inserted":inserted,"updated":updated,"failed":len(failures),"failures":failures,"canonical_backend":"supabase","research_only":True}


@app.get("/crm/latam-trade-research/health")
async def health():
    return await sync_research()


@app.get("/crm/latam-trade-research")
async def list_research():
    sync = await sync_research()
    return {"status":sync["status"],"research_only":True,"qualified_demand":False,"firm_quotation":False,"contracted_transaction":False,"records":RESEARCH,"sync":sync}
