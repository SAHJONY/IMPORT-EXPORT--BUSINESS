"""Owner-entered commercial worksheets; never payment or shipment authority."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

COSTS = ('goods', 'origin_transport', 'export_documents', 'international_freight',
         'insurance', 'customs_broker', 'duties_taxes', 'destination_delivery',
         'payment_fees', 'other_costs', 'contingency')

class CostLine(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    amount: Decimal | None = Field(default=None, ge=0, le=Decimal('1000000000'), decimal_places=2)
    evidence: str = Field(default='', max_length=1000)

class DealWorksheet(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=240)
    buyer: str = Field(default='', max_length=240)
    buyer_contact: str = Field(default='', max_length=320)
    supplier: str = Field(default='', max_length=240)
    product_spec: str = Field(default='', max_length=1200)
    quantity: Decimal | None = Field(default=None, gt=0, le=Decimal('1000000000'))
    unit: str = Field(default='', max_length=40)
    origin: str = Field(default='', max_length=160)
    destination: str = Field(default='Cuba', max_length=160)
    incoterm: str = Field(default='', max_length=120)
    currency: Literal['USD'] = 'USD'
    buyer_evidence: str = Field(default='', max_length=1000)
    supplier_quote_evidence: str = Field(default='', max_length=1000)
    quote_valid_until: date | None = None
    buyer_payment_terms: str = Field(default='', max_length=500)
    supplier_payment_terms: str = Field(default='', max_length=500)
    transaction_review_evidence: str = Field(default='', max_length=1000)
    sale_total: Decimal | None = Field(default=None, gt=0, le=Decimal('1000000000'), decimal_places=2)
    buyer_deposit_available: Decimal = Field(default=Decimal('0'), ge=0, le=Decimal('1000000000'), decimal_places=2)
    target_margin_pct: Decimal = Field(default=Decimal('18'), ge=0, lt=95)
    next_action: str = Field(default='', max_length=1000)
    action_due: date | None = None
    costs: dict[str, CostLine] = Field(default_factory=dict)

    @field_validator('costs')
    @classmethod
    def known_costs(cls, value):
        if set(value)-set(COSTS):
            raise ValueError('Unknown cost category')
        return value


def evaluate(p: DealWorksheet, today: date | None = None):
    today = today or date.today()
    unknown = [key for key in COSTS if key not in p.costs or p.costs[key].amount is None]
    unsupported = [key for key in COSTS if key in p.costs and p.costs[key].amount is not None and not p.costs[key].evidence.strip()]
    blockers = ['Missing cost: '+key for key in unknown] + ['Cost evidence needed: '+key for key in unsupported]
    for name in ('buyer','buyer_contact','supplier','product_spec','quantity','unit','origin','destination','incoterm','buyer_evidence','supplier_quote_evidence','buyer_payment_terms','supplier_payment_terms','transaction_review_evidence','next_action'):
        if not getattr(p,name): blockers.append('Required: '+name)
    if p.quote_valid_until is None: blockers.append('Supplier quote expiry required')
    elif p.quote_valid_until < today: blockers.append('Supplier quote expired')
    if p.sale_total is None: blockers.append('Buyer sale total required')
    if p.sale_total is not None and p.buyer_deposit_available > p.sale_total: blockers.append('Buyer deposit exceeds sale total')
    total = sum((v.amount for k,v in p.costs.items() if k in COSTS and v.amount is not None), Decimal('0'))
    def rounded(v): return float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    complete = not unknown
    profit = p.sale_total-total if complete and p.sale_total is not None else None
    margin = profit/p.sale_total*100 if profit is not None else None
    if complete and total <= 0: blockers.append('Total cost must be greater than zero')
    if margin is not None and margin < p.target_margin_pct: blockers.append('Projected margin below target')
    if profit is not None and profit <= 0: blockers.append('No positive projected contribution')
    if p.action_due and p.action_due < today: blockers.append('Next action overdue')
    return {'status':'OWNER_REVIEW_READY' if not blockers else 'INPUTS_REQUIRED',
            'costs_complete':complete,'known_cost_subtotal':rounded(total),
            'delivered_cost':rounded(total) if complete else None,
            'projected_contribution':rounded(profit) if profit is not None else None,
            'projected_margin_pct':rounded(margin) if margin is not None else None,
            'target_sale_total':rounded(total/(1-p.target_margin_pct/100)) if complete and total>0 else None,
            'full_cost_funding_gap':rounded(max(Decimal('0'),total-p.buyer_deposit_available)) if complete else None,
            'blockers':blockers,'collected_profit':None,'release_authorized':False,
            'basis':'Owner-entered estimates. Evidence references are not independently verified. Contribution excludes unentered overhead and income taxes; funding gap assumes all costs precede final collection.'}
