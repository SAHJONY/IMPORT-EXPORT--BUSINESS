from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Query

app = FastAPI(title='SAHJONY Cuba Laws Intelligence Scanner', version='1.0.0', docs_url=None, redoc_url=None)

SOURCES: list[dict[str, Any]] = [
    {
        'id': 'cuba-gaceta',
        'name': 'Gaceta Oficial de la República de Cuba',
        'jurisdiction': 'CU',
        'authority': 'GACETA_OFICIAL',
        'url': 'https://www.gacetaoficial.gob.cu/',
        'topics': ['IMPORTACION', 'ADUANA', 'COMERCIO_EXTERIOR', 'MIPYME', 'BANCA', 'TRIBUTOS'],
    },
    {
        'id': 'cuba-mincex',
        'name': 'Ministerio del Comercio Exterior y la Inversión Extranjera',
        'jurisdiction': 'CU',
        'authority': 'MINCEX',
        'url': 'https://www.mincex.gob.cu/',
        'topics': ['COMERCIO_EXTERIOR', 'IMPORTACION', 'EXPORTACION', 'MIPYME', 'NOMENCLATURA'],
    },
    {
        'id': 'cuba-aduana',
        'name': 'Aduana General de la República',
        'jurisdiction': 'CU',
        'authority': 'ADUANA',
        'url': 'https://www.aduana.gob.cu/',
        'topics': ['ADUANA', 'DESADUANAMIENTO', 'AGENTE_ADUANAL', 'IMPORTACION', 'EXPORTACION'],
    },
    {
        'id': 'us-ofac-cuba',
        'name': 'U.S. Treasury OFAC — Cuba sanctions',
        'jurisdiction': 'US',
        'authority': 'OFAC',
        'url': 'https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions',
        'topics': ['OFAC', 'SANCIONES', 'SDN', 'CACR', 'PAGOS', 'OWNERSHIP_50_PERCENT'],
    },
    {
        'id': 'us-ofac-actions',
        'name': 'U.S. Treasury OFAC — Recent actions',
        'jurisdiction': 'US',
        'authority': 'OFAC',
        'url': 'https://ofac.treasury.gov/recent-actions',
        'topics': ['OFAC', 'SANCIONES', 'SDN', 'CUBA'],
    },
    {
        'id': 'us-bis-cuba',
        'name': 'U.S. BIS — Cuba export controls',
        'jurisdiction': 'US',
        'authority': 'BIS',
        'url': 'https://www.bis.gov/licensing/country-guidance/cuba-export-controls',
        'topics': ['BIS', 'EAR', 'SCP', 'AGR', 'EXPORTACION', 'BANCA'],
    },
]

