# Cuba market intelligence

The owner board at `/owner-cuba-prospects.html` reads authenticated CRM records from `cuba_market_research`. The September 10 research batch contains 241 buyer prospects, 12 global supplier candidates, 9 logistics providers, and 4 freight quotes. Of the buyers, 61 have public email or phone information and 190 have category-based supplier suggestions. These are prospects, not confirmed purchase orders or guaranteed profits.

Sources include CEMIS company profiles, the IPS 2025 business directory, official supplier and carrier websites, and owner correspondence for freight evidence. Each CRM record carries its source. Private correspondence and import snapshots are excluded from Git; production reads CRM data, not those local files. The preparation tools require those local source snapshots.

Existing external CRM prospects were enriched by exact-name matching (140); 101 new prospects were added. Existing outreach restrictions and commercial statuses were preserved. No outreach was sent. The optional qualification button creates an unqualified scout lead and copies public contact information.

Price comparisons require equivalent product, currency, unit, quantity, destination, incoterm, included costs and payment terms, current validity, evidence, and complete delivered costs. Research scores cannot advance a record into a commercial milestone. No complete A–Z logistics package or competitor price advantage has been established.

Validation: npm test (typecheck, build, repository guards); 13 Python tests; public directory search in browser; local fixture rendering of 241 buyers / 9 providers / 4 quotes; 390px mobile layout without horizontal overflow. Fixture checks do not establish production authentication or backend connectivity.
