from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / 'public/about.html').read_text()
ES = (ROOT / 'public/about-es.html').read_text()


def test_about_surfaces_safe_primary_source_identity_evidence():
    assert 'IRS CP 575' in EN
    assert 'January 24, 2024' in EN
    assert 'issued el 24 de enero de 2024' not in EN
    assert 'IRS CP 575' in ES
    assert '24 de enero de 2024' in ES


def test_public_about_does_not_expose_sensitive_federal_identifier_or_full_private_address():
    combined = EN + ES
    # The real federal identifier and full mailing street from the primary-source notice must remain private.
    forbidden = ['99-0899501', '5216 BEAVERHILL DR', '5216 Beaverhill Dr']
    for value in forbidden:
        assert value not in combined


def test_about_does_not_overclaim_unverified_texas_state_record():
    assert 'Texas Secretary of State entity record has not yet been matched' in EN
    assert 'Todavía no se ha vinculado' in ES
    assert 'Houston, Texas' in EN
    assert 'Houston, Texas' in ES
