from sofia_agentic_sales_os import orchestrate_sales_turn
from sofia_trade_requirement import interpret_buyer_requirement


EXAMPLE = "soybean oil / 2 × 40' containers / 20-L packaging / Mariel / required ASAP"


def test_compact_whatsapp_requirement_is_structured_rfq():
    result = interpret_buyer_requirement(EXAMPLE)
    assert result["trade_intent"] is True
    assert result["rfq_complete"] is True
    assert result["known"]["product"] == "soybean oil"
    assert result["known"]["container_count"] == 2
    assert result["known"]["container_size_ft"] == 40
    assert result["known"]["packaging"] == "20-L"
    assert result["known"]["destination"] == "Mariel"
    assert result["known"]["delivery_timeline"] == "ASAP"


def test_orchestrator_opens_workstreams_but_keeps_commitments_blocked():
    plan = orchestrate_sales_turn(lead_id="wa_test", customer_text=EXAMPLE, stage="QUALIFYING", memory={}, sales_intelligence={"recommended_stage":"RFQ_READY", "missing_fields":["origin", "target budget"]}, crm_context={"crm_connected":True})
    assert plan["missing_fields"] == []
    stages = {item["stage"]: item for item in plan["trade_execution_lifecycle"]}
    assert stages["SUPPLIER_SOURCING"]["status"] == "OPEN"
    assert stages["CONTAINER_UTILIZATION"]["status"] == "OPEN"
    assert stages["COMPLIANCE_CHECK"]["status"] == "OPEN"
    assert stages["LANDED_COST"]["status"] == "BLOCKED"
    assert stages["FORMAL_QUOTE"]["authority"] == "owner_approval"
    assert stages["PURCHASE_ORDER"]["status"] == "BLOCKED"
