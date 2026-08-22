(()=>{
  const common={
    operating:[
      'SAHJONY operates as a managed-trade intermediary/orchestrator unless a transaction expressly assigns another commercial role.',
      'Every transaction must identify the real buyer, seller, origin, destination, product, payment path, logistics path, and responsible legal parties.',
      'Employees prepare, source, document, coordinate, and escalate. They do not bypass required compliance, treasury, or owner-release controls.',
      'A case remains HOLD whenever required evidence is missing, expired, inconsistent, or fails a mandatory control.'
    ],
    rules:[
      'No supplier, customer, product, corridor, beneficiary, or shipment is approved solely because the commercial terms are attractive.',
      'Restricted-party, sanctions, product, customs, banking, tax, document, and logistics controls remain independent and fail-closed.',
      'Importer of Record, Exporter of Record, customs broker, freight forwarder, carrier, payment provider, and principal/reseller roles are assigned transaction by transaction.',
      'No employee may self-approve a control that is designated owner/compliance/treasury-only.'
    ],
    legal:[
      'Applicable law depends on origin, destination, product, parties, end use, payment path, and the role SAHJONY performs in the transaction.',
      'Primary U.S. frameworks can include CBP customs law and entry requirements, the Harmonized Tariff Schedule, BIS Export Administration Regulations, OFAC sanctions programs, Census/AES filing rules, product-specific Partner Government Agency requirements, anti-bribery/recordkeeping rules, tax law, contract law, and privacy/data obligations.',
      'Country-specific import/export, licensing, tax, customs, currency, insurance, and data rules must also be verified for non-U.S. jurisdictions.',
      'This screen is an operating control summary, not a substitute for transaction-specific legal, customs, tax, banking, or licensing advice.'
    ],
    evidence:[
      'Current KYB/KYC and beneficial-owner evidence where applicable',
      'Restricted-party/sanctions screening result',
      'Product classification and origin evidence',
      'Commercial agreement / PO / invoice trail',
      'Verified payment beneficiary and settlement evidence',
      'Required customs, transport, insurance, permit, license, or authorization documents',
      'Owner/compliance approval evidence for all owner-only gates'
    ]
  };

  const screens={
    command:{title:'Command Center',operate:['Use this screen to see business-wide readiness, blockers, exceptions, and the release state of live trade workflows.','The Command Center does not itself authorize a transaction; it summarizes evidence produced by the underlying operating modules.'],rules:['Production readiness is not the same as transaction authorization.','Any critical blocker keeps the global release gate on HOLD.'],legal:['Executive oversight must preserve the legal responsibilities assigned to each transaction and must not override sanctions, customs, banking, licensing, or recordkeeping requirements.']},
    countries:{title:'Global Countries',operate:['Create a country profile before running live trade in that jurisdiction.','Verify country, product, banking, logistics, insurance, tax, contracts, privacy, and reconciliation controls before enabling corridors.'],rules:['New live countries begin BLOCKED.','READY is derived only when all required controls are READY or legitimately NOT_APPLICABLE.','Hypothetical jurisdictions cannot authorize live execution.'],legal:['Each country is governed by its own import/export, customs, sanctions, tax, currency, licensing, insurance, contract, privacy, and corporate rules in addition to any U.S. nexus that applies.']},
    'private-businesses':{title:'Cuba Private Business Desk',operate:['Register the Cuban private business and its owners/controllers.','Verify private-sector eligibility, independence, banking path, and restricted-party status before linking it to a trade case.','Eligible business status is only one gate; each product and transaction still needs its own authorization/compliance review.'],rules:['Private-business status is verified, not self-declared.','Government/state control, prohibited ownership, screening hits, or disallowed banking paths can make the business ineligible or require review.'],legal:['Real Cuba remains a restricted jurisdiction. Current U.S. controls include OFAC Cuban Assets Control Regulations and BIS EAR Part 746/available license exceptions where their exact conditions are met. Private-business eligibility does not waive those requirements.']},
    messages:{title:'Communications',operate:['Keep customer, supplier, broker, carrier, compliance, and internal communications tied to the correct case.','Use communications as evidence of instructions, approvals, exceptions, and agreed commercial changes.'],rules:['Do not communicate an approval that has not actually been granted in the controlling module.','Do not expose internal margin, treasury data, private documents, or restricted information outside the recipient’s authorized scope.'],legal:['Communications can create contractual, disclosure, privacy, sanctions, export-control, and record-retention consequences. Required notices and consent rules vary by channel and jurisdiction.']},
    documents:{title:'Documents',operate:['Store controlled trade documents against the correct customer, supplier, product, shipment, and transaction.','Use signed/private document flows for sensitive commercial, banking, customs, identity, and authorization records.'],rules:['No shipment release when required documents are missing, stale, unsigned, inconsistent, or unverified.','Legal hold and retention controls supersede ordinary deletion.'],legal:['Trade records may be subject to customs, export-control, sanctions, tax, accounting, contract, privacy, and litigation-retention requirements. Recordkeeping periods vary by document and jurisdiction.']},
    shipping:{title:'Shipping',operate:['Coordinate booking, carrier/forwarder milestones, documents, insurance, customs handoff, exceptions, delivery, and proof of receipt.','Tie every shipment to the approved product, parties, corridor, and Incoterm.'],rules:['No shipment may depart or be released while a required compliance/document/payment/logistics gate is unresolved.','Do not infer Importer or Exporter of Record from the freight booking.'],legal:['Transport is governed by customs law, carrier/forwarder terms, Incoterms where adopted by contract, cargo insurance, dangerous-goods rules where applicable, and destination/origin import-export requirements.']},
    compliance:{title:'Compliance',operate:['Screen parties, classify products, verify origin/end use, determine license/authorization requirements, and document release decisions.','Escalate ambiguous or high-risk cases instead of converting uncertainty into approval.'],rules:['A failed mandatory compliance control cannot be overridden by commercial urgency.','Screening must be current at the point the transaction is released.'],legal:['Relevant U.S. frameworks can include OFAC sanctions, BIS EAR, customs law, forced-labor restrictions, anti-boycott rules, FCPA/anti-bribery controls, Census/AES requirements, and product-specific agency rules. Other jurisdictions add their own requirements.']},
    operations:{title:'Commercial Operations',operate:['Convert an approved customer need into supplier sourcing, quote, engagement, purchase/sales documentation, execution milestones, and owner release.','Track commercial changes so pricing, scope, role, and compensation remain consistent with the signed engagement.'],rules:['Commercial approval cannot substitute for compliance, treasury, customs, or logistics approval.','SAHJONY compensation must follow the approved engagement and disclosed economics.'],legal:['Agency/brokerage, contract, sales, tax, customs, sanctions, anti-bribery, and consumer/business-protection rules may apply depending on the role and transaction.']},
    finance:{title:'Finance & Reconciliation',operate:['Record customer receivables, supplier payables, freight/duty/insurance costs, SAHJONY fees, FX, and final P&L.','Reconcile invoices, purchase orders, settlements, bank evidence, and ledger entries before closing a trade.'],rules:['Beneficiary changes require independent verification and maker-checker control.','Employees cannot create and independently approve the same sensitive treasury change.','No First Live Trade certification without complete reconciliation.'],legal:['Money movement can trigger banking, sanctions, AML/KYB, tax, accounting, FX, agency, money-transmission, and recordkeeping obligations depending on the structure. SAHJONY must not hold or transmit client funds unless the transaction structure and applicable law permit it.']},
    sharing:{title:'Governed Sharing',operate:['Share only the minimum approved document/data scope needed by the recipient.','Use expiry, revocation, and case-level access controls for external parties.'],rules:['Customer/supplier access must never expose unrelated tenant data, internal margins, treasury controls, or owner-only approvals.','Revoked or expired access must fail closed.'],legal:['Privacy, confidentiality, trade-secret, sanctions/export-control, contractual, and cross-border data-transfer requirements may apply to shared information.']},
    language:{title:'Language & Translation',operate:['Preserve the original source text and provide translated working copies for the permitted recipient.','Flag legal, customs, banking, and contractual translations for human review where required.'],rules:['Machine translation cannot silently replace the authoritative signed/source document.','Do not change legal meaning, quantities, classifications, names, banking instructions, or authorization terms during translation.'],legal:['Language requirements vary by customs authority, contract, product labeling rule, consumer law, and destination jurisdiction. The authoritative version must be identified for legally significant documents.']},
    'us-import':{title:'United States Import Desk',operate:['A customer/private business gives SAHJONY the product need; SAHJONY may source the supplier globally and manage the inbound U.S. transaction.','Assign the real U.S. Importer of Record and customs broker, verify product classification/origin/valuation/PGA requirements, calculate duties and landed cost, then coordinate freight, insurance, entry, delivery, and reconciliation.','Owner/compliance release occurs only after all applicable import gates pass.'],rules:['Destination is the United States; foreign supplier origin can vary by transaction.','Importer of Record responsibility must be explicit and cannot be inferred from SAHJONY acting as broker/intermediary.','HTS classification, customs value, country of origin/marking, admissibility, PGA requirements, duties/taxes, bond/entry authority, payment, documents, freight, insurance, compliance, and owner release must be resolved before release.'],legal:['U.S. imports are principally governed by CBP customs requirements and the Tariff Act/customs regulations, the Harmonized Tariff Schedule maintained by the U.S. International Trade Commission, country-of-origin/marking and valuation rules, and applicable Partner Government Agency requirements. Sanctions/blocked-party rules can also apply. The Importer of Record remains responsible for reasonable care and entry accuracy even when using a customs broker.']},
    'global-sourcing':{title:'Worldwide Supplier Sourcing',operate:['Search eligible suppliers in any permitted origin country for the customer’s product need.','Compare commercial terms and landed-cost economics, then evaluate the actual origin-to-destination corridor before selection.'],rules:['Price alone never makes a supplier selectable.','Supplier screening, origin export controls, destination import controls, product restrictions, payment, logistics, duty/tax, and any U.S.-nexus/reexport controls must be resolved.'],legal:['Both origin-country export law and destination-country import law apply. U.S. sanctions/export-control rules can also apply to U.S. persons, U.S.-origin items, items subject to the EAR, U.S. dollar/payment touchpoints, or other U.S. jurisdictional nexus depending on the facts.']},
    intermediary:{title:'SAHJONY Intermediary Desk',operate:['Define whom SAHJONY represents, the scope of services, and the approved compensation model.','Keep seller, buyer, Exporter of Record, Importer of Record, and SAHJONY commercial role explicit and verified.'],rules:['Broker/agent mode does not automatically transfer title to SAHJONY.','Dual-side representation requires disclosure.','Client funds cannot be controlled unless expressly authorized and legally/operationally supported.'],legal:['Agency, brokerage, contract, customs, tax, sanctions, anti-bribery, fiduciary/disclosure, licensing, and money-handling rules may differ by jurisdiction and by whether SAHJONY acts as agent or principal.']},
    'business-readiness':{title:'Business Operational Readiness',operate:['Verify real partners, agreements, KYB, product dossiers, payment/logistics controls, incident handling, and reconciliation capabilities.','Use the First Live Trade Certification as the final proof that the business can execute end to end.'],rules:['Configuration alone is not evidence of operational readiness.','A dry run or demo cannot set FIRST_LIVE_TRADE_CERTIFIED=true.'],legal:['Operational readiness does not waive transaction-specific licensing, customs, sanctions, banking, tax, insurance, contract, or product rules. Each live deal still requires its own evidence.']}
  };

  function keyForPath(path){
    const p=path.toLowerCase();
    if(p.includes('/us-import')||p.endsWith('/us-import.html')) return 'us-import';
    if(p.includes('/global-sourcing')) return 'global-sourcing';
    if(p.includes('/intermediary')) return 'intermediary';
    if(p.includes('/business-readiness')) return 'business-readiness';
    for(const key of ['private-businesses','countries','messages','documents','shipping','compliance','operations','finance','sharing','language']) if(p.includes('/'+key)) return key;
    return 'command';
  }

  function roleForPath(path){
    const p=path.toLowerCase();
    if(p.includes('/owner')) return 'OWNER';
    if(p.includes('/employee')) return 'EMPLOYEE';
    if(p.includes('/customer')) return 'CUSTOMER';
    const role=document.getElementById('role');
    return role&&role.value?String(role.value).toUpperCase():'WORKSPACE';
  }

  function list(items){return '<ul>'+items.map(x=>'<li>'+x+'</li>').join('')+'</ul>'}
  function style(){
    if(document.getElementById('sahjony-legal-style')) return;
    const s=document.createElement('style');s.id='sahjony-legal-style';s.textContent=`
      #sahjony-legal-framework{margin:18px 0;padding:20px;border:1px solid #2a4058;border-radius:16px;background:linear-gradient(180deg,rgba(16,35,57,.98),rgba(8,22,38,.98));color:#eef5ff}
      #sahjony-legal-framework *{box-sizing:border-box}#sahjony-legal-framework .lf-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px}
      #sahjony-legal-framework .lf-kicker{font-size:11px;letter-spacing:.16em;color:#8eabc8;text-transform:uppercase}#sahjony-legal-framework h2{margin:6px 0 0;font-size:23px}
      #sahjony-legal-framework .lf-role{font-size:11px;border:1px solid #38516b;border-radius:999px;padding:7px 10px;color:#c9dcf0;white-space:nowrap}
      #sahjony-legal-framework .lf-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}#sahjony-legal-framework .lf-card{border:1px solid #20364f;background:#0a192a;border-radius:12px;padding:14px}
      #sahjony-legal-framework .lf-card h3{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#9db9d4}#sahjony-legal-framework ul{margin:0;padding-left:18px;color:#c7d5e4;line-height:1.48}
      #sahjony-legal-framework li+li{margin-top:5px}#sahjony-legal-framework .lf-note{margin-top:12px;padding-top:12px;border-top:1px solid #20364f;color:#8fa5bc;font-size:12px;line-height:1.45}
      @media(max-width:760px){#sahjony-legal-framework .lf-grid{grid-template-columns:1fr}#sahjony-legal-framework .lf-head{flex-direction:column}}
    `;document.head.appendChild(s);
  }

  function render(){
    const key=keyForPath(location.pathname);const cfg=screens[key]||screens.command;const existing=document.getElementById('sahjony-legal-framework');if(existing) existing.remove();
    const host=document.querySelector('.main')||document.querySelector('.wrap')||document.body;if(!host) return;style();
    const role=roleForPath(location.pathname);const authority=role==='EMPLOYEE'?'Employees may prepare and coordinate this workflow but cannot bypass owner/compliance/treasury-only approvals.':role==='OWNER'?'Owner approval is a governance gate, not a waiver of applicable law or third-party authority.':'Access is limited to the data and actions authorized for this role.';
    const node=document.createElement('section');node.id='sahjony-legal-framework';node.innerHTML=`
      <div class="lf-head"><div><div class="lf-kicker">Business Rules · Legal Framework</div><h2>${cfg.title}</h2></div><div class="lf-role">${role}</div></div>
      <div class="lf-grid">
        <div class="lf-card"><h3>How this business operates</h3>${list([...(cfg.operate||[]),...common.operating])}</div>
        <div class="lf-card"><h3>Mandatory operating rules</h3>${list([...(cfg.rules||[]),...common.rules])}</div>
        <div class="lf-card"><h3>Legal / regulatory framework</h3>${list([...(cfg.legal||[]),...common.legal])}</div>
        <div class="lf-card"><h3>Evidence required</h3>${list(common.evidence)}</div>
      </div>
      <div class="lf-note"><strong>Authority:</strong> ${authority} Regulations and official guidance can change; transaction-specific rules must be revalidated before release. Official U.S. reference points include CBP, USITC HTS, BIS, OFAC, Census/AES, and applicable Partner Government Agencies.</div>`;
    const hero=host.querySelector('.hero');if(hero&&hero.parentNode===host) hero.insertAdjacentElement('afterend',node);else {const firstPanel=host.querySelector('.panel,.section,.grid');if(firstPanel) firstPanel.insertAdjacentElement('afterend',node);else host.appendChild(node)}
  }

  let timer;const schedule=()=>{clearTimeout(timer);timer=setTimeout(render,60)};
  const push=history.pushState.bind(history),replace=history.replaceState.bind(history);history.pushState=(...a)=>{push(...a);schedule()};history.replaceState=(...a)=>{replace(...a);schedule()};addEventListener('popstate',schedule);addEventListener('load',schedule);new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});schedule();
})();