KNOWN_EVENTS: list[dict[str, Any]] = [
    {
        'id': 'cu-2026-mincex-126',
        'date': '2026-09-03',
        'jurisdiction': 'CU',
        'authority': 'MINCEX',
        'instrument': 'Resolución MINCEX 126/2026',
        'title': 'Procedimiento para facultades, nomenclaturas y permisos eventuales de comercio exterior',
        'impact': 'HIGH',
        'topics': ['COMERCIO_EXTERIOR', 'IMPORTACION', 'EXPORTACION', 'NOMENCLATURA', 'MIPYME'],
        'operating_rule': 'No tratar la autorización de importación directa como automática. Verificar facultad MINCEX, nomenclatura autorizada, vigencia y permisos eventuales antes de liberar una operación.',
        'status': 'VERIFIED_REGISTER',
    },
    {
        'id': 'cu-2026-direct-trade-129',
        'date': '2026-07-11',
        'jurisdiction': 'CU',
        'authority': 'CUBA_POLICY',
        'instrument': 'Transformación 129',
        'title': 'Operaciones directas de comercio exterior para actores estatales, privados y cooperativos',
        'impact': 'HIGH',
        'topics': ['COMERCIO_EXTERIOR', 'IMPORTACION', 'MIPYME'],
        'operating_rule': 'Clasificar al comprador cubano como DIRECT IMPORTER solo después de verificar autorización aplicable y nomenclatura/producto.',
        'status': 'POLICY_VERIFIED',
    },
    {
        'id': 'cu-2026-customs-108-134',
        'date': '2026-01-21',
        'jurisdiction': 'CU',
        'authority': 'ADUANA',
        'instrument': 'Decreto-Ley 108 / Decreto 134',
        'title': 'Marco aduanero, representación, agentes, apoderados y desaduanamiento',
        'impact': 'HIGH',
        'topics': ['ADUANA', 'IMPORTACION', 'AGENTE_ADUANAL', 'DESADUANAMIENTO'],
        'operating_rule': 'Verificar quién presenta la declaración, quién obtiene el levante y si el agente/agencia/apoderado está legalmente autorizado. Un transitario no se presume agente aduanal.',
        'status': 'VERIFIED_REGISTER',
    },
    {
        'id': 'us-2026-ofac-gemar-gecomex',
        'date': '2026-07-13',
        'jurisdiction': 'US',
        'authority': 'OFAC',
        'instrument': 'E.O. 14404 / OFAC Cuba designations',
        'title': 'GEMAR and GECOMEX designated; U.S.-person transaction restrictions remain applicable',
        'impact': 'CRITICAL',
        'topics': ['OFAC', 'SANCIONES', 'GEMAR', 'GECOMEX', 'OWNERSHIP_50_PERCENT'],
        'operating_rule': 'Fail closed before contracting or paying GEMAR, GECOMEX or an entity owned 50% or more by them unless a transaction-specific authorization clearly applies.',
        'status': 'VERIFIED_REGISTER',
    },
    {
        'id': 'us-2026-bis-scp-bank',
        'date': '2026-03-04',
        'jurisdiction': 'US',
        'authority': 'BIS',
        'instrument': 'BIS SCP suspension guidance',
        'title': 'License Exception SCP §740.21(b)(1) suspended for transactions involving deposit of foreign funds into Cuban-owned banks',
        'impact': 'CRITICAL',
        'topics': ['BIS', 'EAR', 'SCP', 'BANCA', 'PAGOS'],
        'operating_rule': 'A transaction relying on SCP cannot be cleared when it uses a prohibited Cuban-owned-bank deposit path; evaluate a compliant third-country/payment structure or another authorization.',
        'status': 'VERIFIED_REGISTER',
    },
]

KEYWORDS: dict[str, tuple[str, ...]] = {
    'IMPORTACION': ('importacion', 'importación', 'importar', 'importaciones'),
    'EXPORTACION': ('exportacion', 'exportación', 'exportar', 'exportaciones'),
    'ADUANA': ('aduana', 'aduanal', 'desaduanamiento', 'levante'),
    'COMERCIO_EXTERIOR': ('comercio exterior', 'mincex', 'nomenclatura'),
    'MIPYME': ('mipyme', 'micro pequena', 'micro pequeña', 'empresa privada', 'sector privado'),
    'OFAC': ('ofac', 'sanctions', 'sanction', 'blocked persons', 'sdn'),
    'BIS': ('bureau of industry and security', 'ear', 'license exception', 'scp', 'agr'),
    'BANCA': ('bank', 'banking', 'banco', 'bancaria', 'payment', 'pago'),
    'SANCIONES': ('sanction', 'sancion', 'sanción', 'blocked', 'designated', 'designación'),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify(text: str) -> list[str]:
    lowered = text.lower()
    return [topic for topic, words in KEYWORDS.items() if any(word in lowered for word in words)]


def risk(topics: list[str]) -> str:
    if any(x in topics for x in ('OFAC', 'SANCIONES', 'BIS')):
        return 'CRITICAL'
    if any(x in topics for x in ('ADUANA', 'COMERCIO_EXTERIOR', 'BANCA')):
        return 'HIGH'
    return 'MEDIUM' if topics else 'INFO'


def extract_refs(text: str) -> list[str]:
    patterns = [
        r'(?:Resoluci[oó]n|Decreto(?:-Ley)?|Ley)\s+(?:No\.?\s*)?\d+(?:/\d{4})?',
        r'FAQ\s+\d{3,4}',
        r'E\.O\.\s*\d{4,6}',
        r'§\s*\d{3}\.\d+(?:\([a-z0-9]+\))*',
    ]
    out: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text, re.IGNORECASE):
            value = re.sub(r'\s+', ' ', match).strip()
            if value not in out:
                out.append(value)
            if len(out) >= 20:
                return out
    return out


