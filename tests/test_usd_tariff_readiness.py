import asyncio

import httpx
import pytest

from payment_engine import PaymentError, payment_plan
from production_readiness import evaluate_production_readiness
from usitc_tariff_provider import USITCTariffProvider


def _connector_health(*, tariff_reachable=True, fx_reachable=False):
    return {
        "by_name": {
            "ofac_sanctions_data": {"configured": True, "reachable": True},
            "tariff_classification": {"configured": True, "reachable": tariff_reachable},
            "logistics_tracking": {"configured": False, "reachable": False},
            "fx_execution": {"configured": fx_reachable, "reachable": fx_reachable},
        }
    }


def test_usd_only_payment_engine_rejects_non_usd():
    with pytest.raises(PaymentError, match="denominated in USD"):
        payment_plan(
            audience="BUSINESS_CUSTOMER",
            total_amount=100,
            currency="EUR",
            quote_approved=True,
            compliance_cleared=True,
        )


def test_usd_settlement_does_not_require_fx_execution_provider(monkeypatch):
    for name in ("FX_EXECUTION_PROVIDER", "FX_DATA_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    result = evaluate_production_readiness(
        runtime_ok=True,
        connector_health=_connector_health(fx_reachable=False),
    )
    gate = next(g for g in result["gates"] if g["name"] == "fx_execution_provider")
    assert gate["passed"] is True
    assert "USD-only" in gate["evidence"]
    assert result["canonical_transaction_currency"] == "USD"
    assert result["usd_only_transactions"] is True


def test_tariff_gate_still_requires_authoritative_source_reachability():
    result = evaluate_production_readiness(
        runtime_ok=True,
        connector_health=_connector_health(tariff_reachable=False),
    )
    gate = next(g for g in result["gates"] if g["name"] == "tariff_classification")
    assert gate["passed"] is False


class _FakeResponse:
    def __init__(self, *, text="", content_type="text/html", json_value=None):
        self.text = text
        self.headers = {"content-type": content_type}
        self._json_value = json_value

    def json(self):
        return self._json_value


def test_usitc_provider_prefers_rest_json(monkeypatch):
    provider = USITCTariffProvider()

    async def fake_get(url, *, timeout=20):
        assert "reststop/search" in url
        return _FakeResponse(content_type="application/json", json_value={"results": [{"htsno": "5201"}]})

    monkeypatch.setattr(provider, "_get", fake_get)
    result = asyncio.run(provider.search("cotton"))
    assert result["source_mode"] == "REST"
    assert result["results"]["results"][0]["htsno"] == "5201"
    assert "United States International Trade Commission" in result["source"]


def test_usitc_provider_falls_back_to_official_web(monkeypatch):
    provider = USITCTariffProvider()
    calls = []

    async def fake_get(url, *, timeout=20):
        calls.append(url)
        if "reststop/search" in url:
            raise httpx.ConnectError("simulated REST network failure")
        return _FakeResponse(
            text="<html><title>Harmonized Tariff Schedule</title><body>Search Results cotton 5201.00.00</body></html>",
            content_type="text/html",
        )

    monkeypatch.setattr(provider, "_get", fake_get)
    result = asyncio.run(provider.search("cotton"))
    assert result["source_mode"] == "OFFICIAL_WEB_FALLBACK"
    assert result["candidate_count"] >= 1
    assert result["results"][0]["hts_candidate"] == "5201.00.00"
    assert any("/search?query=" in url for url in calls)
