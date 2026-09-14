from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_communication_os_uses_only_governed_hermes_transport():
    api = (ROOT / "communication_os_api.py").read_text(encoding="utf-8")
    page = (ROOT / "public" / "owner-communications-os.html").read_text(encoding="utf-8")
    assert '"transport": "hermes_hostinger"' in api
    assert "await _whatsapp_state()" in api
    assert "/whatsapp/send" in page
    assert "whatsapp_queue" in api
    assert "meta_cloud" not in api
    assert "wa.me" not in page
    assert "facebook" not in page.lower()


def test_cuba_crm_is_server_paginated_and_routes_outreach_to_hermes():
    api = (ROOT / "cuba_mipymes_api.py").read_text(encoding="utf-8")
    page = (ROOT / "owner-cuba-mipymes.html").read_text(encoding="utf-8")
    public_page = (ROOT / "public" / "owner-cuba-mipymes.html").read_text(encoding="utf-8")
    assert "limit:int=Query(100,ge=1,le=250)" in api
    assert "offset:int=Query(0,ge=0)" in api
    assert "paged_private_rows" in api
    assert "Preparar en Hermes" in page
    assert "/owner/communications-os?" in page
    assert "wa.me" not in page
    assert page == public_page
