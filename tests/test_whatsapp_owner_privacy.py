import whatsapp_api


def test_phone_match_normalizes_e164() -> None:
    assert whatsapp_api._same_phone("+1 (312) 555-0100", "+13125550100") is True


def test_phone_match_rejects_different_numbers() -> None:
    assert whatsapp_api._same_phone("+13125550100", "+13125550101") is False


def test_owner_records_never_enter_growth_queue() -> None:
    from sofia_crm_growth_engine import build_growth_queue

    queue = build_growth_queue([], [], [], [{
        "lead_id": "owner",
        "phone": "+13125550100",
        "actor_role": "owner",
        "owner_private": True,
        "status": "NEW",
    }])
    assert queue == []
