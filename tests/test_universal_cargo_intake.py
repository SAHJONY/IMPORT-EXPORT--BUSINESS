from cuba_agency_network_api import UniversalCargoIntake, classify_cargo


def test_motorcycle_classification():
    out = classify_cargo("Moto electrica usada")
    assert out["cargo_form"] == "MOTORCYCLE"
    assert "TITLE_OWNERSHIP_REVIEW" in out["review_flags"]
    assert "DG_BATTERY_FUEL_REVIEW" in out["review_flags"]


def test_refrigerator_single_item_classification():
    out = classify_cargo("Nevera nueva")
    assert out["cargo_form"] == "SINGLE_ITEM"
    assert "APPLIANCE_TECHNICAL_REVIEW" in out["review_flags"]
    assert "REFRIGERANT_REVIEW" in out["review_flags"]


def test_health_product_classification():
    out = classify_cargo("20 cajas de condones")
    assert out["cargo_form"] == "MULTIPLE_BOXES"
    assert "HEALTH_REGULATORY_REVIEW" in out["review_flags"]


def test_consolidated_cargo_classification():
    out = classify_cargo("Carga consolidada de productos de hogar")
    assert out["cargo_form"] == "LCL_CONSOLIDATED"


def test_explicit_pallet_form_is_preserved():
    out = classify_cargo("Productos varios", "PALLET")
    assert out["cargo_form"] == "PALLET"


def test_global_country_codes_are_not_cuba_specific():
    intake = UniversalCargoIntake(
        description="cajas de repuestos",
        origin_country="DE",
        destination_country="BR",
        quantity=4,
    )
    assert intake.origin_country == "DE"
    assert intake.destination_country == "BR"
