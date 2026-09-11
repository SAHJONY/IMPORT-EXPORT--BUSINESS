const $ = id => document.getElementById(id);
let prospects = [], suppliers = [], providers = [], quotes = [];
let page = 1; const pageSize = 24;
function node(tag, text, cls) { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; }
function source(label, url) { const a = node('a', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
async function api(path, options = {}) {
  const token = sessionStorage.getItem('sahjony.owner.token');
  if (!token) { location.replace('/owner-login'); throw new Error('Se requiere acceso de propietario.'); }
  const r = await fetch(path, { ...options, cache: 'no-store', headers: { 'X-Role': 'owner', Authorization: `Bearer ${token}` } });
  if ([401, 403].includes(r.status)) { location.replace('/owner-login'); throw new Error('Sesión no autorizada.'); }
  if (!r.ok) throw new Error(`No se pudo completar la operación (${r.status}).`);
  return r.json();
}
function render() {
  const q = $('search').value.toLocaleLowerCase().trim();
  if ($('view').value !== 'buyers') { renderShipping(q); return; }
  const filtered = prospects.filter(p => [p.business_name, p.province, p.sector, p.proposal].join(' ').toLocaleLowerCase().includes(q) && ($('contacts').value !== 'available' || p.public_email || p.public_phone) && ($('contacts').value !== 'matched' || p.supplier_ids.length));
  const rows = paginate(filtered);
  $('results').replaceChildren(...rows.map(p => {
    const card = node('article', '', 'card');
    card.append(node('span', 'INVESTIGADO · DEMANDA POR CONFIRMAR', 'badge'), node('h2', p.business_name), node('p', `${p.province} · ${p.sector}`, 'meta'), node('p', p.observed_activity), node('h3', 'Propuesta de suministro (inferencia)'), node('p', p.proposal), node('p', p.ownership_evidence, 'details'), node('p', p.next_step, 'details'));
    card.append(node('h3', 'Proveedores posibles · sin vínculo confirmado'));
    const matches = node('div', '', 'links');
    p.supplier_ids.forEach(id => { const s = suppliers.find(s => s.id === id); if (s) matches.append(source(`${s.name} · ${s.country}`, s.source_url)); });
    card.append(matches);
    const links = node('div', '', 'links'); links.append(source('Fuente de actividad ↗', p.source_url));
    p.evidence_urls.forEach((url, i) => links.append(source(`Evidencia ${i + 1} ↗`, url))); card.append(links, node('p', `Revisado: ${p.researched_on} · Importe y cantidad: no confirmados`, 'details'));
    const contacts = node('div', '', 'links');
    if (p.public_email) { const a=node('a',p.public_email);a.href='mailto:'+p.public_email;contacts.append(a); }
    if (p.public_phone) { const a=node('a',p.public_phone);a.href='tel:+'+p.public_phone.replace(/\D/g,'');contacts.append(a); }
    if (!p.public_email && !p.public_phone) contacts.append(node('p','Contacto directo no publicado.','details'));
    card.append(contacts);
    const button = node('button', 'Añadir a cola de calificación');
    const feedback = node('p', '', 'details'); feedback.setAttribute('role', 'status');
    button.onclick = async () => {
      button.disabled = true; feedback.textContent = 'Guardando…';
      try { const result = await api(`/global-sourcing/cuba-prospects/${encodeURIComponent(p.id)}/import`, { method: 'POST' });
        if (!result.lead_id) throw new Error('El servidor no confirmó el registro.');
        feedback.textContent = `${result.already_present ? 'Ya existe' : 'Guardado'}: ${result.lead_id}. Pendiente de calificación.`;
        button.textContent = 'Prospecto en CRM';
      } catch (error) { feedback.textContent = error.message; button.disabled = false; }
    };
    card.append(button, feedback); return card;
  }));
  $('status').textContent = `${filtered.length} prospectos · ${prospects.filter(p => p.public_email || p.public_phone).length} con contacto publicado · guardados en CRM`;
  if (!rows.length) $('results').append(node('p', 'No hay coincidencias. Prueba otra búsqueda.', 'empty'));
}
async function load() {
  try {
    const [data, directory] = await Promise.all([api('/global-sourcing/cuba-prospects'), fetch('/data/worldwide-suppliers.json').then(r => { if (!r.ok) throw new Error('Directorio no disponible.'); return r.json(); })]);
    prospects = data.prospects; suppliers = directory.suppliers; providers=data.providers; quotes=data.quotes;
    $('summary').textContent = `${prospects.length} prospectos · 0 pedidos confirmados · revisión ${data.researched_on}`;
    render();
  } catch (error) { $('summary').textContent = error.message; }
}
function paginate(rows) {
  const pages=Math.max(1,Math.ceil(rows.length/pageSize));page=Math.min(page,pages);
  $('page').textContent=`${page} / ${pages}`;$('prev').disabled=page===1;$('next').disabled=page===pages;
  return rows.slice((page-1)*pageSize,page*pageSize);
}
function renderShipping(q) {
  const isQuotes=$('view').value==='quotes';
  const rows=paginate((isQuotes?quotes:providers).filter(p=>JSON.stringify(p).toLocaleLowerCase().includes(q)));
  $('results').replaceChildren(...rows.map(p=>{
    const card=node('article','','card');
    if(isQuotes) {
      card.append(node('span','TARIFA RECIBIDA · NO ES COSTO ENTREGADO','badge'),node('h2',p.product),node('p',`${p.currency} ${p.price.toLocaleString()} / ${p.unit}`),node('p',`${p.origin} → ${p.destination} · ${p.basis}`,'meta'),node('p',`Válida hasta ${p.valid_until}`),node('p','Incluye: '+p.included.join(', '),'details'),node('p','Pendiente / excluido: '+p.excluded_or_unconfirmed.join(', '),'details'),node('p','Ventaja frente a competencia: no verificada.','details'));
    } else {
      card.append(node('span',p.first_hand_carrier?'TRANSPORTISTA DIRECTO':'SERVICIO COMPLEMENTARIO','badge'),node('h2',p.name),node('p',`${p.role} · ${p.modes.join(' / ')}`,'meta'),node('p',p.route),node('p',p.notes),node('p',p.rate_status+' · reserva pendiente de aprobación','details'));
      if(p.email){const a=node('a',p.email);a.href='mailto:'+p.email;card.append(a);}
      if(p.phone){const a=node('a',p.phone);a.href='tel:'+p.phone;card.append(a);}
      if(p.contact_url)card.append(source('Contacto oficial',p.contact_url));
    }
    card.append(source('Abrir evidencia',p.source_url));return card;
  }));
  $('status').textContent=isQuotes?'4 tarifas de un mismo proveedor; no son cuatro ofertas competidoras.':'Operadores directos y servicios complementarios. Ningún paquete completo A–Z está confirmado.';
}
$('search').oninput = () => {page=1;render();};
$('view').onchange=$('contacts').onchange=()=>{page=1;render();};
$('prev').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
$('reload').onclick = load; load();
