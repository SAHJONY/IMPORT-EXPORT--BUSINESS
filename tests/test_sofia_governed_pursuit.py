import asyncio

import customer_crm_api as crm


def test_pursuit_queues_only_explicitly_autonomous_eligible(monkeypatch) -> None:
    rows = [
        {"lead_ref":"eligible","source":"customer_crm","company":"Eligible","assessment":{"score":90,"blocked":False,"autonomous_outreach_allowed":True,"next_best_action":"follow up"}},
        {"lead_ref":"unconsented","source":"customer_crm","company":"Unconsented","assessment":{"score":80,"blocked":False,"autonomous_outreach_allowed":False,"next_best_action":"owner review"}},
        {"lead_ref":"blocked","source":"customer_crm","company":"Blocked","assessment":{"score":0,"blocked":True,"autonomous_outreach_allowed":False,"next_best_action":"do not contact"}},
    ]
    audits = []

    async def fake_queue():
        return rows

    async def fake_audit(actor, event, summary, customer_id=None, intake_id=None, payload=None):
        audits.append((customer_id, payload))

    monkeypatch.setattr(crm, "_sofia_growth_queue", fake_queue)
    monkeypatch.setattr(crm, "audit", fake_audit)
    monkeypatch.setattr(crm, "identity", lambda *args: {"role":"owner","id":"owner"})

    result = asyncio.run(crm.sofia_pursue(crm.SofiaPursuitIn(limit=50, execute_reversible_steps=True), x_role="owner", authorization="Bearer test", x_employee_id=None))

    assert result["selected"] == 1
    assert result["blocked_or_ineligible"] == 2
    assert result["messages_sent"] == 0
    assert [row["lead_ref"] for row in result["actions"]] == ["eligible"]
    assert [customer_id for customer_id, _ in audits] == ["eligible"]
    assert audits[0][1]["message_sent"] is False
