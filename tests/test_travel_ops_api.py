from decimal import Decimal

from travel_ops_api import (
    BookingGateIn,
    DuffelSearchIn,
    FareEconomicsIn,
    booking_gate,
    build_duffel_offer_request,
    calculate_economics,
    duffel_readiness,
)


def test_travel_economics_are_canonical_usd_and_profitable_math_is_explicit():
    result = calculate_economics(FareEconomicsIn(
        net_fare=Decimal("300"), taxes_fees=Decimal("80"), agency_fee=Decimal("25"),
        markup_amount=Decimal("45"), payment_cost=Decimal("12"), support_cost=Decimal("8"),
    ))
    assert result["currency"] == "USD"
    assert result["supplier_cost"] == "380.00"
    assert result["customer_price"] == "450.00"
    assert result["estimated_gross_profit"] == "50.00"


def test_booking_gate_blocks_unknown_or_pending_compliance():
    result = booking_gate(BookingGateIn(
        case_compliance_state="pending", itinerary_compliance_state="cleared",
        case_human_review_required=True, itinerary_human_review_required=False,
        provider_configured=True, provider_health_ok=True, payment_authorized=True, fare_still_valid=True,
    ))
    assert result["release_allowed"] is False
    assert "CASE_COMPLIANCE_NOT_CLEARED" in result["blockers"]
    assert "CASE_HUMAN_REVIEW_REQUIRED" in result["blockers"]


def test_booking_gate_requires_provider_payment_and_fare_revalidation():
    result = booking_gate(BookingGateIn(
        case_compliance_state="cleared", itinerary_compliance_state="cleared",
        case_human_review_required=False, itinerary_human_review_required=False,
        provider_configured=False, provider_health_ok=False, payment_authorized=False, fare_still_valid=False,
    ))
    assert result["release_allowed"] is False
    assert "TICKETING_PROVIDER_NOT_CONFIGURED" in result["blockers"]
    assert "PAYMENT_NOT_AUTHORIZED" in result["blockers"]
    assert "FARE_NOT_REVALIDATED" in result["blockers"]


def test_booking_gate_allows_readiness_only_after_every_control_clears():
    result = booking_gate(BookingGateIn(
        case_compliance_state="cleared", itinerary_compliance_state="cleared",
        case_human_review_required=False, itinerary_human_review_required=False,
        provider_configured=True, provider_health_ok=True, payment_authorized=True, fare_still_valid=True,
    ))
    assert result == {"release_allowed": True, "booking_status": "READY_TO_ISSUE", "blockers": [], "fail_closed": True}


def test_duffel_offer_request_supports_round_trip_and_multiple_adults():
    payload = build_duffel_offer_request(DuffelSearchIn(
        origin="mia", destination="mad", departure_date="2026-11-10", return_date="2026-11-20",
        adults=2, cabin_class="economy", max_connections=1,
    ))
    assert payload["data"]["slices"] == [
        {"origin": "MIA", "destination": "MAD", "departure_date": "2026-11-10"},
        {"origin": "MAD", "destination": "MIA", "departure_date": "2026-11-20"},
    ]
    assert payload["data"]["passengers"] == [{"type": "adult"}, {"type": "adult"}]


def test_duffel_live_ticketing_is_not_enabled_by_token_alone(monkeypatch):
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("DUFFEL_MODE", "live")
    monkeypatch.delenv("TRAVEL_DUFFEL_CONTRACT_APPROVED", raising=False)
    monkeypatch.delenv("TRAVEL_DUFFEL_LIVE_TICKETING_ENABLED", raising=False)
    status = duffel_readiness()
    assert status.configured is True
    assert status.fare_search_allowed is True
    assert status.live_ticketing_allowed is False


def test_duffel_ticketing_requires_all_explicit_live_controls(monkeypatch):
    monkeypatch.setenv("DUFFEL_ACCESS_TOKEN", "live-token")
    monkeypatch.setenv("DUFFEL_MODE", "live")
    monkeypatch.setenv("TRAVEL_DUFFEL_CONTRACT_APPROVED", "true")
    monkeypatch.setenv("TRAVEL_DUFFEL_LIVE_TICKETING_ENABLED", "true")
    status = duffel_readiness()
    assert status.live_ticketing_allowed is True
