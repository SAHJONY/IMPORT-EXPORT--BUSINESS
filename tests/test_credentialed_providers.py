import asyncio

from credentialed_providers import ExecutableFXProvider, MaerskProvider
from trade_connectors import TradeConnectorRegistry


def test_maersk_requires_complete_server_credentials(monkeypatch):
    for key in ["MAERSK_CLIENT_ID", "MAERSK_CLIENT_SECRET", "MAERSK_TOKEN_URL", "MAERSK_API_BASE"]:
        monkeypatch.delenv(key, raising=False)
    assert MaerskProvider().configured is False

    monkeypatch.setenv("MAERSK_CLIENT_ID", "client")
    monkeypatch.setenv("MAERSK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MAERSK_TOKEN_URL", "https://example.test/oauth/token")
    monkeypatch.setenv("MAERSK_API_BASE", "https://example.test/api")
    assert MaerskProvider().configured is True


def test_fx_execution_requires_health_path_and_credentials(monkeypatch):
    for key in ["FX_EXECUTION_API_BASE", "FX_EXECUTION_API_KEY", "FX_EXECUTION_HEALTH_PATH"]:
        monkeypatch.delenv(key, raising=False)
    assert ExecutableFXProvider().configured is False

    monkeypatch.setenv("FX_EXECUTION_API_BASE", "https://example.test")
    monkeypatch.setenv("FX_EXECUTION_API_KEY", "secret")
    monkeypatch.setenv("FX_EXECUTION_HEALTH_PATH", "/health")
    assert ExecutableFXProvider().configured is True


def test_usitc_search_is_scoped_to_us_imports(monkeypatch):
    registry = TradeConnectorRegistry()

    class Response:
        def json(self):
            return [{"htsno": "0101.21.00", "description": "Purebred breeding animals"}]

    async def fake_get(url, timeout=15):
        assert "hts.usitc.gov/reststop/search" in url
        return Response()

    monkeypatch.setattr(registry, "_get", fake_get)
    result = asyncio.run(registry.usitc_hts_search("horses"))
    assert result["scope"] == "US_IMPORTS"
    assert result["results"][0]["htsno"] == "0101.21.00"
