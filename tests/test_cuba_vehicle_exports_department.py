from cuba_vehicle_exports_api import ShipmentPreflightIn, VehicleIn, _shipment_gate_state


def _vehicle(**overrides):
    data = {
        "vin": "1HGCM82633A004352",
        "year": 2022,
        "make": "Honda",
        "model": "Accord",
        "condition": "USED",
        "powertrain": "GASOLINE",
        "ownership_document_verified": True,
        "origin_city_state": "Houston, TX",
        "aes_itn": "X20260913000001",
        "eccn_or_ear99": "EAR99",
        "bis_authorization_basis": "SCP",
        "ofac_authorization_basis": "CACR_GENERAL_AUTHORIZATION",
        "restricted_party_screening": "PASS",
        "dangerous_goods_review": "NOT_APPLICABLE",
        "carrier_acceptance": "PASS",
    }
    data.update(overrides)
    return VehicleIn(**data)


def _shipment(vehicle):
    return ShipmentPreflightIn(
        vehicles=[vehicle],
        importer_name="Qualified Cuban Importer",
        importer_type="AUTHORIZED_CUBAN_IMPORTER",
        importer_eligibility="PASS",
        end_user_name="Private customer",
        end_use="Personal transportation",
        end_user_end_use_eligibility="PASS",
        cuba_customs_readiness="PASS",
        commercial_documents="PASS",
    )


def test_used_vehicle_remains_pending_until_cbp_gate_reviewed():
    gates = _shipment_gate_state(_shipment(_vehicle()))
    assert gates["used_vehicle_cbp_export_requirements"] == "PENDING"


def test_ev_requires_dangerous_goods_review():
    gates = _shipment_gate_state(_shipment(_vehicle(powertrain="EV", dangerous_goods_review="PENDING")))
    assert gates["dangerous_goods_review"] == "PENDING"


def test_undetermined_bis_basis_fails_closed_to_pending():
    gates = _shipment_gate_state(_shipment(_vehicle(bis_authorization_basis="UNDETERMINED")))
    assert gates["bis_authorization_basis"] == "PENDING"


def test_new_non_battery_vehicle_can_mark_nonapplicable_transport_gates():
    gates = _shipment_gate_state(_shipment(_vehicle(condition="NEW")))
    assert gates["used_vehicle_cbp_export_requirements"] == "NOT_APPLICABLE"
    assert gates["dangerous_goods_review"] == "NOT_APPLICABLE"
