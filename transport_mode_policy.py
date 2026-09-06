from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransportMode = Literal['AIR', 'SEA', 'MULTIMODAL']
LoadMode = Literal['SINGLE_ITEM', 'BOXES', 'PALLET', 'LCL', 'FCL', 'VEHICLE', 'MOTORCYCLE', 'OVERSIZED', 'SPECIAL']

AIR_FLOW = [
    'INTAKE', 'COMPLIANCE_REVIEW', 'WAREHOUSE_IN', 'AIR_CONSOLIDATION',
    'HAWB_READY', 'MAWB_READY', 'CARRIER_HANDOFF', 'DEPARTED',
    'ARRIVED_DESTINATION', 'CUSTOMS', 'LAST_MILE', 'POD', 'RECONCILED',
]
SEA_FLOW = [
    'INTAKE', 'COMPLIANCE_REVIEW', 'WAREHOUSE_IN', 'LCL_OR_FCL_DECISION',
    'SEA_CONSOLIDATION_OR_CONTAINER_LOAD', 'HBL_READY', 'MBL_READY',
    'CARRIER_HANDOFF', 'DEPARTED', 'ARRIVED_DESTINATION', 'CUSTOMS',
    'LAST_MILE', 'POD', 'RECONCILED',
]

AIR_DOCUMENTS = ['AIR_WAYBILL', 'HAWB', 'MAWB', 'CARGO_MANIFEST']
SEA_DOCUMENTS = ['BILL_OF_LADING', 'HBL', 'MBL', 'CARGO_MANIFEST', 'CONTAINER_PACKING_LIST']

@dataclass(frozen=True)
class ModeRecommendation:
    mode: TransportMode
    load_mode: LoadMode
    reason: str
    requires_manual_review: bool = False


def recommend_transport_mode(*, load_mode: LoadMode, urgent: bool = False,
                              weight_lb: float | None = None,
                              volume_cbm: float | None = None,
                              dangerous_goods: bool = False,
                              battery_or_fuel: bool = False,
                              oversized: bool = False) -> ModeRecommendation:
    if load_mode in {'VEHICLE', 'MOTORCYCLE', 'OVERSIZED'} or oversized:
        return ModeRecommendation('SEA', load_mode, 'Heavy/vehicle/oversized cargo defaults to sea unless a verified air product exists.', True)
    if dangerous_goods or battery_or_fuel:
        return ModeRecommendation('SEA', load_mode, 'Special cargo requires carrier-specific review; sea is the conservative default.', True)
    if load_mode == 'FCL':
        return ModeRecommendation('SEA', load_mode, 'Full-container load is a sea product.')
    if load_mode == 'LCL':
        return ModeRecommendation('SEA', load_mode, 'Less-than-container consolidated cargo is a sea product.')
    if urgent and (weight_lb is None or weight_lb <= 500):
        return ModeRecommendation('AIR', load_mode, 'Urgent small/medium cargo is normally best suited to air.')
    if volume_cbm is not None and volume_cbm >= 2:
        return ModeRecommendation('SEA', load_mode, 'Higher-volume cargo generally favors sea economics.')
    return ModeRecommendation('AIR', load_mode, 'Small parcel, box or pallet cargo defaults to air when no contrary constraint exists.')


def mode_profile(mode: TransportMode) -> dict:
    if mode == 'AIR':
        return {'mode': 'AIR', 'flow': AIR_FLOW, 'documents': AIR_DOCUMENTS, 'pricing_bases': ['PER_LB', 'DIM_WEIGHT', 'MINIMUM', 'SPECIAL_ITEM'], 'hierarchy': ['ITEM', 'PACKAGE', 'PALLET', 'AIR_CONSOLIDATION', 'HAWB', 'MAWB', 'FLIGHT']}
    if mode == 'SEA':
        return {'mode': 'SEA', 'flow': SEA_FLOW, 'documents': SEA_DOCUMENTS, 'pricing_bases': ['PER_LB', 'PER_CUFT', 'PER_CBM', 'LCL_MINIMUM', 'FCL_FLAT', 'SPECIAL_ITEM'], 'hierarchy': ['ITEM', 'PACKAGE', 'PALLET', 'LCL_OR_CONTAINER', 'HBL', 'MBL', 'VESSEL']}
    return {'mode': 'MULTIMODAL', 'flow': ['INTAKE', 'LEG_1', 'TRANSFER', 'LEG_2', 'CUSTOMS', 'LAST_MILE', 'POD'], 'documents': ['LEG_SPECIFIC_DOCUMENTS'], 'pricing_bases': ['COMBINED_LEG_COST'], 'hierarchy': ['SHIPMENT', 'LEG_1', 'TRANSFER', 'LEG_2']}
