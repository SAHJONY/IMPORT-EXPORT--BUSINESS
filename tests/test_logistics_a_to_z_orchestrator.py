from logistics_a_to_z_orchestrator import ShipmentControl, can_transition, lifecycle_blueprint


def test_firm_quote_requires_margin_capacity_and_compliance():
    c = ShipmentControl(stage='QUOTE_PRELIMINARY', pricing_floor_passed=True, capacity_confirmed=True, compliance_cleared=False)
    result = can_transition('QUOTE_PRELIMINARY', 'QUOTE_FIRM', c)
    assert result['allowed'] is False
    assert 'compliance_cleared' in result['missing']


def test_delivery_requires_final_address_pod_and_recipient_verification():
    c = ShipmentControl(stage='OUT_FOR_DELIVERY', final_address_present=True, pod_recorded=True, recipient_verified=False)
    result = can_transition('OUT_FOR_DELIVERY', 'DELIVERED', c)
    assert result['allowed'] is False
    assert result['missing'] == ['recipient_verified']


def test_no_stage_skipping():
    c = ShipmentControl(stage='INTAKE', customer_verified=True)
    result = can_transition('INTAKE', 'QUOTE_PRELIMINARY', c)
    assert result['allowed'] is False
    assert result['reason'] == 'STAGE_SKIP_NOT_ALLOWED'


def test_exception_path_is_available_but_blocks_normal_flow_until_resolved():
    c = ShipmentControl(stage='OUT_FOR_DELIVERY', exception_open=True)
    assert can_transition('OUT_FOR_DELIVERY', 'DELIVERED_WITH_EXCEPTION', c)['allowed'] is True
    blocked = can_transition('DELIVERED_WITH_EXCEPTION', 'DELIVERED', c)
    assert blocked['allowed'] is False


def test_close_requires_reconciliation_pod_and_no_open_exception():
    c = ShipmentControl(stage='RECONCILED', financial_reconciled=True, pod_recorded=True, exception_open=False)
    result = can_transition('RECONCILED', 'CLOSED', c)
    assert result['allowed'] is True


def test_blueprint_contains_end_to_end_tracks():
    bp = lifecycle_blueprint()
    assert 'TRACKING_AND_CHAIN_OF_CUSTODY' in bp['required_operating_tracks']
    assert bp['provider_chain'][-1] == 'RECIPIENT_HOME_OR_BUSINESS'
