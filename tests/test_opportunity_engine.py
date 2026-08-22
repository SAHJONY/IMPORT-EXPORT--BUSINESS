from opportunity_engine import opportunity_engine
from trade_os import TradeScenario


def make_case(**overrides):
    values = {
        "mode": "import",
        "origin_country": "Canada",
        "destination_country": "United States",
        "product": "Machine part",
        "hs_code": "848390",
        "quantity": 100,
        "unit_cost": 10,
        "freight_cost": 100,
        "insurance_cost": 10,
        "duty_rate_pct": 2,
        "broker_fees": 25,
        "inland_cost": 50,
        "target_sale_price_per_unit": 22,
        "incoterm": "FOB",
        "supplier_verified": True,
        "buyer_verified": True,
        "documents_complete": True,
        "sanctions_screened": True,
        "product_regulatory_reviewed": True,
    }
    values.update(overrides)
    return TradeScenario(**values)


def test_ready_case_receives_positive_score():
    result = opportunity_engine.score(make_case())
    assert result.release_gate == "READY"
    assert result.rank_score > 0


def test_hold_case_stays_hold():
    result = opportunity_engine.score(make_case(sanctions_screened=False, target_sale_price_per_unit=100))
    assert result.release_gate == "HOLD"
    assert result.decision == "HOLD"


def test_rank_returns_sorted_results():
    ranked = opportunity_engine.rank([
        make_case(product="Case A", target_sale_price_per_unit=15),
        make_case(product="Case B", target_sale_price_per_unit=28),
    ])
    assert ranked[0]["rank_score"] >= ranked[1]["rank_score"]
    assert ranked[0]["rank"] == 1
