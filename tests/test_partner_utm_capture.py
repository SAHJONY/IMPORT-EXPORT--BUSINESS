"""Partner application first-touch attribution (UTM capture) tests.

The /partners submit path must persist client-side UTM params to
cuba_partner_accounts, mirroring the /start path. All storage calls are
captured in-memory (synthetic fixtures only; no real database, no sends).
"""
import pytest

import cuba_partner_api
from cuba_partner_api import PartnerApplicationIn, apply
from fastapi import HTTPException


class _InsertCapture:
    def __init__(self):
        self.calls = []

    async def __call__(self, table, row):
        self.calls.append((table, dict(row)))
        return row


def _valid_kwargs(**overrides):
    kwargs = {
        "full_name": "Prueba Socio",
        "phone": "+53 5555 0101",
        "email": "socio@example.com",
        "accepts_terms": True,
    }
    kwargs.update(overrides)
    return kwargs


def _install_capture(monkeypatch):
    capture = _InsertCapture()
    monkeypatch.setattr(cuba_partner_api, "insert_row", capture)
    return capture


def test_partner_model_accepts_utm_fields_without_422():
    """UTM fields are optional; submitting without them must not fail validation."""
    p = PartnerApplicationIn(**_valid_kwargs())
    assert p.utm_source is None
    assert p.utm_medium is None
    assert p.utm_campaign is None
    assert p.referrer is None
    assert p.first_touch_source is None


@pytest.mark.asyncio
async def test_partner_apply_persists_utm_fields(monkeypatch):
    capture = _install_capture(monkeypatch)
    payload = PartnerApplicationIn(
        **_valid_kwargs(
            utm_source="facebook",
            utm_medium="group",
            utm_campaign="cuba_import_export_group",
            referrer="https://www.facebook.com/groups/1558873548822463",
            first_touch_source="facebook_group",
        )
    )
    result = await apply(payload)
    assert result["status"] == "APPLIED"
    assert len(capture.calls) == 1
    table, row = capture.calls[0]
    assert table == "cuba_partner_accounts"
    assert row["utm_source"] == "facebook"
    assert row["utm_medium"] == "group"
    assert row["utm_campaign"] == "cuba_import_export_group"
    assert row["referrer"] == "https://www.facebook.com/groups/1558873548822463"
    assert row["first_touch_source"] == "facebook_group"
    assert row["partner_id"] == result["partner_id"]


@pytest.mark.asyncio
async def test_partner_apply_without_utm_persists_nulls(monkeypatch):
    """No UTM params -> NULL attribution columns, no 422, row still persisted."""
    capture = _install_capture(monkeypatch)
    payload = PartnerApplicationIn(**_valid_kwargs())
    result = await apply(payload)
    assert result["status"] == "APPLIED"
    assert len(capture.calls) == 1
    table, row = capture.calls[0]
    assert table == "cuba_partner_accounts"
    for field in ("utm_source", "utm_medium", "utm_campaign", "referrer", "first_touch_source"):
        assert row[field] is None


@pytest.mark.asyncio
async def test_partner_apply_validation_still_enforced(monkeypatch):
    """Required-field guards keep working: missing contact info -> 422,
    terms not accepted -> 422, honeypot -> 400."""
    _install_capture(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await apply(PartnerApplicationIn(**_valid_kwargs(phone=None, email=None)))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await apply(PartnerApplicationIn(**_valid_kwargs(accepts_terms=False)))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await apply(PartnerApplicationIn(**_valid_kwargs(website="https://spam.example")))
    assert exc.value.status_code == 400
