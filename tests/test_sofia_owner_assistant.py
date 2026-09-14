from sofia_owner_assistant import OWNER_ASSISTANT_CONTRACT, build_owner_mission, classify_owner_request, owner_executive_instructions


def test_owner_assistant_is_private_and_free() -> None:
    assert OWNER_ASSISTANT_CONTRACT["access_cost"] == 0
    assert OWNER_ASSISTANT_CONTRACT["private_workspace"] is True
    assert OWNER_ASSISTANT_CONTRACT["privacy"]["personal_data_visibility"] == "owner_only"


def test_personal_request_uses_owner_private_partition() -> None:
    mission = build_owner_mission("Plan my personal family trip")
    assert mission["mode"] == "personal"
    assert mission["visibility"] == "owner"
    assert mission["data_partition"] == "owner_private"


def test_blended_request_keeps_owner_visibility() -> None:
    assert classify_owner_request("Coordinate my family travel with a business meeting") == "blended"
    mission = build_owner_mission("Coordinate my family travel with a business meeting")
    assert mission["visibility"] == "owner"


def test_irreversible_actions_require_owner_confirmation() -> None:
    mission = build_owner_mission("Pay an invoice", "business")
    assert mission["execution_policy"]["money_legal_medical_security_or_irreversible_actions"] == "explicit_owner_confirmation"


def test_fortune_500_executive_style_is_enforced() -> None:
    style = OWNER_ASSISTANT_CONTRACT["executive_style"]
    assert style["standard"] == "fortune_500_private_office"
    assert style["briefing_order"][0] == "bottom_line"
    assert "hype" in style["avoid"]
    mission = build_owner_mission("Review today's priorities")
    assert mission["response_standard"]["lead_with"] == "bottom_line"
    instructions = owner_executive_instructions()
    assert "Fortune 500" in instructions
    assert "owner-only" in instructions


def test_human_quality_without_deceptive_impersonation() -> None:
    quality = OWNER_ASSISTANT_CONTRACT["executive_style"]["human_quality"]
    assert quality["natural_conversation"] is True
    assert quality["emotional_intelligence"] is True
    assert quality["human_impersonation"] is False
    assert "Never falsely claim" in owner_executive_instructions()


def test_owner_business_data_uses_connected_sources_before_upload_requests() -> None:
    policy = OWNER_ASSISTANT_CONTRACT["connected_data_policy"]
    assert policy["live_sources_first"] is True
    assert policy["never_request_export_when_connected_source_is_available"] is True
    mission = build_owner_mission("Pull a fresh CRM update report")
    assert mission["execution_policy"]["connected_business_data"] == "query_live_source_before_requesting_upload"
    instructions = owner_executive_instructions()
    assert "connected production systems first" in instructions
    assert "Do not ask Juan for a CSV" in instructions
    assert "after a real live-source access attempt fails" in instructions


def test_owner_execute_first_forbids_generic_requirement_checklist() -> None:
    policy = OWNER_ASSISTANT_CONTRACT["owner_execute_first_policy"]
    assert policy["generic_requirements_checklist_forbidden"] is True
    assert policy["connected_context_before_questions"] is True
    assert policy["ask_only_single_genuine_blocker"] is True
    mission = build_owner_mission("Proceed with the SAHJONY update report")
    assert mission["execution_policy"]["owner_execute_first"] == "infer_context_use_connected_systems_execute_then_report"
    instructions = owner_executive_instructions()
    assert "generic requirements checklist" in instructions
    assert "single minimum missing fact" in instructions
    assert "endpoints, credentials, or access details" in instructions
