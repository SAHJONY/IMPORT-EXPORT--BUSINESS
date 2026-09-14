import hashlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import customer_crm_api as crm


class Store:
    def __init__(self):
        self.tables = {}

    @staticmethod
    def _val(v):
        return v[3:] if isinstance(v, str) and v.startswith('eq.') else v

    def _match(self, row, params):
        for k, v in (params or {}).items():
            if k in {'limit', 'order'}:
                continue
            if str(row.get(k)) != str(self._val(v)):
                return False
        return True

    async def select(self, table, *, params=None):
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        return rows[: int((params or {}).get('limit', len(rows)) or len(rows))]

    async def insert(self, table, payload):
        rows = payload if isinstance(payload, list) else [payload]
        self.tables.setdefault(table, []).extend(dict(r) for r in rows)
        return rows

    async def patch(self, table, values, *, params):
        out=[]
        for row in self.tables.get(table, []):
            if self._match(row, params):
                row.update(values); out.append(dict(row))
        return out


def ready():
    return {
        'ready': True, 'storage_configured': True, 'signed_storage_verified': True,
        'malware_scan_required': True, 'malware_scan_callback_configured': True,
        'max_files': 1, 'max_bytes': 10 * 1024 * 1024,
        'allowed_types': ['application/pdf'],
    }


def test_readiness_fails_closed_without_scanner(monkeypatch):
    monkeypatch.setattr(crm, 'storage_configuration_status', lambda: {'configured': True})
    monkeypatch.setenv('SIGNED_DOCUMENT_STORAGE_VERIFIED', 'true')
    monkeypatch.setenv('DOCUMENT_MALWARE_SCAN_REQUIRED', 'true')
    monkeypatch.delenv('MALWARE_SCAN_CALLBACK_SECRET', raising=False)
    result = crm.public_attachment_readiness()
    assert result['ready'] is False
    assert result['malware_scan_callback_configured'] is False


def test_public_intake_issues_short_lived_capability_only_when_ready(monkeypatch):
    store=Store(); monkeypatch.setattr(crm, 'get_backend', lambda: store)
    monkeypatch.setattr(crm, 'public_attachment_readiness', ready)
    client=TestClient(crm.app)
    response=client.post('/crm/intake', json={
        'legal_name':'Buyer LLC','contact_name':'Buyer','email':'buyer@example.com',
        'product_need':'Industrial pump','destination_country':'US'
    })
    assert response.status_code == 200
    body=response.json(); cap=body['attachment_capability']
    assert cap['available'] is True and len(cap['token']) >= 32
    events=store.tables['customer_crm_audit']
    issued=[e for e in events if e['event_type']=='attachment_capability_issued']
    assert len(issued)==1
    assert cap['token'] not in str(issued[0]['payload'])
    assert issued[0]['payload']['token_sha256'] == hashlib.sha256(cap['token'].encode()).hexdigest()


def test_authorize_and_complete_attachment_stays_scan_pending(monkeypatch):
    store=Store(); monkeypatch.setattr(crm, 'get_backend', lambda: store)
    monkeypatch.setattr(crm, 'public_attachment_readiness', ready)
    monkeypatch.setattr(crm, 'validate_file', lambda filename, content_type, size: filename)
    monkeypatch.setattr(crm, 'create_upload_url', lambda **kw: {'url':'https://upload.invalid/signed','method':'PUT','headers':{'Content-Type':kw['content_type']}})
    monkeypatch.setattr(crm, 'verify_uploaded_object', lambda **kw: {'etag':'etag-1','size_bytes':kw['expected_size']})
    token='t'*48; intake_id='int_test'; customer_id='cus_test'
    expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
    store.tables['customer_trade_intakes']=[{'intake_id':intake_id,'customer_id':customer_id}]
    store.tables['customer_crm_audit']=[{
        'event_id':'cap','customer_id':customer_id,'intake_id':intake_id,'actor_role':'customer','actor_id':customer_id,
        'event_type':'attachment_capability_issued','summary':'cap','payload':{'token_sha256':hashlib.sha256(token.encode()).hexdigest(),'expires_at':expires},'created_at':datetime.now(timezone.utc).isoformat()
    }]
    client=TestClient(crm.app)
    auth=client.post(f'/crm/intakes/{intake_id}/attachments/authorize',json={'token':token,'filename':'spec.pdf','content_type':'application/pdf','size_bytes':1024})
    assert auth.status_code == 200
    doc_id=auth.json()['document_id']
    doc=store.tables['trade_documents'][0]
    assert doc['storage_status']=='upload_authorized'
    assert doc['trade_case_id']==f'intake:{intake_id}'
    complete=client.post(f'/crm/intakes/{intake_id}/attachments/{doc_id}/complete',json={'token':token})
    assert complete.status_code == 200
    assert complete.json()['storage_status']=='scan_pending'
    assert complete.json()['usable'] is False
    assert store.tables['trade_documents'][0]['malware_scan_status']=='pending'
    storage_events=[e['event_type'] for e in store.tables['document_storage_events']]
    assert storage_events == ['upload_authorized','upload_verified','scan_requested']


def test_invalid_capability_is_rejected(monkeypatch):
    store=Store(); monkeypatch.setattr(crm, 'get_backend', lambda: store)
    monkeypatch.setattr(crm, 'public_attachment_readiness', ready)
    intake_id='int_test'; customer_id='cus_test'
    store.tables['customer_trade_intakes']=[{'intake_id':intake_id,'customer_id':customer_id}]
    store.tables['customer_crm_audit']=[{
        'event_id':'cap','customer_id':customer_id,'intake_id':intake_id,'actor_role':'customer','actor_id':customer_id,
        'event_type':'attachment_capability_issued','summary':'cap','payload':{'token_sha256':hashlib.sha256(b'correct').hexdigest(),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()},'created_at':datetime.now(timezone.utc).isoformat()
    }]
    client=TestClient(crm.app)
    response=client.post(f'/crm/intakes/{intake_id}/attachments/authorize',json={'token':'wrong'*10,'filename':'spec.pdf','content_type':'application/pdf','size_bytes':1024})
    assert response.status_code == 403
