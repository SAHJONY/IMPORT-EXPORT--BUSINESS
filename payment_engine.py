from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Audience = Literal['INDIVIDUAL_CONSUMER', 'BUSINESS_CUSTOMER']
PaymentStatus = Literal[
    'DRAFT', 'AWAITING_COMPLIANCE', 'READY_TO_INVOICE', 'AWAITING_PAYMENT',
    'PARTIALLY_PAID', 'PAID', 'ON_HOLD', 'REFUND_REVIEW', 'REFUNDED', 'CLOSED'
]
PaymentRail = Literal['ACH', 'BANK_WIRE', 'CARD_PROCESSOR', 'OTHER_APPROVED_USD_RAIL']


class PaymentError(ValueError):
    pass


def usd(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PaymentPolicy:
    audience: Audience
    currency: str = 'USD'
    automatic_supplier_payout: bool = False
    automatic_shipment_release: bool = False
    compliance_required_before_payment: bool = True
    owner_release_required: bool = True


CONSUMER_PAYMENT_POLICY = PaymentPolicy(audience='INDIVIDUAL_CONSUMER')
BUSINESS_PAYMENT_POLICY = PaymentPolicy(audience='BUSINESS_CUSTOMER')


def validate_currency(currency: str) -> str:
    if str(currency).upper() != 'USD':
        raise PaymentError('All SAHJONY transactions must be denominated in USD')
    return 'USD'


def payment_plan(*, audience: Audience, total_amount: float, deposit_amount: float = 0,
                 currency: str = 'USD', compliance_cleared: bool = False,
                 quote_approved: bool = False) -> dict:
    validate_currency(currency)
    total = usd(total_amount)
    deposit = usd(deposit_amount)
    if total <= 0:
        raise PaymentError('Total amount must be greater than zero')
    if deposit < 0 or deposit > total:
        raise PaymentError('Deposit must be between zero and total amount')
    if audience == 'INDIVIDUAL_CONSUMER' and deposit not in {Decimal('0.00'), total}:
        raise PaymentError('Individual consumer transactions use full-payment terms unless Owner explicitly creates an exception')
    if not quote_approved:
        status: PaymentStatus = 'DRAFT'
    elif not compliance_cleared:
        status = 'AWAITING_COMPLIANCE'
    else:
        status = 'READY_TO_INVOICE'
    amount_due_now = total if deposit == 0 else deposit
    balance_after_initial = total - amount_due_now
    return {
        'audience': audience,
        'currency': 'USD',
        'total_amount': float(total),
        'amount_due_now': float(amount_due_now),
        'balance_after_initial_payment': float(balance_after_initial),
        'status': status,
        'payment_allowed': bool(quote_approved and compliance_cleared),
        'supplier_payout_allowed': False,
        'shipment_release_allowed': False,
        'owner_release_required': True,
    }


def reconcile(*, total_amount: float, customer_paid: float, supplier_cost: float,
              freight_cost: float = 0, duties_fees: float = 0, payment_fees: float = 0,
              other_costs: float = 0, currency: str = 'USD') -> dict:
    validate_currency(currency)
    total = usd(total_amount)
    paid = usd(customer_paid)
    costs = [usd(x) for x in [supplier_cost, freight_cost, duties_fees, payment_fees, other_costs]]
    if any(x < 0 for x in [total, paid, *costs]):
        raise PaymentError('Amounts cannot be negative')
    total_cost = sum(costs, Decimal('0.00'))
    gross_profit = paid - total_cost
    outstanding = max(total - paid, Decimal('0.00'))
    return {
        'currency': 'USD',
        'customer_total': float(total),
        'customer_paid': float(paid),
        'outstanding_balance': float(outstanding),
        'total_direct_cost': float(total_cost),
        'gross_profit': float(gross_profit),
        'fully_paid': paid >= total,
        'supplier_payout_allowed': False,
        'shipment_release_allowed': False,
        'owner_release_required': True,
    }


def policy_snapshot() -> dict:
    return {
        'consumer': asdict(CONSUMER_PAYMENT_POLICY),
        'business': asdict(BUSINESS_PAYMENT_POLICY),
        'hard_rules': [
            'USD_ONLY',
            'NO_PAYMENT_BEFORE_QUOTE_AND_COMPLIANCE_CLEARANCE',
            'NO_AUTOMATIC_SUPPLIER_PAYOUT',
            'NO_AUTOMATIC_SHIPMENT_RELEASE',
            'OWNER_RELEASE_REQUIRED',
        ],
    }
