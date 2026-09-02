from __future__ import annotations

from typing import Any
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title='SAHJONY Verified Trade Network Core', version='1.0.0', docs_url=None, redoc_url=None)

class OpportunityInput(BaseModel):
    buyer_verified: bool = False
    supplier_verified: bool = False
    written_demand: bool = False
    firm_quote: bool = False
    payment_path_verified: bool = False
    logistics_path_verified: bool = False
    compliance_ready: bool = False
    fee_protection_ready: bool = False
    own_capital_required_usd: float = Field(default=0, ge=0)
    estimated_gross_profit_usd: float | None = Field(default=None, ge=0)
    days_to_cash: int | None = Field(default=None, ge=0)


def score(o: OpportunityInput) -> dict[str, Any]:
    points = 0
    gates = {
        'buyer_verified': o.buyer_verified,
        'supplier_verified': o.supplier_verified,
        'written_demand': o.written_demand,
        'firm_quote': o.firm_quote,
        'payment_path_verified': o.payment_path_verified,
        'logistics_path_verified': o.logistics_path_verified,
        'compliance_ready': o.compliance_ready,
        'fee_protection_ready': o.fee_protection_ready,
    }
    weights = {
        'buyer_verified': 15,
        'supplier_verified': 12,
        'written_demand': 15,
        'firm_quote': 15,
        'payment_path_verified': 12,
        'logistics_path_verified': 8,
        'compliance_ready': 13,
        'fee_protection_ready': 10,
    }
    for k, ok in gates.items():
        if ok:
            points += weights[k]
    if o.own_capital_required_usd > 0:
        points = max(0, points - min(30, int(o.own_capital_required_usd / 1000)))
    missing = [k for k, ok in gates.items() if not ok]
    if not o.written_demand:
        stage = 'RESEARCH_OR_UNQUALIFIED'
    elif o.written_demand and not o.firm_quote:
        stage = 'QUALIFIED_DEMAND_SOURCING'
    elif o.firm_quote and not all([o.buyer_verified, o.supplier_verified, o.compliance_ready]):
        stage = 'MATCHED_DUE_DILIGENCE'
    elif all(gates.values()):
        stage = 'TRANSACTION_READY_NONBINDING'
    else:
        stage = 'COMMERCIAL_VALIDATION'
    priority = 'HIGH' if points >= 75 and o.own_capital_required_usd == 0 else 'MEDIUM' if points >= 50 else 'LOW'
    if o.estimated_gross_profit_usd is not None and o.days_to_cash:
        velocity = round(o.estimated_gross_profit_usd / max(1, o.days_to_cash), 2)
    else:
        velocity = None
    return {
        'score': points,
        'priority': priority,
        'stage': stage,
        'missing_gates': missing,
        'estimated_profit_velocity_usd_per_day': velocity,
        'zero_own_capital_target_met': o.own_capital_required_usd == 0,
        'binding': False,
    }

@app.get('/crm/verified-trade-network/health')
async def health():
    return {
        'status':'ok',
        'service':'verified-trade-network-core',
        'version':'1.0.0',
        'positioning':'SAHJONY LLC — The Global Trade Network for Verified Businesses',
        'core_modules':['verified_business_network','sofia_next_best_opportunity','deal_supplier_matching','competition_price_intelligence','deal_room_fee_protection','follow_the_sun_24x7'],
        'commercial_priority':'fastest legitimate collected revenue with minimal SAHJONY capital exposure',
        'research_is_not_demand':True,
        'binding_actions_allowed':False,
    }

@app.post('/crm/verified-trade-network/opportunity-score')
async def opportunity_score(payload: OpportunityInput):
    return {'status':'ok', **score(payload)}
