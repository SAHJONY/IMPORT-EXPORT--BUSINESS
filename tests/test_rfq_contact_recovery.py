from decimal import Decimal

from tools.rfq_contact_recovery import (
    ContactCandidate,
    DeliveryState,
    classify_delivery_notice,
    normalize_to_usd_per_kg,
    resend_decision,
    sanctions_gate,
    split_route_costs,
)


def test_delivery_failure_classification():
    assert classify_delivery_notice("Delivery Status Notification (Failure) 550 5.1.1") == DeliveryState.PERMANENT_FAILURE


def test_delivery_delay_classification():
    assert classify_delivery_notice("Delivery Status Notification (Delay): temporary failure; will retry") == DeliveryState.TEMPORARY_DELAY


def test_delay_never_prepares_duplicate_resend():
    c = ContactCandidate(
        value="ops@example.com",
        channel="email",
        source="official website",
        verified=True,
        same_legal_entity=True,
        role_match=True,
    )
    result = resend_decision(delivery_state=DeliveryState.TEMPORARY_DELAY, alternate_candidates=[c])
    assert result["action"] == "wait_for_provider_retry"


def test_permanent_failure_uses_verified_alternate_only():
    c = ContactCandidate(
        value="ops@example.com",
        channel="email",
        source="official website",
        verified=True,
        same_legal_entity=True,
        role_match=True,
    )
    result = resend_decision(delivery_state=DeliveryState.PERMANENT_FAILURE, alternate_candidates=[c])
    assert result["action"] == "prepare_resend"
    assert result["candidate"]["value"] == "ops@example.com"


def test_no_verified_alternate_fails_closed():
    c = ContactCandidate(
        value="possible@example.com",
        channel="email",
        source="third-party directory",
        verified=False,
    )
    result = resend_decision(delivery_state=DeliveryState.PERMANENT_FAILURE, alternate_candidates=[c])
    assert result["action"] == "research_alternate"


def test_usd_per_kg_from_pounds():
    # $220.46226218 for 220.46226218 lb = $2.2046/kg approximately.
    normalized = normalize_to_usd_per_kg(amount_usd="220.46226218", quantity="220.46226218", unit="lb")
    assert normalized == Decimal("2.2046")


def test_route_costs_remain_separate():
    costs = split_route_costs({"inland": "100", "ocean": "250", "customs": "50"})
    assert costs["inland"] == Decimal("100")
    assert costs["ocean"] == Decimal("250")
    assert costs["customs"] == Decimal("50")
    assert costs["upstream_total_usd"] == Decimal("400")


def test_high_risk_cuba_provider_fails_gate():
    gate = sanctions_gate("TRANSCARGO Cuba", ["GEMAR"])
    assert gate.blocked_or_high_risk_match is True
    assert gate.commercially_usable is False
