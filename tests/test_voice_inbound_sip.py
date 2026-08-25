from voice_inbound_api import _build_write, _sip_direction, _sip_endpoint


def test_openai_sip_endpoint_is_tls_canonical():
    endpoint = _sip_endpoint("proj_test")
    assert endpoint == "sip:proj_test@sip.api.openai.com;transport=tls"


def test_existing_inbound_uses_update_not_duplicate_attach():
    current = {"data": {"inbound": {"sip_endpoint": "sip:old.example.com"}}}
    operation, url, body = _build_write(current, "+12125550123", "proj_test")
    assert operation == "update"
    assert url.endswith("/v1/sip/update")
    assert body["phone_number"] == "+12125550123"
    assert body["updates"]["type"] == "inbound"
    assert body["updates"]["sip_endpoint"].startswith("sip:proj_test@sip.api.openai.com")


def test_missing_inbound_uses_attach():
    operation, url, body = _build_write({"data": {}}, "+12125550123", "proj_test")
    assert operation == "attach"
    assert url.endswith("/v1/sip/attach")
    assert body["service"] == "sip"
    assert len(body["directions"]) == 1


def test_sip_direction_requires_tls_and_secure_media():
    direction = _sip_direction("proj_test")
    assert direction["auth_mode"] == "ip"
    assert direction["options"]["port"] == 5061
    assert direction["options"]["transport"] == "tls"
    assert direction["options"]["secure_media"] is True
