const byId = id => document.getElementById(id);
const filters = ['search', 'region', 'country', 'category'];
let suppliers = [];
function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function link(label, href) {
  const node = element('a', label);
  node.href = href;
  if (href.startsWith('https://')) { node.target = '_blank'; node.rel = 'noopener noreferrer'; }
  return node;
}
function render() {
  const query = byId('search').value.trim().toLocaleLowerCase();
  const rows = suppliers.filter(s => (!query || [s.name, s.country, s.category, ...s.products].join(' ').toLocaleLowerCase().includes(query)) && ['region', 'country', 'category'].every(key => !byId(key).value || byId(key).value === s[key]));
  byId('result-count').textContent = `${rows.length} of ${suppliers.length} suppliers`;
  byId('results').replaceChildren(...rows.map(s => {
    const card = element('article', '', 'card');
    card.append(element('span', 'SOURCED · NOT YET QUALIFIED', 'badge'), element('h2', s.name), element('p', `${s.country} · ${s.region} · Company location`, 'meta'), element('p', s.category, 'meta'), element('p', s.products.join(' · '), 'products'), element('p', `Source reviewed ${s.reviewed_on}`, 'details'));
    const links = element('div', '', 'links');
    links.append(link('Official product source ↗', s.source_url), link('Company contact / website ↗', s.contact_url));
    if (s.email) { const email = link(s.email, `mailto:${s.email}`); email.className = 'email'; links.append(email); }
    card.append(links);
    return card;
  }));
  if (!rows.length) byId('results').append(element('p', 'No suppliers match these filters. Try another product or clear the filters.', 'empty'));
}
async function load() {
  try {
    const response = await fetch('/data/worldwide-suppliers.json');
    if (!response.ok) throw new Error('Directory unavailable');
    const data = await response.json();
    suppliers = data.suppliers;
    for (const key of ['region', 'country', 'category']) {
      for (const value of [...new Set(suppliers.map(s => s[key]))].sort()) {
        const option = element('option', value); option.value = value; byId(key).append(option);
      }
    }
    byId('summary').textContent = `${suppliers.length} suppliers · ${new Set(suppliers.map(s => s.country)).size} countries · ${new Set(suppliers.map(s => s.region)).size} regions`;
    byId('review-date').textContent = data.researched_on;
    byId('review-date').dateTime = data.researched_on;
    render();
  } catch {
    byId('summary').textContent = 'Supplier directory could not be loaded.';
    const retry = element('button', 'Retry loading directory'); retry.onclick = load;
    byId('results').replaceChildren(retry);
  }
}
filters.forEach(key => byId(key).addEventListener('input', render));
byId('reset').onclick = () => { filters.forEach(key => byId(key).value = ''); render(); };
load();
