(() => {
  const select = document.getElementById('directory-supplier');
  const button = document.getElementById('directory-add');
  const status = document.getElementById('directory-status');
  let suppliers = [];
  async function request(path, options = {}) {
    const token = sessionStorage.getItem('sahjony.owner.token');
    if (!token) throw new Error('Sign in as owner to add a candidate.');
    const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Role': 'owner', Authorization: `Bearer ${token}` }, cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
    return data;
  }
  fetch('/data/worldwide-suppliers.json').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(data => {
    suppliers = data.suppliers;
    select.replaceChildren(new Option('Choose a supplier', ''));
    suppliers.forEach(s => select.add(new Option(`${s.name} · ${s.country} · ${s.category}`, s.id)));
  }).catch(() => { status.textContent = 'Unable to load supplier directory. Reload this page to retry.'; button.disabled = true; });
  button.addEventListener('click', async () => {
    const supplier = suppliers.find(s => s.id === select.value);
    const requestId = document.getElementById('request').value;
    const origin = document.getElementById('directory-origin').value.trim().toUpperCase();
    if (!supplier || !requestId || !/^[A-Z]{2}$/.test(origin)) {
      status.textContent = 'Choose a sourcing request, a supplier and a confirmed two-letter shipment origin code.'; return;
    }
    button.disabled = true;
    status.textContent = 'Checking existing candidates…';
    try {
      const path = `/global-sourcing/requests/${encodeURIComponent(requestId)}/candidates`;
      const existing = await request(path);
      if ((existing.candidates || []).some(c => c.source_evidence?.directory_id === supplier.id && c.supplier_country === origin)) {
        status.textContent = 'This supplier and origin are already attached to the selected request.'; return;
      }
      const data = await request(path, { method: 'POST', body: JSON.stringify({
        supplier_name: supplier.name, supplier_country: origin, website: supplier.contact_url,
        product_match: supplier.products.join(', '), source_reference: supplier.source_url,
        source_evidence: { directory_id: supplier.id, status: 'SOURCED', reviewed_on: supplier.reviewed_on, company_location: supplier.country, product_source: supplier.source_url, contact_source: supplier.contact_url, public_email: supplier.email, qualification: 'Pending; no quote, inventory or destination approval inferred' }
      }) });
      if (!data.candidate?.global_candidate_id) throw new Error('Server did not confirm candidate creation. Refresh before retrying.');
      status.textContent = `Candidate saved: ${data.candidate.global_candidate_id}. Quote and qualification checks remain pending.`;
      document.getElementById('reload').click();
    } catch (error) { status.textContent = `Could not add candidate: ${error.message}`; }
    finally { button.disabled = false; }
  });
})();
