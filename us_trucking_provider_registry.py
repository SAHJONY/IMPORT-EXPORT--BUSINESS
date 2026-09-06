from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

PriceMode = Literal['LIVE_QUOTE_REQUIRED','PUBLIC_ACCESSORIAL_ONLY']
ServiceType = Literal['LTL','VOLUME_LTL','FTL','EXPEDITED','RESIDENTIAL','FINAL_MILE','CROSS_BORDER','CONSOLIDATION_DISTRIBUTION']


@dataclass(frozen=True)
class TruckingProvider:
    provider_id: str
    name: str
    coverage: str
    services: tuple[ServiceType, ...]
    pricing_mode: PriceMode
    quote_url: str
    source_url: str
    source_checked_date: str
    public_price_notes: str | None = None
    residential_delivery: bool = False
    liftgate_available: bool = False
    appointment_delivery: bool = False
    tracking: bool = True
    volume_pricing: bool = False
    hub_feeder_eligible: bool = True


PROVIDERS = (
    TruckingProvider(
        provider_id='xpo_ltl',
        name='XPO',
        coverage='US domestic LTL; >99% of US ZIP codes per carrier site',
        services=('LTL','EXPEDITED','RESIDENTIAL','FINAL_MILE'),
        pricing_mode='PUBLIC_ACCESSORIAL_ONLY',
        quote_url='https://ltl.xpo.com/webapp/rating_p_app/',
        source_url='https://www.xpo.com/help-center/united-states/xpo-us-ltl-service/',
        source_checked_date='2026-09-06',
        public_price_notes='Base LTL requires live quote. Guaranteed: +25% of linehaul, $63 minimum. Guaranteed by Noon: +35% of linehaul, $158 minimum.',
        residential_delivery=True,
        liftgate_available=True,
        appointment_delivery=True,
        tracking=True,
        volume_pricing=True,
    ),
    TruckingProvider(
        provider_id='estes',
        name='Estes Express Lines',
        coverage='US national LTL plus Canada/Mexico and offshore services',
        services=('LTL','VOLUME_LTL','FTL','EXPEDITED','FINAL_MILE','CROSS_BORDER'),
        pricing_mode='LIVE_QUOTE_REQUIRED',
        quote_url='https://www.estes-express.com/myestes/rate-quote-estimate/quick-quote',
        source_url='https://www.estes-express.com/services/',
        source_checked_date='2026-09-06',
        public_price_notes='Rates are shipment-specific by origin/destination, class, weight, dimensions and accessorials.',
        residential_delivery=True,
        liftgate_available=True,
        appointment_delivery=True,
        tracking=True,
        volume_pricing=True,
    ),
    TruckingProvider(
        provider_id='old_dominion',
        name='Old Dominion Freight Line',
        coverage='United States and Canada LTL network',
        services=('LTL','EXPEDITED'),
        pricing_mode='LIVE_QUOTE_REQUIRED',
        quote_url='https://www.odfl.com/us/en/tools/freight-shipping-rate-estimate/ltl-rate-estimate.html',
        source_url='https://www.odfl.com/us/en/resources/freight-knowledge/odfl-blog/ltl-pricing-guide.html',
        source_checked_date='2026-09-06',
        public_price_notes='Shipment-specific rating; fuel surcharge changes weekly and accessorials such as liftgate may add fees.',
        residential_delivery=True,
        liftgate_available=True,
        appointment_delivery=True,
        tracking=True,
        volume_pricing=True,
    ),
    TruckingProvider(
        provider_id='fedex_freight',
        name='FedEx Freight',
        coverage='US, Canada and Mexico LTL',
        services=('LTL','VOLUME_LTL'),
        pricing_mode='LIVE_QUOTE_REQUIRED',
        quote_url='https://ratefinder.van.fedex.com/en-us/',
        source_url='https://www.fedex.com/en-us/shipping/freight/ltl.html',
        source_checked_date='2026-09-06',
        public_price_notes='Instant or requested quote based on origin, destination, commodity/class, weight, pieces, dimensions and special services.',
        residential_delivery=True,
        liftgate_available=True,
        appointment_delivery=True,
        tracking=True,
        volume_pricing=True,
    ),
    TruckingProvider(
        provider_id='tforce_freight',
        name='TForce Freight',
        coverage='Regional, interregional and long-haul US network with offshore/international options',
        services=('LTL','VOLUME_LTL','EXPEDITED','CROSS_BORDER','CONSOLIDATION_DISTRIBUTION'),
        pricing_mode='LIVE_QUOTE_REQUIRED',
        quote_url='https://www.tforcefreight.com/ltl/apps/TForceFreightLTL',
        source_url='https://www.tforcefreight.com/ltl/apps/ContactUs',
        source_checked_date='2026-09-06',
        public_price_notes='Live LTL quote required. Carrier advertises spot volume pricing for shipments over 8,000 lb or occupying more than 8 ft of trailer.',
        residential_delivery=True,
        liftgate_available=True,
        appointment_delivery=True,
        tracking=True,
        volume_pricing=True,
    ),
)


def provider_snapshot() -> list[dict]:
    return [asdict(p) for p in PROVIDERS]


def eligible_for_feeder(*, residential_needed: bool = False, liftgate_needed: bool = False, appointment_needed: bool = False) -> list[dict]:
    rows = []
    for p in PROVIDERS:
        if not p.hub_feeder_eligible:
            continue
        if residential_needed and not p.residential_delivery:
            continue
        if liftgate_needed and not p.liftgate_available:
            continue
        if appointment_needed and not p.appointment_delivery:
            continue
        rows.append(asdict(p))
    return rows


def pricing_input_requirements() -> dict:
    return {
        'origin_zip': True,
        'destination_zip': True,
        'weight_lb': True,
        'handling_units': True,
        'dimensions': True,
        'freight_class_or_nmfc': True,
        'residential': False,
        'liftgate': False,
        'appointment': False,
        'inside_service': False,
        'hazmat': False,
        'pickup_date': True,
        'rule': 'Do not persist a static nationwide LTL price where the carrier requires live shipment-specific rating.',
    }
