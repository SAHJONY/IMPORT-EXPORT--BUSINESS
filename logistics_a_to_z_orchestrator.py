from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Stage = Literal[
    'INTAKE','CUSTOMER_VERIFIED','QUOTE_PRELIMINARY','QUOTE_FIRM','PAYMENT_CLEARED',
    'PICKUP_SCHEDULED','PICKED_UP','VIRTUAL_HUB_RECEIVED','CONSOLIDATED','GATEWAY_SELECTED',
    'EXPORT_COMPLIANCE_CLEARED','CARRIER_BOOKED','DEPARTED_US','ARRIVED_CUBA',
    'CUSTOMS_RELEASED','LAST_MILE_ASSIGNED','OUT_FOR_DELIVERY','DELIVERED',
    'DELIVERED_WITH_EXCEPTION','CLAIM_OPEN','RECONCILED','CLOSED'
]

ORDERED_STAGES: tuple[Stage, ...] = (
    'INTAKE','CUSTOMER_VERIFIED','QUOTE_PRELIMINARY','QUOTE_FIRM','PAYMENT_CLEARED',
    'PICKUP_SCHEDULED','PICKED_UP','VIRTUAL_HUB_RECEIVED','CONSOLIDATED','GATEWAY_SELECTED',
    'EXPORT_COMPLIANCE_CLEARED','CARRIER_BOOKED','DEPARTED_US','ARRIVED_CUBA',
    'CUSTOMS_RELEASED','LAST_MILE_ASSIGNED','OUT_FOR_DELIVERY','DELIVERED','RECONCILED','CLOSED'
)

EXCEPTION_STAGES = {'DELIVERED_WITH_EXCEPTION','CLAIM_OPEN'}

@dataclass(frozen=True)
class ShipmentControl:
    stage: Stage
    customer_verified: bool = False
    pricing_floor_passed: bool = False
    capacity_confirmed: bool = False
    compliance_cleared: bool = False
    payment_cleared: bool = False
    pickup_provider_verified: bool = False
    virtual_hub_provider_verified: bool = False
    gateway_selected: bool = False
    carrier_booked: bool = False
    customs_released: bool = False
    last_mile_provider_verified: bool = False
    final_address_present: bool = False
    pod_recorded: bool = False
    recipient_verified: bool = False
    exception_open: bool = False
    financial_reconciled: bool = False


def missing_controls_for(target: Stage, c: ShipmentControl) -> list[str]:
    missing: list[str] = []
    gates = {
        'CUSTOMER_VERIFIED': [('customer_verified', c.customer_verified)],
        'QUOTE_FIRM': [
            ('pricing_floor_passed', c.pricing_floor_passed),
            ('capacity_confirmed', c.capacity_confirmed),
            ('compliance_cleared', c.compliance_cleared),
        ],
        'PAYMENT_CLEARED': [('payment_cleared', c.payment_cleared)],
        'PICKUP_SCHEDULED': [('pickup_provider_verified', c.pickup_provider_verified)],
        'VIRTUAL_HUB_RECEIVED': [('virtual_hub_provider_verified', c.virtual_hub_provider_verified)],
        'GATEWAY_SELECTED': [('gateway_selected', c.gateway_selected)],
        'EXPORT_COMPLIANCE_CLEARED': [('compliance_cleared', c.compliance_cleared)],
        'CARRIER_BOOKED': [('carrier_booked', c.carrier_booked)],
        'CUSTOMS_RELEASED': [('customs_released', c.customs_released)],
        'LAST_MILE_ASSIGNED': [('last_mile_provider_verified', c.last_mile_provider_verified)],
        'DELIVERED': [
            ('final_address_present', c.final_address_present),
            ('pod_recorded', c.pod_recorded),
            ('recipient_verified', c.recipient_verified),
        ],
        'RECONCILED': [
            ('financial_reconciled', c.financial_reconciled),
            ('no_open_exception', not c.exception_open),
        ],
        'CLOSED': [
            ('financial_reconciled', c.financial_reconciled),
            ('pod_recorded', c.pod_recorded),
            ('no_open_exception', not c.exception_open),
        ],
    }
    for name, ok in gates.get(target, []):
        if not ok:
            missing.append(name)
    return missing


def can_transition(current: Stage, target: Stage, c: ShipmentControl) -> dict:
    if target in EXCEPTION_STAGES:
        return {'allowed': True, 'missing': [], 'reason': 'EXCEPTION_PATH'}

    if current in EXCEPTION_STAGES and target not in {'RECONCILED','CLOSED'}:
        return {'allowed': False, 'missing': ['exception_resolution'], 'reason': 'EXCEPTION_MUST_BE_RESOLVED'}

    if current not in ORDERED_STAGES or target not in ORDERED_STAGES:
        return {'allowed': False, 'missing': [], 'reason': 'UNSUPPORTED_STAGE'}

    current_index = ORDERED_STAGES.index(current)
    target_index = ORDERED_STAGES.index(target)
    if target_index != current_index + 1:
        return {'allowed': False, 'missing': [], 'reason': 'STAGE_SKIP_NOT_ALLOWED'}

    missing = missing_controls_for(target, c)
    return {
        'allowed': not missing,
        'missing': missing,
        'reason': 'OK' if not missing else 'CONTROL_GATE_BLOCKED',
    }


def lifecycle_blueprint() -> dict:
    return {
        'operating_principles': [
            'DOOR_TO_DOOR_DEFAULT',
            'NO_SCAN_NO_HANDOFF',
            'NO_FINAL_ADDRESS_DELIVERY_PLUS_POD_EQUALS_NOT_COMPLETE',
            'NO_FIRM_QUOTE_WITHOUT_MARGIN_CAPACITY_AND_COMPLIANCE',
            'NO_PROVIDER_BOOKING_WITHOUT_VERIFICATION',
            'NO_CLOSE_WITH_OPEN_EXCEPTION_OR_UNRECONCILED_FINANCIALS',
        ],
        'stages': list(ORDERED_STAGES),
        'exception_stages': sorted(EXCEPTION_STAGES),
        'provider_chain': [
            'AGENCY_OR_HOME_COLLECTION_PARTNER',
            'LOCAL_TRUCKING_OR_FIRST_MILE',
            'LOCAL_CITY_VIRTUAL_HUB',
            'DOMESTIC_LINEHAUL',
            'EXPORT_GATEWAY_PORT_OR_AIRPORT',
            'INTERNATIONAL_CARRIER',
            'CUBA_DESTINATION_OPERATOR',
            'LAST_MILE_PROVIDER',
            'RECIPIENT_HOME_OR_BUSINESS',
        ],
        'required_operating_tracks': [
            'CUSTOMER_AND_KYB_KYC',
            'CARGO_CLASSIFICATION_AND_COMPLIANCE',
            'PRICING_MARGIN_AND_COLLECTIONS',
            'PROVIDER_PROCUREMENT_AND_CAPACITY',
            'DOCUMENTS_AND_CUSTOMS',
            'TRACKING_AND_CHAIN_OF_CUSTODY',
            'DELIVERY_POD_AND_RECIPIENT_VERIFICATION',
            'EXCEPTIONS_CLAIMS_AND_INSURANCE',
            'SETTLEMENT_RECONCILIATION_AND_PROFITABILITY',
        ],
    }
