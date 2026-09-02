import ai_brain_api
import agentic_trade_engine_api
import whatsapp_sales_brain


def test_sol_is_primary_for_every_standard_business_task(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_PRIMARY_MODEL", raising=False)
    for task in (
        "EXECUTIVE_STRATEGY",
        "SUPPLIER_RESEARCH",
        "TRADE_RESEARCH",
        "DOCUMENT_ANALYSIS",
        "NEGOTIATION_SUPPORT",
        "COMPLIANCE_ANALYSIS",
        "PAYMENT_ANALYSIS",
        "LOGISTICS_ANALYSIS",
        "CUSTOMER_RESPONSE",
        "GENERAL_ANALYSIS",
    ):
        primary_provider, primary_model, _, _ = ai_brain_api.route(task, "AUTO", False)
        assert primary_provider == "openai"
        assert primary_model == "gpt-5.6-sol"


def test_high_stakes_uses_sol_primary_and_anthropic_review(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_PRIMARY_MODEL", raising=False)
    primary_provider, primary_model, reviewer_provider, reviewer_model = ai_brain_api.route(
        "EXECUTIVE_STRATEGY", "AUTO", True
    )
    assert (primary_provider, primary_model) == ("openai", "gpt-5.6-sol")
    assert reviewer_provider == "anthropic"
    assert reviewer_model


def test_trade_engine_keeps_sol_first_in_consensus(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_PRIMARY_MODEL", raising=False)
    providers, high = agentic_trade_engine_api.route("EXECUTIVE_DECISION", "AUTO")
    assert high is True
    assert providers[0] == ("openai", "gpt-5.6-sol")
    assert providers[1][0] == "anthropic"


def test_whatsapp_all_openai_workload_tiers_use_sol() -> None:
    for complexity in ("fast", "normal", "critical", "rfq", "triage"):
        model, effort = whatsapp_sales_brain.choose_openai_model(complexity)
        assert model == "gpt-5.6-sol"
        assert effort in {"low", "medium", "high"}


def test_sales_health_describes_anthropic_as_review_layer() -> None:
    health = whatsapp_sales_brain.frontier_status()
    assert health["primary_reasoning_authority"] == "gpt-5.6-sol"
    assert health["anthropic_role"] == "independent_review_consensus_and_resilience"
    assert health["co_brain_consensus"] is True
