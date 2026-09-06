from us_national_shipping_network import NationalIntake, recommend_hub, recommend_mode, zone_for


def test_texas_routes_to_houston():
    p = NationalIntake(origin_state="TX", destination_country="CU", cargo_unit="PALLET", description="food pallet", weight_lb=900)
    assert zone_for("TX") == "TEXAS_GULF"
    assert recommend_hub(p) == "HOUSTON"
    assert recommend_mode(p) == "SEA"


def test_florida_routes_to_miami():
    p = NationalIntake(origin_state="FL", destination_country="DO", cargo_unit="BOX", description="documents", weight_lb=20, urgent=True)
    assert zone_for("FL") == "SOUTH_FLORIDA"
    assert recommend_hub(p) == "MIAMI"
    assert recommend_mode(p) == "AIR"


def test_vehicle_and_motorcycle_default_to_sea():
    car = NationalIntake(origin_state="OH", destination_country="CU", cargo_unit="VEHICLE", description="sedan")
    moto = NationalIntake(origin_state="CA", destination_country="CO", cargo_unit="MOTORCYCLE", description="motorcycle")
    assert recommend_mode(car) == "SEA"
    assert recommend_mode(moto) == "SEA"


def test_regulated_cargo_does_not_force_air():
    p = NationalIntake(origin_state="NY", destination_country="CU", cargo_unit="BOX", description="regulated goods", weight_lb=40, urgent=True, dangerous_or_regulated=True)
    assert recommend_mode(p) == "SEA"
