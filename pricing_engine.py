from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Audience = Literal['INDIVIDUAL_CONSUMER', 'BUSINESS_CUSTOMER']


def money(v: float | int | str | Decimal) -> Decimal:
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricingPolicy:
    audience: Audience
    minimum_margin_pct: Decimal
    default_margin_pct: Decimal
    fx_buffer_pct: Decimal
    quote_valid_hours: int
    volume_pricing: bool
    customer_can_see_cost_basis: bool = False


CONSUMER_POLICY = PricingPolicy(
    audience='INDIVIDUAL_CONSUMER',
    minimum_margin_pct=Decimal('20.00'),
    default_margin_pct=Decimal('30.00'),
    fx_buffer_pct=Decimal('3.00'),
    quote_valid_hours=72,
    volume_pricing=False,
)

BUSINESS_POLICY = PricingPolicy(
    audience='BUSINESS_CUSTOMER',
    minimum_margin_pct=Decimal('10.00'),
    default_margin_pct=Decimal('18.00'),
    fx_buffer_pct=Decimal('2.00'),
    quote_valid_hours=168,
    volume_pricing=True,
)


class PricingError(ValueError):
    pass


def _pct(base: Decimal, pct: Decimal) -> Decimal:
    return (base * pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _quote(*, policy: PricingPolicy, supplier_cost: float, international_freight: float = 0, local_delivery: float = 0,
           compliance_cost: float = 0, payment_cost: float = 0, handling_cost: float = 0, support_cost: float = 0,
           insurance_cost: float = 0, duty_tax_cost: float = 0, requested_margin_pct: float | None = None,
           volume_discount_pct: float = 0) -> dict:
    components = [money(x) for x in [supplier_cost, international_freight, local_delivery, compliance_cost, payment_cost,
                                     handling_cost, support_cost, insurance_cost, duty_tax_cost]]
    if any(x < 0 for x in components):
        raise PricingError('Pricing components cannot be negative')
    landed = sum(components, Decimal('0.00'))
    if landed <= 0:
        raise PricingError('Landed cost must be greater than zero')

    margin = money(requested_margin_pct if requested_margin_pct is not None else policy.default_margin_pct)
    if margin < policy.minimum_margin_pct:
        raise PricingError(f'Margin below {policy.audience} minimum floor')
    if margin >= Decimal('95'):
        raise PricingError('Margin percentage is not commercially valid')

    if volume_discount_pct and not policy.volume_pricing:
        raise PricingError('Volume discounts are not available in consumer pricing')
    volume_discount = money(volume_discount_pct)
    if volume_discount < 0 or volume_discount > Decimal('30'):
        raise PricingError('Volume discount must be between 0 and 30 percent')

    fx_buffer = _pct(landed, policy.fx_buffer_pct)
    protected_cost = landed + fx_buffer
    gross_price = (protected_cost / (Decimal('1') - margin / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    discount_amount = _pct(gross_price, volume_discount)
    customer_price = money(gross_price - discount_amount)
    gross_profit = money(customer_price - landed)
    realized_margin = money((gross_profit / customer_price) * Decimal('100')) if customer_price else Decimal('0')

    # Volume discount may never break the audience-specific minimum margin floor.
    if realized_margin < policy.minimum_margin_pct:
        raise PricingError('Discount would breach minimum margin floor')

    return {
        'audience': policy.audience,
        'customer_price': float(customer_price),
        'currency': 'USD',
        'quote_valid_hours': policy.quote_valid_hours,
        'pricing_release': 'OWNER_REVIEW_REQUIRED',
        'margin_floor_passed': True,
        'volume_pricing': policy.volume_pricing,
        'internal': {
            'landed_cost': float(landed),
            'fx_buffer': float(fx_buffer),
            'gross_profit': float(gross_profit),
            'realized_margin_pct': float(realized_margin),
            'requested_margin_pct': float(margin),
            'volume_discount_pct': float(volume_discount),
        },
    }


def consumer_quote(**kwargs) -> dict:
    """Retail-style quote. No MOQ/volume discount and no business pricing leakage."""
    kwargs.pop('volume_discount_pct', None)
    return _quote(policy=CONSUMER_POLICY, volume_discount_pct=0, **kwargs)


def business_quote(**kwargs) -> dict:
    """Commercial quote with owner-governed volume economics."""
    return _quote(policy=BUSINESS_POLICY, **kwargs)


def public_quote_view(quote: dict) -> dict:
    """Return only customer-safe pricing fields; never expose cost basis or margin internals."""
    return {k: v for k, v in quote.items() if k != 'internal'}


def policy_snapshot() -> dict:
    return {
        'consumer': {k: (float(v) if isinstance(v, Decimal) else v) for k, v in asdict(CONSUMER_POLICY).items()},
        'business': {k: (float(v) if isinstance(v, Decimal) else v) for k, v in asdict(BUSINESS_POLICY).items()},
        'hard_rule': 'INDIVIDUAL_CONSUMER_PRICE_NEVER_EQUALS_BUSINESS_PRICE_BY_SHARED_PRICE_RECORD',
    }
