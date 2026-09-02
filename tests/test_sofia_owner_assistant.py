from sofia_owner_assistant import OWNER_ASSISTANT_CONTRACT, build_owner_mission, classify_owner_request


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
