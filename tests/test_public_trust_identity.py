from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_mobile_language_control_is_top_fixed_and_explicit():
    text = read("public/global-language.js")
    assert "top:max(10px,env(safe-area-inset-top))" in text
    assert "baseLocale(sourceLocale)==='es'?'Español':'English'" in text
    assert ">Original<" not in text


def test_about_names_company_leadership_and_avoids_unverified_legal_claims():
    text = read("public/about.html")
    assert "Juan Gonzalez" in text
    assert "Founder &amp; CEO" in text
    # Standing rule: render NOTHING for address/registration — no disclaimers.
    assert "We do not publish an unverified street address, registration number" not in text
    assert "/trust-center.html" in text


def test_customer_payments_requires_case_specific_instructions():
    text = read("public/customer-payments.html")
    assert "every payment must belong to a specific verified commercial case" in text
    assert "Do not assume that card, Zelle, cash, crypto, wire, ACH" in text
    assert "Verify by WhatsApp" in text
    assert "Refund, cancellation, fee responsibility and payment timing" in text


def test_cuba_funnel_surfaces_human_identity_and_trust_center():
    text = read("public/cuba-es.html")
    assert "PERSONA REAL · EMPRESA REAL" in text
    assert "Juan Gonzalez, Fundador y CEO" in text
    assert "Puede hablar con nosotros antes de compartir datos" in text
    assert "Centro de confianza" in text
