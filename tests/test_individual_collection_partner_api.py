from individual_collection_partner_api import PartnerApplicationIn, CollectionIn


def test_partner_application_supports_home_dropoff_and_pickup():
    p = PartnerApplicationIn(
        full_name="Test Partner", phone="+17135550101", street_address="123 Main St",
        city="Houston", state="TX", postal_code="77084", accepts_terms=True,
        home_dropoff_enabled=True, customer_pickup_enabled=True,
        has_verified_scale=True, has_secure_storage=True,
    )
    assert p.home_dropoff_enabled is True
    assert p.customer_pickup_enabled is True
    assert p.max_daily_weight_lb == 250


def test_collection_supports_general_household_cargo():
    c = CollectionIn(
        partner_id="hcp_test1", customer_name="Customer", description="Household boxes",
        pieces=4, measured_weight_lb=82.5, destination_country="CU", cargo_category="GENERAL",
    )
    assert c.measured_weight_lb == 82.5
    assert c.pieces == 4


def test_collection_supports_single_appliance_category():
    c = CollectionIn(
        partner_id="hcp_test2", customer_name="Customer", description="Refrigerator",
        pieces=1, measured_weight_lb=190, destination_country="CU", cargo_category="APPLIANCE",
    )
    assert c.cargo_category == "APPLIANCE"
