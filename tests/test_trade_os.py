from agentic_control_plane import control_plane
from trade_os import TradeScenario


def base_scenario(**overrides):
    data = {
        "mode": "import",
        "origin_country": "Mexico",
        "destination_country": "United States",
        "product": "Fresh avocados",
        "hs_code": "080440",
        "quantity": 1000,
        "unit_cost": 1.0,
        "freight_cost": 250,
        "insurance_cost": 25,
        "duty_rate_pct": 0,
        "broker_fees": 100,
        "inland_cost": 125,
        "target_sale_price_per_unit": 2.5,
        "incoterm": "FOB",
        "supplier_verified": True,
        "buyer_verified": True,
        "documents_complete": True,
        "sanctions_screened": True,
        "product_regulatory_reviewed": True,
    }
    data.update(overrides)
    return TradeScenario(**data)


def test_ready_scenario_can_release():
    result = control_plane.evaluate(base_scenario())
    assert result["decision"]["release_gate"] == "READY"
    assert result["governance"]["ai_override_allowed"] is False


def test_missing_sanctions_screen_blocks_release():
    result = control_plane.evaluate(base_scenario(sanctions_screened=False))
    assert result["decision"]["release_gate"] == "HOLD"
    assert result["decision"]["risk_level"] == "blocked"


def test_missing_classification_blocks_release():
    result = control_plane.evaluate(base_scenario(hs_code=None))
    assert result["decision"]["release_gate"] == "HOLD"


def test_agent_registry_is_multi_agent():
    agents = control_plane.registry()
    assert len(agents) >= 10
    assert any(a["can_block_release"] for a in agents)
