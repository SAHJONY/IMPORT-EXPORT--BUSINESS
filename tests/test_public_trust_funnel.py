from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUBA = (ROOT / "public" / "cuba-es.html").read_text()
START = (ROOT / "public" / "start.html").read_text()
FIND = (ROOT / "public" / "find.html").read_text()
OWNER = (ROOT / "public" / "owner-login.html").read_text()
APP = (ROOT / "src" / "App.tsx").read_text()


def test_cuba_funnel_is_whatsapp_first_and_explains_next_step():
    assert "wa.me/12816628581" in CUBA
    assert "atendemos en español" in CUBA
    assert "24–48 horas hábiles" in CUBA
    assert "Referencia:" in CUBA


def test_generic_start_hands_cuba_to_spanish_desk_without_duplicate_country():
    assert "/cuba-private-sector?lang=es" in START
    assert "['CU','CUB','CUBA']" in START
    assert 'name="country_code"' not in START
    assert "24–48 business hours" in START


def test_spanish_find_cards_are_native_and_owner_copy_is_corporate():
    assert "const esCopy=" in FIND
    assert "Hablar con una persona" in FIND
    assert "SECURE COMMAND ENTRANCE" not in OWNER
    assert "Full control. One owner." not in OWNER
    assert "OWNER SIGN IN" in OWNER


def test_public_homepage_leads_with_company_service_and_whatsapp():
    assert "SAHJONY LLC helps businesses find qualified suppliers" in APP
    assert "Talk to us on WhatsApp" in APP
    assert "HELD UNTIL VERIFIED" in APP
    assert "AI recommends · Owner governs · Evidence releases" not in APP
