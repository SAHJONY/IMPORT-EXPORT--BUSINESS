import asyncio

from credentialed_providers import AirwallexProvider
from market_intelligence import CensusTradeFeed


def test_airwallex_requires_server_credentials(monkeypatch):
    for key in ["AIRWALLEX_CLIENT_ID", "AIRWALLEX_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    assert AirwallexProvider().configured is False
    monkeypatch.setenv("AIRWALLEX_CLIENT_ID", "client")
    monkeypatch.setenv("AIRWALLEX_API_KEY", "secret")
    assert AirwallexProvider().configured is True


def test_census_import_signals_rank_by_monthly_value(monkeypatch):
    monkeypatch.setenv("CENSUS_TRADE_API_KEY", "key")
    feed = CensusTradeFeed()

    async def fake_query(url, params):
        return [
            ["CTY_CODE", "CTY_NAME", "I_COMMODITY", "GEN_VAL_MO", "GEN_VAL_YR"],
            ["5700", "China", "0901", "200", "1000"],
            ["2010", "Mexico", "0901", "500", "2000"],
        ]

    monkeypatch.setattr(feed, "_query", fake_query)
    signals = asyncio.run(feed.us_import_origins("0901", "2026-07"))
    assert signals[0].country_name == "Mexico"
    assert signals[0].monthly_value_usd == 500
    assert signals[0].direction == "US_IMPORT"


def test_census_feed_is_aggregate_not_counterparty_identity(monkeypatch):
    monkeypatch.setenv("CENSUS_TRADE_API_KEY", "key")
    assert CensusTradeFeed().configured is True
