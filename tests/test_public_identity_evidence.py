from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / 'public/about.html').read_text()
ES = (ROOT / 'public/about-es.html').read_text()


def test_about_renders_no_registration_commentary():
    # Standing rule: address/registration fields render NOTHING — no mentions,
    # placeholders, explanations, disclaimers, or pending labels.
    for text in (EN, ES):
        assert 'IRS CP 575' not in text
    assert 'January 24, 2024' not in EN
    assert 'issued el 24 de enero de 2024' not in EN
    assert '24 de enero de 2024' not in ES


def test_public_about_does_not_expose_sensitive_federal_identifier_or_full_private_address():
    combined = EN + ES
    # The real federal identifier and full mailing street from the primary-source notice must remain private.
    forbidden = ['99-0899501', '5216 BEAVERHILL DR', '5216 Beaverhill Dr']
    for value in forbidden:
        assert value not in combined


def test_about_does_not_overclaim_unverified_texas_state_record():
    # Standing rule: render NOTHING for address/registration — the former
    # "not yet matched" disclaimer is removed rather than published.
    assert 'Texas Secretary of State entity record has not yet been matched' not in EN
    assert 'Todavía no se ha vinculado' not in ES
    assert 'Houston, Texas' in EN
    assert 'Houston, Texas' in ES
