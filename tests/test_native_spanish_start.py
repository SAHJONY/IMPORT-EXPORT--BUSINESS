from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPANISH = (ROOT / "public/start-es.html").read_text(encoding="utf-8")
LANGUAGE = (ROOT / "public/global-language.js").read_text(encoding="utf-8")


def test_start_spanish_routes_to_native_page():
    assert "currentPath==='/start'&&baseLocale(target)==='es'" in LANGUAGE
    assert "location.assign('/es/start')" in LANGUAGE


def test_native_spanish_start_has_current_conversion_contract():
    assert "Nuestro objetivo es responder en 24–48 horas hábiles" in SPANISH
    assert "Referencia:" in SPANISH
    assert "Abrir Mesa Cuba" in SPANISH
    assert "['CU','CUB','CUBA']" in SPANISH
    assert 'name="country_code"' not in SPANISH


def test_native_spanish_start_is_fully_spanish_at_source():
    assert '<html lang="es">' in SPANISH
    assert "Nombre del contacto" in SPANISH
    assert "Contacto name" not in SPANISH
    assert 'content="Diga a SAHJONY LLC qué necesita su empresa.' in SPANISH
    assert 'href="https://www.sahjony.com/es/start"' in SPANISH
