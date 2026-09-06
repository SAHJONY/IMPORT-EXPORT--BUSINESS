from sofia_crm_growth_engine import build_growth_queue, growth_health, score_crm_lead


def test_do_not_contact_overrides_lead_score() -> None:
    result = score_crm_lead({"customer_id": "c1", "sales_status": "DO_NOT_CONTACT", "email": "lead@example.com"})
    assert result["score"] == 0
    assert result["blocked"] is True
    assert result["autonomous_outreach_allowed"] is False


def test_unconsented_lead_is_research_only() -> None:
    result = score_crm_lead({"customer_id": "c1", "sales_status": "NEW", "email": "lead@example.com"})
    assert result["contactable"] is True
    assert result["autonomous_outreach_allowed"] is False
    assert "consent-compatible" in result["next_best_action"]
    assert "do not transfer research responsibility to the owner" in result["next_best_action"]


def test_consented_lead_can_enter_follow_up_queue() -> None:
    result = score_crm_lead({"customer_id": "c1", "sales_status": "FOLLOW_UP_DUE", "email": "lead@example.com", "consent_to_business_contact": True})
    assert result["autonomous_outreach_allowed"] is True
    assert result["score"] > 0


def test_growth_queue_deduplicates_and_prioritizes() -> None:
    accounts = [
        {"customer_id": "c1", "legal_name": "Qualified Buyer", "email": "a@example.com", "sales_status": "REPLIED", "consent_to_business_contact": True},
        {"customer_id": "c2", "legal_name": "Blocked Buyer", "email": "b@example.com", "sales_status": "DO_NOT_CONTACT"},
    ]
    intakes = [{"customer_id": "c1", "product_need": "Industrial pumps"}]
    queue = build_growth_queue(accounts, intakes, [])
    assert [row["lead_ref"] for row in queue] == ["c1", "c2"]
    assert queue[0]["assessment"]["score"] > queue[1]["assessment"]["score"]


def test_health_links_all_crm_sources() -> None:
    health = growth_health()
    assert health["primary_brain"] == "gpt-5.6-sol"
    assert "customer_accounts" in health["crm_sources"]
    assert "whatsapp_leads" in health["crm_sources"]
    assert health["unsolicited_autonomous_outreach"] is False
