from decimal import Decimal

import pytest
from fastapi import HTTPException

from agency_to_last_mile_network import ProviderCandidate, choose_provider, eligible


def provider(**overrides):
    data = dict(
        provider_id='p1', provider_name='Provider 1', leg_type='LAST_MILE',
        city='Havana', region='La Habana', status='ACTIVE',
        supported_modes=('SEA','AIR'), supported_cargo=('BOX','PALLET','LCL','FCL'),
        base_cost=Decimal('10'), variable_cost=Decimal('5'), estimated_days=2,
        capacity_score=80, service_score=90, on_time_score=85, claims_score=80,
        tracking=True, qr_handoff=True, pod=True, door_delivery=True,
        compliance_cleared=True,
    )
    data.update(overrides)
    return ProviderCandidate(**data)


def test_last_mile_requires_door_delivery_tracking_and_pod():
    assert eligible(provider(), mode='SEA', cargo_type='BOX') is True
    assert eligible(provider(pod=False), mode='SEA', cargo_type='BOX') is False
    assert eligible(provider(door_delivery=False), mode='SEA', cargo_type='BOX') is False
    assert eligible(provider(tracking=False), mode='SEA', cargo_type='BOX') is False


def test_provider_must_be_verified_or_active_and_compliance_cleared():
    assert eligible(provider(status='CANDIDATE'), mode='SEA', cargo_type='BOX') is False
    assert eligible(provider(compliance_cleared=False), mode='SEA', cargo_type='BOX') is False


def test_choose_provider_balances_service_before_cost():
    stronger = provider(provider_id='strong', base_cost=Decimal('15'), service_score=95, on_time_score=95, capacity_score=95)
    cheaper = provider(provider_id='cheap', base_cost=Decimal('1'), service_score=40, on_time_score=40, capacity_score=40)
    selected = choose_provider([cheaper, stronger], leg_type='LAST_MILE', mode='SEA', cargo_type='BOX')
    assert selected.provider_id == 'strong'


def test_no_eligible_provider_fails_closed():
    with pytest.raises(HTTPException):
        choose_provider([provider(pod=False)], leg_type='LAST_MILE', mode='SEA', cargo_type='BOX')
