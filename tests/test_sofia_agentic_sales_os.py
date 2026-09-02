from sofia_agentic_sales_os import action_authority, orchestrate_sales_turn, score_opportunity


def test_binding_and_prohibited_actions_are_fail_closed():
    assert action_authority("prepare_rfq") == "autonomous"
    assert action_authority("accept_price") == "owner_approval"
    assert action_authority("bypass_compliance") == "prohibited"


def test_opt_out_overrides_opportunity_scoring_and_outreach():
    plan = orchestrate_sales_turn(
        lead_id="wa_1",
        customer_text="STOP",
        stage="OPTED_OUT",
        memory={"known": {"product": "coffee"}},
        sales_intelligence={"opportunity_score": 99, "recommended_stage": "OPTED_OUT"},
    )
    assert plan["deal_score"]["total"] == 0
    assert plan["consent"]["outbound_allowed"] is False
    assert plan["next_best_action"]["action"] == "record_opt_out"


def test_complete_qualified_deal_prepares_non_binding_rfq():
    memory = {"known": {
        "product": "green coffee", "specification": "grade 1", "quantity": "1 container",
        "origin": "Colombia", "destination": "Houston", "delivery_timeline": "Q4",
        "target_budget": "market competitive",
    }}
    plan = orchestrate_sales_turn(
        lead_id="wa_2", customer_text="Please prepare the RFQ", stage="QUALIFIED",
        memory=memory,
        sales_intelligence={"opportunity_score": 88, "recommended_stage": "RFQ_READY"},
        crm_context={"crm_connected": True},
    )
    assert plan["missing_fields"] == []
    assert plan["next_best_action"]["action"] == "prepare_rfq"
    assert plan["next_best_action"]["authority"] == "autonomous"
    assert plan["binding_commitment_allowed"] is False


def test_score_is_explainable_and_bounded():
    score = score_opportunity(
        stage="NEGOTIATING",
        known_fields={"product": "oil", "quantity": "1000 MT", "destination": "US"},
        model_score=100,
        risk_flags=["sanctions_review"],
        opted_out=False,
    )
    assert 0 <= score.total <= 100
    assert score.risk_penalty == 7
    assert score.explanation
