import asyncio

from market_intelligence import UNComtradePreviewFeed


def test_un_comtrade_preview_is_credential_free_and_capped(monkeypatch):
    feed = UNComtradePreviewFeed()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"reporterCode": 156, "flowCode": "X", "cmdCode": "0901"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            assert "public/v1/preview" in url
            assert params["maxRecords"] == "500"
            return Response()

    monkeypatch.setattr("market_intelligence.httpx.AsyncClient", lambda *args, **kwargs: Client())
    result = asyncio.run(feed.query(period="2023", reporter_code="156", flow_code="X", hs_code="0901", max_records=9999))
    assert result["count"] == 1
    assert result["scope"] == "GLOBAL_AGGREGATE_PREVIEW"
    assert "individual buyers or suppliers" in result["notice"]
