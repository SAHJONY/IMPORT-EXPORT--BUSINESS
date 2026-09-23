from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


def text(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8")


def test_find_has_native_submit_without_js_interception():
    page = text("find.html")
    assert 'action="/start"' in page
    assert 'name="product_need"' in page
    assert 'type="submit"' in page
    assert "findForm.addEventListener('submit'" not in page


def test_marketplace_no_match_is_explicit_not_silent_redirect():
    page = text("industrial-marketplace.html")
    assert "NO VERIFIED PUBLIC MATCH" in page
    assert "Continue to sourcing request" in page
    assert "No inventory or price is being implied" in page


def test_native_spanish_trust_pages_exist():
    about = text("about-es.html")
    trust = text("trust-center-es.html")
    find = text("find-es.html")
    assert 'lang="es"' in about and "Juan Gonzalez" in about
    assert 'lang="es"' in trust and "Centro de Confianza" in trust
    assert "no publica testimonios" in trust
    assert 'lang="es"' in find and 'action="/es/start"' in find


def test_native_spanish_routes_and_language_bridge():
    routes = (ROOT / "vercel.json").read_text(encoding="utf-8")
    runtime = text("global-language.js")
    for route in ("/es/about", "/es/trust-center", "/es/find"):
        assert f'"src": "{route}"' in routes
    assert "location.assign('/es/about')" in runtime
    assert "location.assign('/es/trust-center')" in runtime
    # /find was consolidated into marketplace-search: Spanish users land on the
    # real search page, never on the dead /es/find target
    assert "location.assign('/es/marketplace-search')" in runtime
    assert "location.assign('/es/find')" not in runtime
