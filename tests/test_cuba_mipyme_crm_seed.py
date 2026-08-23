from crm_campaign_bootstrap import CAMPAIGN, load_seed


def test_cuba_mipyme_seed_has_ten_unique_verified_outreach_leads():
    leads = load_seed()
    assert len(leads) == 10
    emails = [lead["email"].strip().lower() for lead in leads]
    assert len(set(emails)) == 10
    assert all(lead["campaign"] == CAMPAIGN for lead in leads)
    assert all(lead["outreach_status"] == "SENT" for lead in leads)
    assert all(lead["funnel_url"] == "https://www.sahjony.com/cuba-private-sector" for lead in leads)
    assert all(lead["gmail_message_id"] for lead in leads)
