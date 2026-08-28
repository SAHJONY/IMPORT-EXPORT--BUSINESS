import asyncio

import worldwide_connect_api as module


class _Response:
    status_code = 200

    def json(self):
        return {
            "places": [
                {
                    "id": "place-1",
                    "displayName": {"text": "Industrial Supplier Miami"},
                    "formattedAddress": "Miami, FL",
                    "websiteUri": "https://supplier.example",
                    "businessStatus": "OPERATIONAL",
                }
            ]
        }


class _Client:
    def __init__(self, *args, **kwargs):
        self.headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, _url, *, headers, json):
        self.headers = headers
        assert headers["X-Goog-Api-Key"] == "secret-test-key"
        assert json["textQuery"] == "industrial suppliers Miami Florida"
        return _Response()


def test_health_never_exposes_google_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "secret-test-key")
    payload = asyncio.run(module.worldwide_health())
    assert payload["google_places_ready"] is True
    assert payload["api_key_exposed"] is False
    assert "secret-test-key" not in str(payload)


def test_real_search_contract_returns_usable_safe_results(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "secret-test-key")
    monkeypatch.setattr(module, "verify_owner_token", lambda token: token == "owner-token")
    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    payload = asyncio.run(
        module.worldwide_search(
            module.PlacesSearchIn(query="industrial suppliers Miami Florida", limit=5),
            authorization="Bearer owner-token",
        )
    )
    assert payload["result_count"] == 1
    assert payload["usable_results"] is True
    assert payload["api_key_exposed"] is False
    assert "secret-test-key" not in str(payload)
