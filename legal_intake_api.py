"""SAHJONY Global Trade — Departamento Legal (Firma Legal) · deal-advisory intake.

Owner-only module. Stores deal pre-commitment legal-review requests as local
JSON files under the repo's `legal/` directory. NOTHING is sent anywhere and
no external calls are made. Import/export business only — never cross-filed
with MY CUBA CASH.

Label: AI LEGAL RESEARCH — NOT LEGAL ADVICE.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token

app = FastAPI(
    title='SAHJONY Legal Department — Deal-Advisory Intake',
    version='1.0.0',
    docs_url=None,
    redoc_url=None,
)

LEGAL_DIR = Path(__file__).resolve().parent / 'legal'
LEGAL_DIR.mkdir(exist_ok=True)

_SLUG_RE = re.compile(r'[^a-z0-9]+')


def _auth_owner(x_role: str | None, authorization: str | None) -> None:
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


def _slug(value: str) -> str:
    s = _SLUG_RE.sub('-', value.lower()).strip('-')
    return s[:48] or 'deal'


class DealIntakeIn(BaseModel):
    deal_name: str = Field(min_length=2, max_length=160)
    counterparty: str = Field(min_length=2, max_length=200)
    structure: str = Field(min_length=2, max_length=2000)
    question: str = Field(min_length=2, max_length=4000)


@app.get('/legal/health')
def legal_health():
    return {
        'status': 'ok',
        'module': 'firma-legal',
        'business': 'import-export',
        'notice': 'AI LEGAL RESEARCH — NOT LEGAL ADVICE',
    }


@app.post('/legal/intake')
def create_intake(
    payload: DealIntakeIn,
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
):
    _auth_owner(x_role, authorization)
    ts = datetime.now(timezone.utc)
    filename = f"intake-{ts.strftime('%Y%m%d-%H%M%S')}-{_slug(payload.deal_name)}.json"
    record = {
        'id': filename.removesuffix('.json'),
        'created_at': ts.isoformat(),
        'deal_name': payload.deal_name.strip(),
        'counterparty': payload.counterparty.strip(),
        'structure': payload.structure.strip(),
        'question': payload.question.strip(),
        'business': 'import-export',
        'status': 'pending-review',
        'notice': 'AI LEGAL RESEARCH — NOT LEGAL ADVICE. Intake only; no attorney-client relationship created.',
    }
    (LEGAL_DIR / filename).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    return {'status': 'ok', 'id': record['id'], 'created_at': record['created_at']}


@app.get('/legal/intakes')
def list_intakes(
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
):
    _auth_owner(x_role, authorization)
    records = []
    for path in sorted(LEGAL_DIR.glob('intake-*.json'), reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            continue
    return {
        'status': 'ok',
        'count': len(records),
        'records': records,
        'notice': 'AI LEGAL RESEARCH — NOT LEGAL ADVICE. Internal intake records only.',
    }
