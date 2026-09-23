"""Regression tests for the 10/10 fix: Spanish funnel routes + Trust Center binding.

Covers:
- every required public/es/*.html page exists, is marked data-source-locale="es",
  carries hreflang alternates, and contains no leftover English source phrases
- /es/start keeps the real RFQ form (/crm/intake, reference number, 24-48h promise)
- global-language.js routes /partners and /marketplace-search correctly and only
  ever targets existing /es/* pages (no dead /es/find, no silent English fallback)
- Trust Center pipeline counters fall back to an embedded snapshot that matches
  canonical-deals.json, and company identity renders name/location/contact only
- English source pages declare lang="en"
"""
import json
import re
from pathlib import Path

PUB = Path('public')
ES_PAGES = [
    'start', 'partners', 'about', 'trust-center', 'suppliers',
    'supplier-commercial-terms', 'supplier-cuba-terms',
    'customer-payments', 'marketplace-search',
]


def read_es(slug):
    return (PUB / 'es' / f'{slug}.html').read_text(encoding='utf-8')


def test_all_spanish_pages_exist():
    for slug in ES_PAGES:
        p = PUB / 'es' / f'{slug}.html'
        assert p.exists(), f'missing Spanish page: {p}'


def test_spanish_pages_marked_es_with_hreflang():
    for slug in ES_PAGES:
        text = read_es(slug)
        assert 'data-source-locale="es"' in text, slug
        assert '<html lang="es"' in text, slug
        assert f'hreflang="es" href="https://www.sahjony.com/es/{slug}"' in text, slug
        # english alternate may be /slug or /slug.html depending on the page
        assert re.search(r'hreflang="en" href="https://www\.sahjony\.com/' + re.escape(slug) + r'(\.html)?"', text), slug


def test_spanish_start_keeps_real_rfq_form():
    text = read_es('start')
    assert '/crm/intake' in text
    assert 'id="s"' in text
    assert 'Referencia' in text
    assert '24' in text and '48' in text and 'hábiles' in text
    assert 'Enviar solicitud' in text


def test_spanish_pages_have_no_english_fallback_copy():
    english_markers = [
        'Request a sourcing quote', 'Submit request', 'Please review and retry',
        'Trust Center', 'Supplier Center', 'Partner Center',
        'Marketplace Search', 'Customer Payments', 'Before you pay',
        'Evaluate the Cuba channel before you quote',
        'No blank check. Commercial economics must be written down',
    ]
    for slug in ES_PAGES:
        text = read_es(slug)
        for marker in english_markers:
            assert marker not in text, f'{slug}: leftover English "{marker}"'


def test_spanish_cross_links_stay_in_spanish():
    assert '/es/partners' in read_es('start')
    # partner center's public share URL is the Spanish canonical (parity with EN page)
    assert 'https://www.sahjony.com/es/partners' in read_es('partners')
    assert 'href="/start"' not in read_es('partners')
    assert '/es/trust-center' in read_es('about')
    assert '/es/start' in read_es('trust-center')
    assert '/es/supplier-commercial-terms' in read_es('suppliers')
    assert '/es/supplier-cuba-terms' in read_es('suppliers')
    assert '/es/suppliers' in read_es('supplier-commercial-terms')


def test_global_language_routes_partners_and_marketplace():
    js = (PUB / 'global-language.js').read_text(encoding='utf-8')
    # /partners must land on the real Spanish page, never the bare /es fallback
    assert "'/partners':'/es/partners'" in js.replace(' ', '')
    assert "'/partners.html':'/es/partners'" in js.replace(' ', '')
    # direct Spanish routing for /partners inside applyLanguage, both directions
    assert "location.assign('/es/partners')" in js
    assert "currentPath==='/es/partners'" in js
    # dead /find routes must redirect to the real marketplace search page
    assert "location.assign('/es/find')" not in js
    assert "location.assign('/es/marketplace-search')" in js
    assert "location.assign('/marketplace-search')" in js


def test_global_language_es_targets_all_exist():
    js = (PUB / 'global-language.js').read_text(encoding='utf-8')
    targets = set(re.findall(r"location\.assign\('(/es(?:/[\w\-]+)?)'\)", js))
    for target in targets:
        rel = 'es.html' if target == '/es' else 'es/' + target[4:] + '.html'
        assert (PUB / rel).exists(), f'global-language.js targets missing page {target}'


def test_trust_center_counter_fallback_matches_canonical_deals():
    deals_doc = json.loads((PUB / 'canonical-deals.json').read_text(encoding='utf-8'))
    deals = deals_doc['deals']
    expected = {
        'dealCount': len(deals),
        'firmCount': sum(1 for d in deals if d.get('stage') == 'FIRM_QUOTE'),
        'evidenceCount': sum(1 for d in deals if isinstance(d.get('evidence'), list) and d['evidence']),
        'updated': (deals_doc.get('updated_at') or '')[:10],
    }
    for slug, page in (('en', 'trust-center.html'), ('es', 'es/trust-center.html')):
        text = (PUB / page).read_text(encoding='utf-8')
        m = re.search(r'<script type="application/json" id="sj-deals-fallback">(\{.*?\})</script>', text)
        assert m, f'{slug} trust center: missing embedded counter fallback'
        embedded = json.loads(m.group(1))
        for key, value in expected.items():
            assert embedded[key] == value, f'{slug} trust center: fallback {key}={embedded[key]} != canonical {value}'


def test_trust_center_identity_has_no_address_or_registration():
    for page in ('trust-center.html', 'es/trust-center.html'):
        text = (PUB / page).read_text(encoding='utf-8')
        # embedded safe fallback object (rendered by JS into the identity block)
        assert "legalName: 'SAHJONY LLC'" in text, page
        assert "city: 'Houston'" in text, page
        assert "state: 'Texas'" in text, page
        assert "country: 'USA'" in text, page
        assert "phoneVoice: '+1 281-662-8581'" in text, page
        assert "emailSales: 'ventas@sahjony.com'" in text, page
        assert 'window.SAHJONY_COMPANY' in text, page
        # shelved per Juan ("no pongas nada"): fields exist but render nothing
        assert "streetAddress: ''" in text, page
        assert "registrationNumber: ''" in text, page
        for forbidden in ('123 Main St', 'Calle Falsa', 'Reg. No', 'Nº de registro',
                           'registration number', 'número de registro'):
            assert forbidden.lower() not in text.lower(), f'{page}: forbidden placeholder {forbidden}'


def test_english_pages_declare_lang_en():
    for page in ('about.html', 'trust-center.html', 'suppliers.html',
                 'supplier-commercial-terms.html', 'supplier-cuba-terms.html',
                 'customer-payments.html', 'marketplace-search.html', 'partners.html'):
        text = (PUB / page).read_text(encoding='utf-8')
        assert '<html lang="en"' in text, f'{page}: must declare lang="en"'
