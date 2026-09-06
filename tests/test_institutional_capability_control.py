from institutional_capability_api import CAPABILITIES
from sofia_crm_growth_engine import score_crm_lead


def test_ten_institutional_capabilities_are_explicit_and_unique():
    assert len(CAPABILITIES) == 10
    keys=[row[0] for row in CAPABILITIES]
    assert len(set(keys)) == 10
    assert {'crm_sync','supplier_intelligence','rfq_qualification','pricing_margin','kyb_compliance','logistics','executive_comms','deal_room','production_health','business_intelligence'} == set(keys)


def test_transactional_reply_allows_contextual_followup_without_marketing_claim():
    result=score_crm_lead({
        'customer_id':'c1','legal_name':'Example Buyer','email':'buyer@example.com','sales_status':'REPLIED',
        'consent_status':'TRANSACTIONAL_ONLY','last_reply_at':'2026-09-05T12:00:00Z','engagement_evidence':'gmail:abc',
    })
    assert result['recommended_stage'] == 'ENGAGED'
    assert result['autonomous_outreach_allowed'] is True
    assert result['verified_demand'] is False
    assert result['binding_commitment_allowed'] is False


def test_research_contact_without_relationship_stays_ineligible():
    result=score_crm_lead({'customer_id':'c2','legal_name':'Research Lead','email':'lead@example.com','sales_status':'NEW'})
    assert result['autonomous_outreach_allowed'] is False
    assert result['verified_demand'] is False
