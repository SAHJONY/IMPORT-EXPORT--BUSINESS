from pathlib import Path


def read(path): return Path(path).read_text()


def test_find_never_silently_redirects_unmatched_search():
    text=read('public/find.html')
    assert 'action="/start"' in text
    assert 'name="source" value="find_no_match"' in text
    assert "findForm.addEventListener('submit'" not in text
    assert 'No verified public match was selected.' in read('public/start.html')


def test_english_home_nav_has_no_cuba_primary_link_and_has_supplier_entry():
    text=read('src/App.tsx')
    section=text[text.index('function PublicSite()'):text.index('function PublicRfqForm()')]
    header=section[section.index('<header'):section.index('</header>')]
    assert 'Cuba Desk' not in header
    assert 'href="/suppliers"' in header
    assert 'Call trade desk' in header


def test_home_rfq_exposes_commercial_fields_and_guarded_upload():
    text=read('src/App.tsx')
    rfq=text[text.index('function PublicRfqForm()'):text.index('function StatePage')]
    for needle in ['TARGET BUDGET','INCOTERM','REQUIRED BY','OPTIONAL SPEC / DRAWING','/crm/intake-attachments/health']:
        assert needle in rfq


def test_conversion_instrumentation_and_owner_dashboard_are_routed():
    assert Path('public/conversion-analytics.js').exists()
    assert Path('public/owner-conversion-dashboard.html').exists()
    assert '/owner/conversion' in read('vercel.json')
    assert 'conversion-analytics.js' in read('public/global-language.js')
