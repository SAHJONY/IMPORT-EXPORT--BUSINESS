from fastapi.testclient import TestClient

import cuba_private_sector_lead_api as api


client = TestClient(api.app)
BASE = '/cuba-private-sector/leads/private-economy'


def payload(**overrides):
    base = {
        'origin_country': 'CU',
        'destination_country': 'MX',
        'participant_type': 'MIPYME',
        'counterparty_type': 'FOREIGN_BUYER',
        'kyc_kyb_verified': True,
        'beneficial_ownership_verified': True,
        'sanctions_state': 'CLEAR',
        'us_nexus': False,
        'payment_currency': 'USD',
        'stable_family_remittance_pattern': False,
        'recurring_recipient': False,
        'transaction_anomaly': False,
        'fraud_indicator': False,
        'structuring_indicator': False,
        'product_control_review_complete': True,
    }
    base.update(overrides)
    return base


def test_overview_exposes_four_cuba_corridors_and_no_fake_live_screening():
    response = client.get(f'{BASE}/overview')
    assert response.status_code == 200
    body = response.json()
    assert [row['id'] for row in body['corridors']] == ['CU-CU', 'CU-WORLD', 'WORLD-CU', 'CU-US']
    assert body['live_sanctions_provider_claimed'] is False
    assert body['automatic_whitelisting'] is False


def test_cuba_to_cuba_classification():
    response = client.post(f'{BASE}/classify', json=payload(destination_country='CU'))
    assert response.status_code == 200
    assert response.json()['corridor'] == 'CU-CU'


def test_world_to_cuba_classification():
    response = client.post(f'{BASE}/classify', json=payload(origin_country='ES', destination_country='CU', participant_type='FOREIGN_SUPPLIER', counterparty_type='MIPYME'))
    assert response.status_code == 200
    assert response.json()['corridor'] == 'WORLD-CU'


def test_us_nexus_forces_special_corridor():
    response = client.post(f'{BASE}/classify', json=payload(destination_country='PA', us_nexus=True))
    assert response.status_code == 200
    assert response.json()['corridor'] == 'CU-US'


def test_blocked_sanctions_are_prohibited_even_for_stable_remittance():
    response = client.post(f'{BASE}/classify', json=payload(sanctions_state='BLOCKED', participant_type='PERSON', stable_family_remittance_pattern=True, recurring_recipient=True))
    body = response.json()
    assert body['decision'] == 'BLOCK'
    assert body['risk_band'] == 'PROHIBITED'
    assert body['remittance_pattern_effect'] == 'NONE'


def test_pending_or_error_sanctions_fail_closed():
    for state in ('PENDING', 'REVIEW', 'ERROR'):
        response = client.post(f'{BASE}/classify', json=payload(sanctions_state=state))
        assert response.json()['decision'] == 'HOLD'


def test_stable_remittance_only_reduces_anomaly_weight():
    response = client.post(f'{BASE}/classify', json=payload(participant_type='PERSON', stable_family_remittance_pattern=True, recurring_recipient=True, transaction_anomaly=True))
    body = response.json()
    assert body['decision'] != 'BLOCK'
    assert body['remittance_pattern_effect'] == 'LOWER_ANOMALY_WEIGHT_ONLY'


def test_missing_kyb_remains_hold_even_with_stable_pattern():
    response = client.post(f'{BASE}/classify', json=payload(kyc_kyb_verified=False, stable_family_remittance_pattern=True, recurring_recipient=True))
    assert response.json()['decision'] == 'HOLD'


def test_us_corridor_requires_product_control_review():
    response = client.post(f'{BASE}/classify', json=payload(destination_country='US', product_control_review_complete=False))
    body = response.json()
    assert body['corridor'] == 'CU-US'
    assert body['decision'] == 'HOLD'
    assert 'US_PRODUCT_CONTROL_REVIEW_REQUIRED' in body['reasons']
