from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Literal

Decision = Literal['ALLOW','BLOCK','OWNER_EXCEPTION_REQUIRED']


@dataclass(frozen=True)
class ZeroOwnMoneyPolicy:
    enabled: bool = True
    require_customer_funds_or_secured_terms: bool = True
    require_provider_cost_coverage: bool = True
    require_contingency_coverage: bool = True
    require_minimum_gp: bool = True
    minimum_gp_usd: Decimal = Decimal('5.00')
    prohibit_inventory_prebuy: bool = True
    prohibit_unfunded_provider_deposits: bool = True
    prohibit_unfunded_freight_booking: bool = True
    prohibit_unfunded_pickup: bool = True
    prohibit_unfunded_claim_advances: bool = True
    prohibit_unfunded_customs_duties: bool = True
    prohibit_unfunded_last_mile: bool = True
    owner_exception_allowed: bool = True


DEFAULT_POLICY = ZeroOwnMoneyPolicy()


def evaluate_commitment(
    *,
    customer_funds_cleared: Decimal,
    secured_provider_credit: Decimal = Decimal('0'),
    provider_cost: Decimal,
    contingency_reserve: Decimal = Decimal('0'),
    expected_customer_revenue: Decimal,
    minimum_gp_usd: Decimal | None = None,
    compliance_cleared: bool = False,
    provider_verified: bool = False,
    capacity_confirmed: bool = False,
    binding_commitment: bool = True,
    policy: ZeroOwnMoneyPolicy = DEFAULT_POLICY,
) -> dict:
    minimum_gp = minimum_gp_usd if minimum_gp_usd is not None else policy.minimum_gp_usd
    covered_funds = customer_funds_cleared + secured_provider_credit
    required_coverage = provider_cost + contingency_reserve
    expected_gp = expected_customer_revenue - required_coverage

    blockers: list[str] = []
    if binding_commitment:
        if not provider_verified:
            blockers.append('PROVIDER_NOT_VERIFIED')
        if not capacity_confirmed:
            blockers.append('CAPACITY_NOT_CONFIRMED')
        if not compliance_cleared:
            blockers.append('COMPLIANCE_NOT_CLEARED')
        if policy.require_customer_funds_or_secured_terms and covered_funds < required_coverage:
            blockers.append('UNFUNDED_PROVIDER_EXPOSURE')
        if policy.require_minimum_gp and expected_gp < minimum_gp:
            blockers.append('MINIMUM_GP_NOT_PROTECTED')

    own_money_exposure = max(Decimal('0'), required_coverage - covered_funds)
    decision: Decision = 'ALLOW' if not blockers else 'BLOCK'

    return {
        'decision': decision,
        'zero_own_money_policy': policy.enabled,
        'binding_commitment_allowed': decision == 'ALLOW',
        'customer_funds_cleared': float(customer_funds_cleared),
        'secured_provider_credit': float(secured_provider_credit),
        'provider_cost': float(provider_cost),
        'contingency_reserve': float(contingency_reserve),
        'required_coverage': float(required_coverage),
        'covered_funds': float(covered_funds),
        'own_money_exposure': float(own_money_exposure),
        'expected_customer_revenue': float(expected_customer_revenue),
        'expected_gp': float(expected_gp),
        'minimum_gp_usd': float(minimum_gp),
        'blockers': blockers,
        'rule': 'NO CUSTOMER FUNDS OR SECURED PROVIDER TERMS = NO BINDING COMMITMENT. SAHJONY OWN-MONEY EXPOSURE MUST REMAIN ZERO.',
    }


def policy_snapshot() -> dict:
    row = asdict(DEFAULT_POLICY)
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
