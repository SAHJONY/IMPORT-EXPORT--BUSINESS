from __future__ import annotations

import secrets
from datetime import datetime, timezone

from insforge_backend import get_backend
from lead_scout_api import LeadScoutIn, fingerprint, opportunity_score, priority


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


CUBA_MIPYME_EXPANSION_LEADS = [
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"SERLOVEM SURL","country":"CU","city_region":"Havana","deal_side":"BOTH","lead_type":"DISTRIBUTOR","product_need_or_offer":"Cuban private-sector trading/import channel with extensive observed customs activity across general goods and 2026 gasoline/diesel tank movements; high-priority fuel and general-goods qualification target.","source_url":"https://importkey.com/i/serlovem-surl","source_description":"Current customs-data profile shows hundreds of trade records and August 2026 gasoline/diesel-related tank movements.","evidence_urls":["https://importkey.com/i/serlovem-surl","https://www.trademo.com/cuba/buyers/hscode/340250"],"notes":"CUBA_PRIVATE_SECTOR; FUEL + GENERAL_GOODS. Enhanced KYB, ownership, end-use, payment-path and transaction-specific BIS/OFAC review required. Customs records do not establish U.S. export eligibility by themselves."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"MIPYME Agencia Importadora Caribe SURL","country":"CU","city_region":"Miramar, Havana","deal_side":"BUYER","lead_type":"BUYER","product_need_or_offer":"Cuban MIPYME/import agency with verified multi-country import history; candidate buyer/import channel for food, household, construction and other eligible general goods.","source_url":"https://www.trademo.com/companies/mipyme-agencia-importadora-caribe-surl/31629319","source_description":"Trade-data profile reports 23 import shipments and sourcing from Colombia, Ecuador and Brazil.","evidence_urls":["https://www.trademo.com/companies/mipyme-agencia-importadora-caribe-surl/31629319","https://importkey.com/i/mipyme-agencia-importadora-caribe"],"notes":"GENERAL_GOODS IMPORTER. Verify ownership, current product demand, import authority and U.S.-origin eligibility by item/end use."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"MIPYME Impexport S.U.R.L.","country":"CU","city_region":"Miramar, Havana","deal_side":"BUYER","lead_type":"BUYER","product_need_or_offer":"Cuban private import/export company appearing as an active buyer in food/beverage customs categories; candidate general-goods and food importer.","source_url":"https://www.trademo.com/cuba/buyers/hscode/2009","source_description":"Trade-data directory lists MIPYME Impexport S.U.R.L. with substantial shipment activity in HS 2009 and other import categories.","evidence_urls":["https://www.trademo.com/cuba/buyers/hscode/2009","https://www.trademo.com/cuba/buyers/hscode/020714/2"],"notes":"GENERAL_GOODS/FOOD BUYER. Verify private ownership, current buying categories and permitted export path."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"Agrimpex Caribe S.U.R.L.","country":"CU","city_region":"Havana","deal_side":"BUYER","lead_type":"BUYER","product_need_or_offer":"Cuban private-sector import prospect with observed food/agricultural shipment activity; candidate buyer for eligible food and agricultural goods.","source_url":"https://www.trademo.com/cuba/buyers/hscode/020714/2","source_description":"Trade-data directory identifies Agrimpex Caribe S.U.R.L. as a Cuban buyer/importer with observed shipments.","evidence_urls":["https://www.trademo.com/cuba/buyers/hscode/020714/2"],"notes":"AGRI/FOOD BUYER. Verify current corporate status, ownership and product needs before outreach."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"Supermax Mayorista","country":"CU","city_region":"Cerro, Havana","deal_side":"BUYER","lead_type":"DISTRIBUTOR","product_need_or_offer":"Cuban wholesale/import prospect appearing in food shipment records; candidate buyer/distributor for eligible packaged food and general merchandise.","source_url":"https://www.trademo.com/cuba/buyers/hscode/020712/2","source_description":"Trade-data directory lists Supermax Mayorista among Cuban buyers/importers in food categories.","evidence_urls":["https://www.trademo.com/cuba/buyers/hscode/020712/2"],"notes":"WHOLESALE GENERAL GOODS. Verify legal entity, private-sector status and current procurement categories."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"Impocaribe MIPYME Agencia Importadora","country":"CU","deal_side":"BUYER","lead_type":"BUYER","product_need_or_offer":"Cuban MIPYME/import agency appearing in cleaning/household goods customs categories; candidate buyer for eligible general merchandise and supplies.","source_url":"https://www.trademo.com/cuba/buyers/hscode/340250","source_description":"Trade-data directory lists Impocaribe MIPYME Agencia Importadora with observed shipments in cleaning-product categories.","evidence_urls":["https://www.trademo.com/cuba/buyers/hscode/340250"],"notes":"GENERAL_GOODS/CLEANING SUPPLIES. Verify current demand, ownership and export eligibility."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"Landservi SURL","country":"CU","city_region":"Sancti Spiritus","deal_side":"BUYER","lead_type":"BUYER","product_need_or_offer":"Cuban private MIPYME reported in U.S.-licensed procurement activity supplying foreign embassies in Havana; potential institutional general-goods buyer subject to enhanced due diligence.","source_url":"https://www.asere.com/mipyme-de-sancti-spiritus-bajo-la-lupa-por-compras-millonarias-en-hialeah/","source_description":"2026 reporting describes Landservi SURL and U.S. export-license-related procurement activity for embassy supply.","evidence_urls":["https://www.asere.com/mipyme-de-sancti-spiritus-bajo-la-lupa-por-compras-millonarias-en-hialeah/","https://www.periodicocubano.com/mipyme-de-sancti-spiritus-desata-sospecha-por-compras-millonarias-en-eeuu-para-21-embajadas-en-la-habana/"],"notes":"ENHANCED_DD_REQUIRED. Reported transaction values/relationships are unusual and must not be treated as verified financial history without primary documents. Screen ownership, end users, licenses and counterparties."},
    {"scout_name":"SAHJONY CEO Cuba Private Sector","business_name":"SOLIMPORT AUTOMOTRIZ S.U.R.L.","country":"CU","deal_side":"BUYER","lead_type":"DISTRIBUTOR","product_need_or_offer":"Cuban SURL authorized in 2026 regulation to commercialize motorcycles, tricycles, engines, engine blocks and related mobility products in convertible currency; candidate mobility/general-goods buyer.","source_url":"https://www.directoriocubano.com/servicios/gaceta-oficial/2026/ordinaria/65/","source_description":"Official-gazette reproduction identifies SOLIMPORT AUTOMOTRIZ S.U.R.L. and approved product categories.","evidence_urls":["https://www.directoriocubano.com/servicios/gaceta-oficial/2026/ordinaria/65/"],"notes":"MOBILITY/GENERAL GOODS. Verify private ownership, current purchasing authority and product-specific U.S. export eligibility."},
]