async def scan_source(client: httpx.AsyncClient, source: dict[str, Any]) -> dict[str, Any]:
    checked_at = now_iso()
    try:
        response = await client.get(source['url'], follow_redirects=True)
        raw = response.text[:1_500_000]
        normalized = re.sub(r'\s+', ' ', raw).strip()
        fingerprint = hashlib.sha256(normalized.encode('utf-8', errors='ignore')).hexdigest() if normalized else None
        detected = sorted(set(source['topics']) | set(classify(normalized)))
        return {
            **source,
            'status': 'ONLINE' if response.is_success else 'HTTP_ERROR',
            'http_status': response.status_code,
            'checked_at': checked_at,
            'final_url': str(response.url),
            'fingerprint': fingerprint,
            'last_modified': response.headers.get('last-modified'),
            'etag': response.headers.get('etag'),
            'detected_topics': detected,
            'risk': risk(detected),
            'references': extract_refs(normalized),
            'requires_human_legal_review': True,
        }
    except Exception as exc:
        return {
            **source,
            'status': 'UNREACHABLE',
            'http_status': None,
            'checked_at': checked_at,
            'fingerprint': None,
            'detected_topics': source['topics'],
            'risk': 'HIGH',
            'references': [],
            'error_type': type(exc).__name__,
            'requires_human_legal_review': True,
        }


@app.get('/cuba-laws/health')
async def health():
    return {
        'status': 'ok',
        'service': 'cuba-laws-intelligence-scanner',
        'version': '1.0.0',
        'sources': len(SOURCES),
        'known_events': len(KNOWN_EVENTS),
        'fail_closed': True,
        'binding_legal_advice': False,
        'transaction_release_authority': False,
        'capabilities': ['source_monitoring', 'content_fingerprints', 'topic_classification', 'risk_ranking', 'legal_register', 'operating_rules'],
    }


@app.get('/cuba-laws/register')
async def legal_register(topic: str | None = Query(None), jurisdiction: str | None = Query(None)):
    rows = KNOWN_EVENTS
    if topic:
        t = topic.upper().strip()
        rows = [row for row in rows if t in row['topics']]
    if jurisdiction:
        j = jurisdiction.upper().strip()
        rows = [row for row in rows if row['jurisdiction'] == j]
    return {'as_of': now_iso(), 'events': rows, 'count': len(rows)}


@app.get('/cuba-laws/sources')
async def sources():
    return {'sources': SOURCES, 'count': len(SOURCES)}


@app.get('/cuba-laws/scan')
async def scan(live: bool = Query(True)):
    if not live:
        return {'status': 'registry_only', 'checked_at': now_iso(), 'sources': SOURCES, 'events': KNOWN_EVENTS}
    timeout = httpx.Timeout(12.0, connect=6.0)
    headers = {'User-Agent': 'SAHJONY-Cuba-Laws-Intelligence/1.0 (+https://www.sahjony.com)'}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        results = []
        for source in SOURCES:
            results.append(await scan_source(client, source))
    critical = [row for row in results if row.get('risk') == 'CRITICAL']
    degraded = [row for row in results if row.get('status') != 'ONLINE']
    return {
        'status': 'ok' if not degraded else 'degraded',
        'checked_at': now_iso(),
        'sources_scanned': len(results),
        'critical_sources': len(critical),
        'degraded_sources': len(degraded),
        'results': results,
        'known_events': KNOWN_EVENTS,
        'decision_rule': 'A detected or suspected legal change never auto-clears a transaction. Material changes create a human-review gate before commercial execution.',
    }
