from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

NetworkRole = Literal[
    'AGENCY','HOME_COLLECTION_PARTNER','LOCAL_TRUCKER','VIRTUAL_HUB_PROVIDER',
    'WAREHOUSE','EXPORT_GATEWAY_PROVIDER','AIR_CARRIER','OCEAN_CARRIER',
    'CUSTOMS_PROVIDER','DESTINATION_OPERATOR','LAST_MILE_PROVIDER'
]

@dataclass(frozen=True)
class NetworkKPI:
    name: str
    target_direction: Literal['HIGHER','LOWER']
    description: str

NETWORK_KPIS = [
    NetworkKPI('COLLECTED_GROSS_PROFIT','HIGHER','Collected gross profit, not quoted or theoretical profit.'),
    NetworkKPI('REVENUE_PER_SHIPMENT','HIGHER','Collected revenue per completed shipment.'),
    NetworkKPI('GROSS_MARGIN_PCT','HIGHER','Gross margin after provider, partner and exception costs.'),
    NetworkKPI('COST_PER_LB_OR_UNIT','LOWER','Fully loaded cost by lane, cargo type and service level.'),
    NetworkKPI('ON_TIME_PICKUP_PCT','HIGHER','Pickup completed inside promised window.'),
    NetworkKPI('ON_TIME_DELIVERY_PCT','HIGHER','Door delivery completed inside promised window.'),
    NetworkKPI('CLAIMS_RATE','LOWER','Claims per completed shipments.'),
    NetworkKPI('DAMAGE_SHORTAGE_RATE','LOWER','Physical exception rate.'),
    NetworkKPI('QUOTE_TO_BOOK_RATE','HIGHER','Firm quotes converted to paid bookings.'),
    NetworkKPI('DAYS_QUOTE_TO_CASH','LOWER','Time from qualified demand to cleared funds.'),
    NetworkKPI('NETWORK_NODE_UTILIZATION','HIGHER','Useful throughput at agencies, virtual hubs and providers.'),
    NetworkKPI('PROVIDER_RELIABILITY_SCORE','HIGHER','Composite capacity, punctuality, custody and claims score.'),
    NetworkKPI('POD_COMPLETENESS','HIGHER','Completed deliveries with valid POD and recipient verification.'),
]

CONTROL_TOWER_TRACKS = {
    'DEMAND': ['customer_intake','agency_intake','rfq_normalization','cargo_classification'],
    'PROCUREMENT': ['provider_discovery','live_lane_tender','capacity_confirmation','rate_normalization','provider_scorecard'],
    'PRICING': ['fully_loaded_cost','competitor_effective_price','margin_floor','agency_margin','partner_share','recommended_sell_price'],
    'COMPLIANCE': ['kyb_kyc','sanctions','cargo_rules','export_rules','destination_rules','document_readiness'],
    'EXECUTION': ['pickup','virtual_hub','domestic_linehaul','consolidation','gateway','international_carrier','customs','last_mile'],
    'CUSTODY': ['qr_identity','scan_out','scan_in','photo_evidence','weight_evidence','handoff_audit'],
    'CUSTOMER': ['single_tracking_record','whatsapp_updates','eta','exception_notice','pod','claim_status'],
    'FINANCE': ['deposit','provider_accruals','agency_share','partner_share','invoice','settlement','reconciliation','collected_gp'],
    'QUALITY': ['sla_monitoring','claims','root_cause','provider_suspension','lane_repricing','continuous_improvement'],
}

MOATS = [
    'DENSE_AGENCY_AND_HOME_PARTNER_COLLECTION_NETWORK',
    'AGGREGATED_BUYING_POWER_FOR_TRUCK_AIR_OCEAN_AND_LAST_MILE',
    'REAL_TIME_LANE_COST_AND_SERVICE_INTELLIGENCE',
    'UNIFIED_DOOR_TO_DOOR_TRACKING_AND_CHAIN_OF_CUSTODY',
    'AGENCY_CUSTOMER_AND_MARGIN_PROTECTION',
    'FAIL_CLOSED_COMPLIANCE_AND_PROVIDER_VERIFICATION',
    'PROPRIETARY_PROVIDER_PERFORMANCE_HISTORY',
    'ONE_ACCOUNT_FOR_BOXES_PALLETS_LCL_FCL_VEHICLES_AND_SPECIAL_CARGO',
]

GROWTH_FLYWHEEL = [
    'ADD_VERIFIED_AGENCIES_AND_COLLECTION_PARTNERS',
    'AGGREGATE_MORE_VOLUME',
    'NEGOTIATE_LOWER_PROVIDER_COSTS_AND_BETTER_TERMS',
    'OFFER BETTER EFFECTIVE DOOR_TO_DOOR PRICE_AND_SERVICE',
    'WIN_MORE AGENCIES_AND CUSTOMERS',
    'INCREASE SHIPMENT DENSITY AND ROUTE UTILIZATION',
    'EXPAND MARGINS WHILE REMAINING COMPETITIVE',
]


def control_tower_blueprint() -> dict:
    return {
        'positioning': 'LOGISTICS_NETWORK_AND_OPERATING_SYSTEM_FOR_AGENCIES',
        'customer_promise': 'ONE_QUOTE_ONE_TRACKING_RECORD_ONE_CHAIN_OF_CUSTODY_ONE_POD_DOOR_TO_DOOR',
        'commercial_rule': 'NEVER_BUY_VOLUME_WITH NEGATIVE_UNIT_ECONOMICS; USE SERVICE VALUE WHEN PRICE CANNOT BE BEAT PROFITABLY',
        'network_roles': list(NetworkRole.__args__),
        'tracks': CONTROL_TOWER_TRACKS,
        'moats': MOATS,
        'growth_flywheel': GROWTH_FLYWHEEL,
        'kpis': [asdict(k) for k in NETWORK_KPIS],
        'north_star': 'QUALITY_ADJUSTED_COLLECTED_GROSS_PROFIT',
    }
