from voice_outbound_api import _crm_status, _email_from, _task


def test_outbound_task_collects_crm_identity_without_inventing():
    text = _task("EV charger follow-up", "en-US").lower()
    assert "business email" in text
    assert "autonomously create or update a crm prospect" in text
    assert "never invent an email" in text
    assert "not kyc approval" in text


def test_email_extraction_prefers_verified_metadata():
    assert _email_from("contact me at other@example.com", {"email": "Buyer@Example.com"}) == "buyer@example.com"
    assert _email_from("my email is sales@example.org", {}) == "sales@example.org"
    assert _email_from("there is no email here", {}) is None


def test_qualification_mapping_is_conservative():
    assert _crm_status("QUALIFIED_LEAD") == ("QUALIFIED_LEAD", "QUALIFIED")
    assert _crm_status("FOLLOW_UP_REQUIRED") == ("FOLLOW_UP_DUE", "NEEDS_INFO")
    assert _crm_status("NEEDS_MORE_INFO") == ("FOLLOW_UP_DUE", "NEEDS_INFO")
    assert _crm_status("NO_CONTACT_MADE") == ("CONTACTED", "NEEDS_INFO")


def test_do_not_contact_is_hard_stop():
    assert _crm_status("DO_NOT_CONTACT") == ("DO_NOT_CONTACT", "DISQUALIFIED")
