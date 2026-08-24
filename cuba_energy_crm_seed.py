from __future__ import annotations

import secrets
from datetime import datetime, timezone

from insforge_backend import get_backend
from lead_scout_api import LeadScoutIn, fingerprint, opportunity_score, priority


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


CUBA_ENERGY_CRM_LEADS = [
    {
        "scout_name": "SAHJONY CEO Cuba Energy Origination",
        "business_name": "Grupo Nueva Vision",
        "phone": "+53 54421417",
        "country": "CU",
        "city_region": "Diez de Octubre, Havana",
        "deal_side": "BUYER",
        "lead_type": "BUYER",
        "product_need_or_offer": "Cuban private MIPYME publicly advertising installation of photovoltaic panels, inverters, EcoFlow systems, refrigeration and electrical services for households and businesses in Havana; energy-sector prospect for equipment sourcing and commercial partnerships.",
        "source_url": "https://itencel.com/anuncio/instalacion-paneles-solares-y-servicios-de-clima-y-refrigeracion/",
        "source_description": "Current public commercial listing identifying Grupo Nueva Vision as a MIPYME providing solar and refrigeration services in Havana.",
        "evidence_urls": [
            "https://itencel.com/anuncio/instalacion-paneles-solares-y-servicios-de-clima-y-refrigeracion/",
            "https://www.revolico.com/item/instalacion-paneles-inversor-ecoflow-54746988"
        ],
        "notes": "CUBA_ENERGY; ENERGY_ADJACENT. Public contact visible. Verify corporate registration, ownership, current demand and sanctions/export-control eligibility before commercial commitment. Not a crude-oil lead and not automatically a gasoline/diesel buyer.",
    },
    {
        "scout_name": "SAHJONY CEO Cuba Energy Origination",
        "business_name": "Fujian Trebor Trading Company",
        "country": "CN",
        "city_region": "Representation reported in Miramar, Havana, Cuba",
        "deal_side": "SELLER",
        "lead_type": "SUPPLIER",
        "product_need_or_offer": "Foreign fuel supply channel publicly reported offering gasoline and diesel to Cuban MIPYMES in 25,000-liter lots, with commercial activity in Havana. Candidate Cuba-energy market-intelligence/supplier lead subject to enhanced KYB, origin verification and U.S. sanctions/export-control review.",
        "source_url": "https://www.14ymedio.com/cuba/pese-cerco-energetico-impuesto-ee_1_1123892.html",
        "source_description": "Public reporting identifies Fujian Trebor Trading Company as offering gasoline and diesel to Cuban private businesses in 25,000-liter lots.",
        "evidence_urls": [
            "https://www.14ymedio.com/cuba/pese-cerco-energetico-impuesto-ee_1_1123892.html",
            "https://www.cibercuba.com/noticias/2026-02-23-u1-e129488-s27061-nid321483-empresa-china-cuba-importa-combustible-venta-dolares"
        ],
        "notes": "CUBA_ENERGY; FUEL_SUPPLY_CHANNEL; ENHANCED_KYB_REQUIRED. Do not infer U.S.-law eligibility or product origin from media claims. No binding outreach, payment, shipment or deal release without legal/compliance review and verified counterparty documentation.",
    },
]


async def ensure_cuba_energy_crm_seed() -> dict:
    backend = get_backend()
    inserted = 0
    already_present = 0
    failures: list[dict] = []

    for payload in CUBA_ENERGY_CRM_LEADS:
        try:
            model = LeadScoutIn(**payload)
            fp = fingerprint(model)
            existing = await backend.select('lead_scout_leads', params={'fingerprint': f'eq.{fp}', 'limit': '1'}) or []
            if existing:
                already_present += 1
                continue

            score = opportunity_score(model)
            lead_id = f'lsl_{secrets.token_urlsafe(10)}'
            ts = now()
            row = {
                'lead_id': lead_id,
                'fingerprint': fp,
                'scout_name': model.scout_name.strip(),
                'scout_code': 'CEO-CUBA-ENERGY',
                'scout_contact': None,
                'business_name': model.business_name.strip(),
                'contact_name': (model.contact_name or '').strip() or None,
                'email': model.email,
                'phone': (model.phone or '').strip() or None,
                'country': model.country.strip(),
                'city_region': (model.city_region or '').strip() or None,
                'deal_side': model.deal_side,
                'lead_type': model.lead_type,
                'product_need_or_offer': model.product_need_or_offer.strip(),
                'estimated_deal_value': model.estimated_deal_value,
                'currency': model.currency,
                'source_url': (model.source_url or '').strip() or None,
                'source_description': (model.source_description or '').strip() or None,
                'evidence_urls': model.evidence_urls,
                'notes': (model.notes or '').strip() or None,
                'consent_to_business_contact': False,
                'opportunity_score': score,
                'qualification_priority': priority(score),
                'status': 'NEW',
                'duplicate_candidate': False,
                'duplicate_of_lead_id': None,
                'referral_credit_status': 'NOT_APPLICABLE',
                'commission_status': 'NOT_APPLICABLE',
                'country_department': model.country.strip().upper(),
                'lead_search_job_id': None,
                'created_at': ts,
                'updated_at': ts,
            }
            await backend.insert('lead_scout_leads', row)
            await backend.insert('lead_scout_audit', {
                'event_id': f'lsa_{secrets.token_urlsafe(10)}',
                'lead_id': lead_id,
                'event_type': 'ceo_cuba_energy_seed_ingested',
                'summary': 'CEO Cuba Energy prospect added to governed CRM',
                'payload': {
                    'score': score,
                    'priority': priority(score),
                    'automatic_deal_promotion': False,
                    'automatic_outreach_authority': False,
                },
                'created_at': ts,
            })
            inserted += 1
        except Exception as exc:
            failures.append({'business_name': payload.get('business_name'), 'error': type(exc).__name__})

    return {
        'status': 'ok' if not failures else 'partial',
        'expected': len(CUBA_ENERGY_CRM_LEADS),
        'inserted': inserted,
        'already_present': already_present,
        'failed': len(failures),
        'failures': failures,
        'automatic_deal_promotion': False,
        'automatic_outreach_authority': False,
    }
