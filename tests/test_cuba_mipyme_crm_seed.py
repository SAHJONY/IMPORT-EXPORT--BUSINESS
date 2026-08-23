from crm_campaign_bootstrap import CAMPAIGN, load_seed


def test_cuba_mipyme_seed_has_governed_unique_outreach_records():
    leads = load_seed()
    assert len(leads) >= 10
    emails = [lead["email"].strip().lower() for lead in leads]
    assert len(set(emails)) == len(leads)
    assert all(lead["campaign"] == CAMPAIGN for lead in leads)
    allowed_statuses = {"SENT", "BOUNCED_INVALID_ADDRESS"}
    assert all(lead["outreach_status"] in allowed_statuses for lead in leads)
    assert sum(lead["outreach_status"] == "SENT" for lead in leads) >= 10
    allowed_funnels = {
        "https://www.sahjony.com/cuba-private-sector",
        "https://www.sahjony.com/start",
    }
    assert all(lead["funnel_url"] in allowed_funnels for lead in leads)
    assert all(lead["gmail_message_id"] for lead in leads)
