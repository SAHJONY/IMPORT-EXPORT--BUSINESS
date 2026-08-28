from cuba_logistics_network_api import _project


def test_national_customs_container_candidate():
    row = {
        "buyer_company": "Example Logistics",
        "verification_status": "OFFICIAL_BUSINESS_SOURCE_VERIFIED",
        "qualification_stage": "LOGISTICS_PARTNER_RESEARCH",
        "risk_level": "MEDIUM",
        "evidence_summary": (
            "Private logistics operator with nationwide coverage in todas las provincias, "
            "customs/aduana services, Mariel container extraction, warehouse, B2B carga comercial "
            "and door-to-door last mile delivery."
        ),
    }
    item = _project(row)
    assert item["binding_actions_allowed"] is False
    assert item["capabilities"]["national_distribution"] is True
    assert item["capabilities"]["customs_clearance"] is True
    assert item["capabilities"]["container_handling"] is True
    assert item["route_readiness"] == "ROUTE_CANDIDATE"


def test_critical_risk_is_fail_closed():
    row = {
        "buyer_company": "Critical Operator",
        "verification_status": "VERIFIED",
        "risk_level": "CRITICAL",
        "evidence_summary": "Nationwide Mariel customs container warehouse B2B door-to-door logistics.",
    }
    item = _project(row)
    assert item["route_readiness_score"] <= 25
    assert item["route_readiness"] == "RESEARCH_ONLY"
    assert item["route_blockers"][0] == "Critical sanctions/ownership/compliance review"
