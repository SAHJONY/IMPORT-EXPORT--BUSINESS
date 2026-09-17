"""SAHJONY Envios — Houston, Texas → Cuba quote intake (broker/intermediary).

Public API for the "Envios Houston → Cuba" section:
- Service lines covered here: CONTENEDORES FCL and PALLETS / CARGA CONSOLIDADA.
  (Carros live in the car app; this endpoint covers freight only.)
- The endpoint creates a QUOTE REQUEST with a server-generated reference number
  (ENV-2026-XXXXXX), persists it server-side, and returns the reference.
  No quote is produced by this endpoint: real quotes are issued by Juan's team
  within 24–48h. Leads stay inside the import/export business only.

Verified-facts policy: this module contains NO ocean freight rates, NO transit
times, NO sailing schedules, and NO named carriers for the Houston→Cuba leg.
Those facts do not exist as verified data, so the API must never invent them.

Storage: Neon Postgres via physical_postgres.insert_row / select_rows
(table envios_intakes; see migrations/20260917_envios_intakes.sql).
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from physical_postgres import insert_row, select_rows

app = FastAPI(title='SAHJONY Envios — Houston→Cuba Quote Intake', version='1.0.0', docs_url=None, redoc_url=None)

REFERENCE_PREFIX = 'ENV-2026'
_REFERENCE_ALPHABET = string.ascii_uppercase + string.digits

CargoType = Literal['contenedor_fcl', 'pallet_consolidado']
ContainerSize = Literal['20', '40']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_reference() -> str:
    """Build a unique quote-request reference: ENV-2026-XXXXXX (6 alnum chars)."""
    suffix = ''.join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(6))
    return f'{REFERENCE_PREFIX}-{suffix}'


def require_owner(authorization: str | None, x_role: str | None) -> None:
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


class EnviosIntakeIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    whatsapp: str = Field(min_length=7, max_length=40)
    cargo_type: CargoType
    # Origin: Houston pickup address OR drop-off at reception point.
    origin_detail: str = Field(min_length=3, max_length=600)
    origin_mode: Literal['pickup', 'dropoff'] = 'pickup'
    # Destination: Cuba province + city/municipality.
    cuba_province: str = Field(min_length=2, max_length=120)
    cuba_city: str = Field(min_length=2, max_length=120)
    # Container branch (cargo_type == 'contenedor_fcl')
    container_size: ContainerSize | None = None
    goods_description: str = Field(min_length=3, max_length=2000)
    # Pallet branch (cargo_type == 'pallet_consolidado')
    pieces: int | None = Field(default=None, ge=1)
    weight_kg: float | None = Field(default=None, ge=0)
    dimensions_cm: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=2000)
    preferred_language: Literal['es', 'en'] = 'es'
    # Honeypot anti-bot field: legit browsers leave it empty.
    website: str | None = None
    # First-touch attribution (captured client-side, never invented server-side)
    utm_source: str | None = Field(default=None, max_length=200)
    utm_medium: str | None = Field(default=None, max_length=200)
    utm_campaign: str | None = Field(default=None, max_length=200)
    referrer: str | None = Field(default=None, max_length=500)


def _validate_branch(p: EnviosIntakeIn) -> None:
    if p.cargo_type == 'contenedor_fcl' and not p.container_size:
        raise HTTPException(422, 'Container size (20\'/40\') is required for FCL quotes')
    if p.cargo_type == 'pallet_consolidado' and not p.pieces:
        raise HTTPException(422, 'Number of pieces is required for pallet quotes')


@app.get('/envios-api/health')
async def health():
    return {
        'status': 'ok',
        'service': 'sahjony-envios-houston-cuba',
        'storage': 'physical_neon_postgres',
        'table': 'envios_intakes',
        'response_target': '24-48h',
        'broker_positioning': True,
        'quotes_issued_by': 'team_review',
    }


@app.post('/envios-api/intake')
async def create_intake(p: EnviosIntakeIn):
    if p.website:
        raise HTTPException(400, 'Unable to accept request')
    _validate_branch(p)
    reference = build_reference()
    ts = now()
    first_touch = {k: v for k, v in {
        'utm_source': p.utm_source,
        'utm_medium': p.utm_medium,
        'utm_campaign': p.utm_campaign,
        'referrer': p.referrer,
    }.items() if v}
    row = {
        'reference': reference,
        'full_name': p.full_name.strip(),
        'whatsapp': p.whatsapp.strip(),
        'cargo_type': p.cargo_type,
        'origin_detail': p.origin_detail.strip(),
        'origin_mode': p.origin_mode,
        'cuba_province': p.cuba_province.strip(),
        'cuba_city': p.cuba_city.strip(),
        'container_size': p.container_size,
        'goods_description': p.goods_description.strip(),
        'pieces': p.pieces,
        'weight_kg': p.weight_kg,
        'dimensions_cm': p.dimensions_cm.strip() if p.dimensions_cm else None,
        'notes': p.notes.strip() if p.notes else None,
        'preferred_language': p.preferred_language,
        'status': 'REQUESTED',
        'first_touch': first_touch or None,
        'created_at': ts,
        'updated_at': ts,
    }
    try:
        await insert_row('envios_intakes', row)
    except Exception as exc:
        raise HTTPException(502, 'Quote request storage is temporarily unavailable; please retry or use WhatsApp.') from exc
    return {
        'ok': True,
        'reference': reference,
        'response_target': '24-48h',
        'message': (
            'Your quote request was received. SAHJONY\'s team (broker/intermediary) '
            'will issue a real quote within 24–48 hours using the WhatsApp number provided.'
        ),
        'status': 'REQUESTED',
    }


@app.get('/envios-api/owner/intakes')
async def owner_list_intakes(
    authorization: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    limit: int = 50,
):
    require_owner(authorization, x_role)
    rows = await select_rows('envios_intakes', order_by='created_at', descending=True, limit=min(max(limit, 1), 200))
    return {'ok': True, 'count': len(rows), 'intakes': rows}
