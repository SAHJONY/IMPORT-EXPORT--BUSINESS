import asyncio

import telegram_api


def test_telegram_health_is_explicitly_read_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "configured")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "configured")
    monkeypatch.setenv("OWNER_SESSION_SECRET", "configured")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@SahjonyGlobalTradeBot")

    result = asyncio.run(telegram_api.telegram_health())

    assert result["status"] == "ok"
    assert result["read_only_health"] is True
    assert result["persistence_accessed"] is False
    assert result["provider_called"] is False
    assert result["bot_identity_matches_canonical"] is True
    assert result["autonomous_external_commitments"] is False
    assert result["fail_closed"] is True


def test_generic_telegram_message_stays_engagement_only():
    result = telegram_api._triage_message("Hello, I would like more information about SAHJONY.")
    assert result["classification"] == "engagement_only"
    assert result["genuine_trade_requirement_present"] is False
    assert result["qualified_demand"] is False
    assert result["rfq_created"] is False
    assert result["trade_intake_created"] is False


def test_concrete_trade_message_is_candidate_not_qualified_or_rfq():
    result = telegram_api._triage_message(
        "We need 2 containers of soybean oil delivered to Mariel, Cuba. Please quote CIF."
    )
    assert result["classification"] == "trade_requirement_candidate"
    assert result["genuine_trade_requirement_present"] is True
    assert result["qualified_demand"] is False
    assert result["rfq_created"] is False
    assert result["trade_intake_created"] is False
    assert result["sofia_priority"] == "high"