async def ensure_cuba_mipyme_expansion_seed() -> dict:
    backend = get_backend()
    inserted = 0
    already_present = 0
    failures: list[dict] = []
    for raw in CUBA_MIPYME_EXPANSION_LEADS:
        try:
            model = LeadScoutIn(**raw, consent_to_business_contact=False)
            fp = fingerprint(model)
            existing = await backend.select("lead_scout_leads", params={"fingerprint": f"eq.{fp}", "limit": "1"}) or []
            if existing:
                already_present += 1
                continue
            score = opportunity_score(model)
            ts = now()
            lead_id = f"lsl_{secrets.token_urlsafe(10)}"
            row = {
                "lead_id": lead_id, "fingerprint": fp, "scout_name": model.scout_name.strip(),
                "scout_code": "CEO-CUBA-MIPYME-EXPANSION", "scout_contact": None,
                "business_name": model.business_name.strip(), "contact_name": (model.contact_name or "").strip() or None,
                "email": model.email, "phone": (model.phone or "").strip() or None, "country": model.country.strip(),
                "city_region": (model.city_region or "").strip() or None, "deal_side": model.deal_side, "lead_type": model.lead_type,
                "product_need_or_offer": model.product_need_or_offer.strip(), "estimated_deal_value": model.estimated_deal_value,
                "currency": model.currency, "source_url": (model.source_url or "").strip() or None,
                "source_description": (model.source_description or "").strip() or None, "evidence_urls": model.evidence_urls,
                "notes": (model.notes or "").strip() or None, "consent_to_business_contact": False,
                "opportunity_score": score, "qualification_priority": priority(score), "status": "NEW",
                "duplicate_candidate": False, "duplicate_of_lead_id": None,
                "referral_credit_status": "NOT_APPLICABLE", "commission_status": "NOT_APPLICABLE",
                "created_at": ts, "updated_at": ts,
            }
            await backend.insert("lead_scout_leads", row)
            await backend.insert("lead_scout_audit", {
                "event_id": f"lsa_{secrets.token_urlsafe(10)}", "lead_id": lead_id,
                "event_type": "ceo_cuba_mipyme_expansion_ingested",
                "summary": "Cuba private-sector prospect ingested into governed CRM",
                "payload": {"score": score, "priority": priority(score), "source_url": model.source_url, "automatic_promotion": False},
                "created_at": ts,
            })
            inserted += 1
        except Exception as exc:
            failures.append({"business_name": raw.get("business_name"), "error": type(exc).__name__})
    return {"status":"ok" if not failures else "partial","expected":len(CUBA_MIPYME_EXPANSION_LEADS),"inserted":inserted,"already_present":already_present,"failed":len(failures),"failures":failures,"automatic_deal_promotion":False,"automatic_outreach_authority":False}
