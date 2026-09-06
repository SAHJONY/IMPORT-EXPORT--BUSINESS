import os
os.environ.setdefault('TRACKING_SIGNING_SECRET','test-secret-value')
import shipment_api as api

def test_signed_tracking_token_roundtrip():
    sid='shp_test-package-123'
    token=api.public_tracking_token(sid)
    assert api.shipment_id_from_token(token)==sid
    assert token.count('.')==1

def test_tampered_tracking_token_rejected():
    import pytest
    token=api.public_tracking_token('shp_test-package-456')
    with pytest.raises(Exception): api.shipment_id_from_token(token+'x')

def test_tracking_url_is_public_route(monkeypatch):
    monkeypatch.setenv('PUBLIC_APP_URL','https://www.sahjony.com')
    token=api.public_tracking_token('shp_test-package-789')
    assert api.tracking_url(token).startswith('https://www.sahjony.com/track/')
