# Business execution desk

The private `/owner-business-ready.html` workspace supports a specific trade decision: identify a buyer and supplier, record current evidence and terms, enter complete USD order costs, evaluate projected contribution and funding needs, and save a draft snapshot into the CRM. Links connect it to supplier qualification, payments, deals, and shipment operations.

Unknown expenses remain unknown. Explicit zero costs require an explanation or evidence reference before a worksheet is ready for owner review. Missing demand, expired supplier quotes, incomplete costs, missing terms, overdue actions, and margins below the entered target remain visible blockers. Evidence references are owner-entered, not automatically verified. Review readiness grants no authority to contract, send messages, release funds, or ship goods.

Saved worksheets are immutable draft snapshots in the existing generic CRM record store (`deal_worksheets`). A save is confirmed only after a read-back. Loading recalculates validity and action deadlines. Contribution excludes unentered overhead and income taxes; the conservative funding gap assumes all costs precede final customer collection. These are projections, never collected profit.

The existing pricing preview now identifies omitted costs and rejects non-finite inputs. Economics ranking no longer labels unrecognized payment terms low risk or converts null amounts into zero estimates.

Production baseline on September 11, 2026: 10 of 28 platform gates passed (36/100), release HOLD. Outstanding gates: owner MFA, AI provider verification, logistics, document storage, translation, country governance, supplier sourcing, managed-trade gateway, intermediary controls, operating controls, Cuba eligibility/desk, collaboration isolation, accounting, beneficiary review, backup policy, monitoring, and first live trade certification. The execution desk shows current platform and CRM readiness. Do not change verification flags to claim completion without evidence.

No counterparties were contacted, payments issued, shipments booked, or research prospects promoted to confirmed demand in this release. An authenticated production session and a completed real transaction remain necessary to certify live business execution.

Validation: 264 tests passed across the Python suite, followed by two additional passing access/persistence tests (266 total); npm test passed; browser verified complete and incomplete calculations, save/read-back with isolated backend data, and 390px mobile layout without horizontal overflow. No production credentials were used for the fixture.
