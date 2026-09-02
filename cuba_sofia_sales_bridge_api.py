from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Cuba SOFIA Sales OS Bridge', version='1.0.0', docs_url=None, redoc_url=None)

ORG = 'org_sahjony_global_trade'
CATALOG_PATH = Path(__file__).resolve().parent / 'public' / 'cuba-catalog.json'
PRIVATE_TYPES = {'MIPYME_PRIVADA', 'EMPRESA_PRIVADA', 'OTHER_NON_STATE_VERIFIED'}
CONSENTED = {'CONSENTED'}
WARM_OUTREACH = {'OPTED_IN', 'INBOUND', 'ENGAGED', 'REQUESTED_QUOTE', 'CUSTOMER', 'ACTIVE_CUSTOMER'}
BLOCKED_OUTREACH = {'DO_NOT_AUTO_SEND', 'DO_NOT_CONTACT', 'REVOKED', 'BOUNCED', 'UNSUBSCRIBED'}

CATEGORY_RULES = {
    'alimentos': ['alimento','restaurante','cafeter','panader','agric','mercado','tienda','comida','bebida'],
    'limpieza': ['limpieza','higiene','hotel','hostal','restaurante','cafeter','servicio'],
    'telefonos': ['telefono','celular','movil','reparacion','electronica','tecnologia','informatica'],
    'computadoras': ['computadora','informatica','software','tecnologia','oficina','reparacion'],
    'perfumes': ['belleza','cosmet','peluquer','barber','salon','perfume'],
    'bebes': ['bebe','niño','infantil','familia','tienda'],
    'hogar': ['hogar','mueble','decoracion','tienda','hostal','alojamiento'],
    'construccion': ['construccion','ferreter','electric','plomer','obra','mantenimiento'],
    'industrial': ['industrial','manufactur','taller','maquinaria','produccion'],
    'automotriz': ['auto','vehiculo','taller','transporte','neumatic','mecanica'],
    'solar': ['solar','energia','electric','refrigeracion','hotel','hostal','agric'],
    'salud': ['salud','farmac','clinica','medic','primeros auxilios'],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


def catalog() -> list[dict[str, Any]]:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        return list(data.get('products') or [])
    except Exception:
        return []


def text(row: dict[str, Any]) -> str:
    return ' '.join(str(row.get(k) or '') for k in ('business_name','buyer_company','company_name','primary_activity','activity','product_category','product_description')).lower()


def categories_for(row: dict[str, Any]) -> list[str]:
    blob = text(row)
    scored: list[tuple[int, str]] = []
    for cat, needles in CATEGORY_RULES.items():
        score = sum(1 for n in needles if n in blob)
        if score:
            scored.append((score, cat))
    scored.sort(reverse=True)
    return [c for _, c in scored[:4]] or ['alimentos','limpieza','hogar']


def product_matches(row: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
    cats = categories_for(row)
    products = catalog()
    out = []
    for p in products:
        c = str(p.get('category') or '').lower()
        name = str(p.get('product') or '').lower()
        score = 0
        for cat in cats:
            if cat == 'telefonos' and ('teléfono' in name or 'smartphone' in name or 'tablet' in name or 'accesorios electrónicos' in c): score += 4
            if cat == 'computadoras' and ('computadora' in name or 'laptop' in name or 'impresora' in name or 'oficina' in c): score += 4
            if cat == 'perfumes' and ('perfume' in name or 'cosm' in c or 'belleza' in c): score += 4
            if cat == 'bebes' and ('bebé' in name or 'pañal' in name or 'toallitas' in name): score += 4
            if cat == 'limpieza' and ('limpieza' in c or 'detergente' in name or 'papel' in c): score += 4
            if cat == 'hogar' and ('hogar' in c or 'cocina' in c or 'dormitorio' in c): score += 4
            if cat == 'solar' and ('energía' in c or 'solar' in name): score += 4
            if cat == 'alimentos' and 'alimentos' in c: score += 4
            if cat == 'salud' and ('salud' in c or 'medicamentos' in c): score += 3
            if cat == 'automotriz' and ('automotr' in c or 'vehículo' in name): score += 3
            if cat == 'construccion' and ('constru' in c or 'ferreter' in name): score += 3
            if cat == 'industrial' and ('industrial' in c or 'maquinaria' in name): score += 3
        if score:
            out.append((score, p))
    out.sort(key=lambda x: (-x[0], str(x[1].get('priority') or 'Z'), str(x[1].get('product') or '')))
    return [p for _, p in out[:limit]]


async def cuba_rows(limit: int = 20000) -> list[dict[str, Any]]:
    rows = await get_backend().select('external_trade_prospects', params={'buyer_country':'eq.CU','limit':str(max(1, min(limit, 25000)))}) or []
    return [r for r in rows if str(r.get('actor_type') or '').upper() in PRIVATE_TYPES or str(r.get('country') or '').lower() == 'cuba']


def warm(row: dict[str, Any]) -> bool:
    status = str(row.get('outreach_status') or '').upper()
    consent = str(row.get('consent_status') or '').upper()
    if status in BLOCKED_OUTREACH or consent in {'REVOKED','DO_NOT_CONTACT'}:
        return False
    return consent in CONSENTED or status in WARM_OUTREACH or bool(row.get('consent_to_business_contact'))


def contact_key(row: dict[str, Any]) -> str:
    seed = '|'.join(str(row.get(k) or '') for k in ('prospect_id','buyer_company','business_name','public_email','public_phone'))
    return 'ctc_cu_' + hashlib.sha256(seed.encode()).hexdigest()[:24]


@app.get('/crm/cuba-sales-os/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p.get('configured') else 'configuration_required',
        'service':'cuba-sofia-sales-os-bridge',
        'agent':'SOFIA',
        'crm_connected':bool(p.get('configured')),
        'catalog_connected':CATALOG_PATH.exists(),
        'communication_os_connected':True,
        'autonomy_mode':'AUTONOMOUS_NONBINDING',
        'cold_marketing_autosend':False,
        'consent_gated_marketing':True,
        'binding_actions_allowed':False,
        'protected_counterparty_disclosure':False,
        'cash_collected_metric':True,
        'canonical_backend':'supabase',
    }


@app.get('/crm/cuba-sales-os/opportunities')
async def opportunities(
    authorization: str | None = Header(None, alias='Authorization'),
    limit: int = Query(100, ge=1, le=1000),
    warm_only: bool = False,
):
    owner(authorization)
    rows = await cuba_rows()
    if warm_only:
        rows = [r for r in rows if warm(r)]
    out = []
    for r in rows[:limit]:
        recs = product_matches(r, 8)
        out.append({
            'prospect_id':r.get('prospect_id'),
            'company':r.get('buyer_company') or r.get('business_name') or r.get('company_name'),
            'province':r.get('province'),
            'municipality':r.get('municipality'),
            'activity':r.get('primary_activity') or r.get('activity'),
            'sales_segments':categories_for(r),
            'recommended_products':[{'sku':p.get('sku'),'product':p.get('product'),'category':p.get('category'),'status':p.get('status'),'cta':p.get('cta')} for p in recs],
            'warm_or_consented':warm(r),
            'outreach_status':r.get('outreach_status'),
            'commercial_stage':'RESEARCH' if not warm(r) else 'QUALIFICATION',
            'autonomous_send_allowed':warm(r),
        })
    return {'status':'ok','agent':'SOFIA','sales_os':True,'count':len(out),'opportunities':out,'cold_autosend':False}


@app.post('/crm/cuba-sales-os/sync')
async def sync(
    authorization: str | None = Header(None, alias='Authorization'),
    limit: int = Query(20000, ge=1, le=25000),
):
    owner(authorization)
    rows = (await cuba_rows(limit))[:limit]
    created_contacts = created_endpoints = updated_contacts = 0
    ts = now()
    for r in rows:
        cid = contact_key(r)
        existing = await get_backend().select('communication_contacts', params={'contact_id':f'eq.{cid}','limit':'1'}) or []
        base = {
            'contact_id':cid,
            'display_name':r.get('buyer_company') or r.get('business_name') or r.get('company_name') or 'Cuba private business',
            'company':r.get('buyer_company') or r.get('business_name') or r.get('company_name'),
            'country_code':'CU',
            'preferred_language':'es',
            'lead_id':r.get('prospect_id'),
            'status':'ACTIVE',
            'notes':'SOFIA Sales OS Cuba CRM bridge; research record remains non-qualified until demand is verified.',
            'updated_at':ts,
        }
        if existing:
            await get_backend().patch('communication_contacts', base, params={'contact_id':f'eq.{cid}'})
            updated_contacts += 1
        else:
            base['created_at'] = ts
            base['created_by'] = 'sofia_cuba_sales_bridge'
            await get_backend().insert('communication_contacts', base)
            created_contacts += 1

        endpoint_specs = []
        if r.get('public_phone') or r.get('phone'):
            endpoint_specs.append(('whatsapp', r.get('public_phone') or r.get('phone')))
        if r.get('public_email') or r.get('email'):
            endpoint_specs.append(('email', r.get('public_email') or r.get('email')))
        for channel, dest in endpoint_specs:
            eid = 'cep_' + hashlib.sha256(f'{cid}|{channel}|{dest}'.encode()).hexdigest()[:24]
            ex = await get_backend().select('communication_contact_endpoints', params={'endpoint_id':f'eq.{eid}','limit':'1'}) or []
            consent = 'CONSENTED' if warm(r) else 'UNKNOWN'
            ep = {
                'endpoint_id':eid,'contact_id':cid,'channel':channel,'destination':str(dest),
                'normalized_destination':str(dest).strip().lower() if channel == 'email' else str(dest).strip(),
                'label':'CRM business contact','preferred':channel == 'whatsapp','verified':False,
                'verification_source':r.get('source_platform') or r.get('source_name'),
                'consent_status':consent,
                'consent_source':'CRM consent/engagement evidence' if consent == 'CONSENTED' else 'No marketing consent evidence; research only',
                'do_not_contact':not warm(r) and str(r.get('outreach_status') or '').upper() in BLOCKED_OUTREACH,
                'updated_at':ts,
            }
            if ex:
                await get_backend().patch('communication_contact_endpoints', ep, params={'endpoint_id':f'eq.{eid}'})
            else:
                ep['created_at'] = ts
                await get_backend().insert('communication_contact_endpoints', ep)
                created_endpoints += 1
    return {
        'status':'ok','agent':'SOFIA','crm_rows_seen':len(rows),'contacts_created':created_contacts,
        'contacts_updated':updated_contacts,'endpoints_created':created_endpoints,
        'marketing_policy':'consent-gated; cold registry contacts remain research-only',
        'binding_actions_allowed':False,
    }


@app.post('/crm/cuba-sales-os/activate-consented')
async def activate_consented(
    authorization: str | None = Header(None, alias='Authorization'),
    limit: int = Query(200, ge=1, le=1000),
):
    owner(authorization)
    contacts = await get_backend().select('communication_contacts', params={'country_code':'eq.CU','order':'updated_at.desc','limit':str(limit)}) or []
    created = []
    ts = now()
    for c in contacts:
        cid = str(c.get('contact_id') or '')
        eps = await get_backend().select('communication_contact_endpoints', params={'contact_id':f'eq.{cid}','limit':'100'}) or []
        allowed = [e for e in eps if str(e.get('consent_status') or '').upper() == 'CONSENTED' and not bool(e.get('do_not_contact'))]
        if not allowed:
            continue
        prospect = None
        if c.get('lead_id'):
            rows = await get_backend().select('external_trade_prospects', params={'prospect_id':f"eq.{c.get('lead_id')}",'limit':'1'}) or []
            prospect = rows[0] if rows else None
        recs = product_matches(prospect or c, 6)
        mission_id = 'cmis_sofia_' + secrets.token_urlsafe(10)
        objective = 'Qualify current purchasing needs and offer relevant SAHJONY Cuba catalog products without making binding commitments.'
        if recs:
            objective += ' Suggested categories/products: ' + '; '.join(str(p.get('product')) for p in recs[:6])
        row = {
            'mission_id':mission_id,'contact_id':cid,'objective':objective,
            'success_criteria':'Obtain product, quantity, specification, destination, timeline and payment preference; convert only evidence-backed demand into RFQ.',
            'priority':'high','autonomy_mode':'AUTONOMOUS_NONBINDING',
            'allowed_channels':list(dict.fromkeys(str(e.get('channel')) for e in allowed)),
            'max_outbound_attempts':3,'status':'READY','binding_actions_allowed':False,
            'owner_approved':True,'approved_at':ts,'created_by':'SOFIA_CUBA_SALES_OS','agent_name':'SOFIA',
            'marketing_consent_verified':True,'created_at':ts,'updated_at':ts,
        }
        await get_backend().insert('communication_missions', row)
        created.append({'mission_id':mission_id,'contact_id':cid,'channels':row['allowed_channels']})
    return {
        'status':'ok','agent':'SOFIA','missions_created':len(created),'missions':created,
        'autonomy':'non-binding sales qualification only','cold_autosend':False,
        'cannot_do':['sign contracts','authorize payments','approve compliance','reveal protected counterparties','send unsolicited bulk marketing'],
    }
