from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def text(path): return (ROOT/path).read_text()

def test_english_home_de_cuba_and_trade_desk_visible():
    app=text('src/App.tsx')
    public=app[app.index('function PublicSite()'):app.index('function PublicRfqForm()')]
    assert 'Cuba Desk' not in public
    assert 'tel:+12816628581' in public
    assert 'Call trade desk · +1 281-662-8581' in public
    assert 'not a completed deal' in public
    assert '12–14 weeks' in public

def test_generic_rfq_has_no_cuba_marketing_and_exposes_commercial_fields():
    page=text('public/start.html')
    assert 'Private business in Cuba?' not in page
    assert '<details>' not in page
    for field in ('target_budget','preferred_incoterm','target_delivery_date'):
        assert f'name="{field}"' in page
    assert "const presetNeed=params.get('product_need')" in page

def test_marketplace_search_has_real_route_and_explicit_no_match():
    routes=json.loads(text('vercel.json'))['routes']
    assert {'src':'/marketplace/search.html','dest':'/marketplace-search.html'} in routes
    assert {'src':'/marketplace/search','dest':'/marketplace-search.html'} in routes
    market=text('public/industrial-marketplace.html')
    assert 'action="/marketplace/search.html"' in market
    assert 'name="q"' in market
    result=text('public/marketplace-search.html')
    assert 'NO VERIFIED PUBLIC MATCH' in result
    assert 'Continue to sourcing request' in result
    assert 'tel:+12816628581' in result

def test_marketplace_home_uses_real_route():
    public=text('src/App.tsx')[text('src/App.tsx').index('function PublicSite()'):]
    assert 'href="/marketplace"' in public
    assert 'href="/industrial-marketplace"' not in public
