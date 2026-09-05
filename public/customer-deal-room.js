(() => {
  const stages = ['RESEARCH_LEAD','QUALIFIED_DEMAND','RFQ_COMPLETE','SOURCING','FIRM_QUOTE','COMPLIANCE_PASS','CONTRACTED','FUNDED','IN_TRANSIT','DELIVERED','COLLECTED'];
  const stageLabels = {
    RESEARCH_LEAD:'Research',QUALIFIED_DEMAND:'Demanda validada',RFQ_COMPLETE:'RFQ completo',SOURCING:'Sourcing',FIRM_QUOTE:'Oferta firme',COMPLIANCE_PASS:'Compliance',CONTRACTED:'Contratado',FUNDED:'Fondos listos',IN_TRANSIT:'En tránsito',DELIVERED:'Entregado',COLLECTED:'Cerrado'
  };
  const forbiddenKeys = /supplier(_| )?(name|identity|quote|cost)|gross(_| )?margin|landed(_| )?cost|commission|internal|negotiation|risk_score|owner_notes|protected|margin/i;
  const token = (() => { try { return sessionStorage.getItem('sahjony.customer.token') || ''; } catch { return ''; } })();
  const auth = document.getElementById('auth');
  if (!token) auth?.classList.add('show');

  function safeText(value, fallback='—') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  }
  function firstArray(body){
    if (!body || typeof body !== 'object') return [];
    for (const value of Object.values(body)) if (Array.isArray(value)) return value;
    return [];
  }
  function visibleRecord(record){
    const out = {};
    for (const [k,v] of Object.entries(record || {})) if (!forbiddenKeys.test(k)) out[k]=v;
    return out;
  }
  async function api(path){
    const response = await fetch(path,{cache:'no-store',headers:{'X-Role':'customer','Authorization':`Bearer ${token}`}});
    if(response.status===401||response.status===403) throw new Error('AUTH');
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  function normalizeStage(record){
    const raw = String(record.stage || record.status || record.deal_stage || record.trade_stage || '').toUpperCase().replaceAll(' ','_');
    if(stages.includes(raw)) return raw;
    if(raw.includes('TRANSIT')||raw.includes('SHIP')) return 'IN_TRANSIT';
    if(raw.includes('DELIVER')) return 'DELIVERED';
    if(raw.includes('FUND')||raw.includes('PAID')) return 'FUNDED';
    if(raw.includes('CONTRACT')||raw.includes('PO')) return 'CONTRACTED';
    if(raw.includes('COMPLI')) return 'COMPLIANCE_PASS';
    if(raw.includes('QUOTE')) return 'FIRM_QUOTE';
    if(raw.includes('SOURC')) return 'SOURCING';
    if(raw.includes('RFQ')) return 'RFQ_COMPLETE';
    if(raw.includes('QUALIF')) return 'QUALIFIED_DEMAND';
    return 'RESEARCH_LEAD';
  }
  function renderRail(stage){
    const idx=stages.indexOf(stage); const rail=document.getElementById('rail'); if(!rail)return;
    rail.innerHTML=stages.map((s,i)=>`<div class="stage ${i<idx?'done':''} ${i===idx?'current':''}"><i></i><small>${String(i+1).padStart(2,'0')}</small><b>${stageLabels[s]}</b></div>`).join('');
  }
  function statusTag(value){
    const s=String(value||'PENDING').toUpperCase();
    const cls=/PASS|READY|COMPLETE|APPROVED|DELIVERED|PAID|OK/.test(s)?'ok':/FAIL|BLOCK|REJECT|ERROR/.test(s)?'bad':'hold';
    return `<span class="tag ${cls}">${safeText(value,'PENDING')}</span>`;
  }
  function renderRows(id, rows){
    const el=document.getElementById(id); if(!el)return;
    el.innerHTML=rows.length?rows.map(r=>`<div class="row"><div><small>${r.label}</small><b>${safeText(r.value)}</b></div>${r.status?statusTag(r.status):''}</div>`).join(''):`<div class="empty">Sin información compartida todavía.</div>`;
  }
  function chooseCase(records){
    if(!records.length) return null;
    return [...records].sort((a,b)=>{
      const ai=stages.indexOf(normalizeStage(a)), bi=stages.indexOf(normalizeStage(b));
      return bi-ai || String(b.updated_at||'').localeCompare(String(a.updated_at||''));
    })[0];
  }
  function nextFor(stage, record){
    const own = record.next_action_owner || record.responsible_party || (['RFQ_COMPLETE','FIRM_QUOTE','CONTRACTED'].includes(stage)?'CLIENTE':'SAHJONY');
    const text = record.customer_next_action || record.next_action || {
      RESEARCH_LEAD:'Confirma producto, cantidad, destino y fecha requerida.',QUALIFIED_DEMAND:'Completa los datos faltantes del RFQ.',RFQ_COMPLETE:'SAHJONY está preparando opciones de suministro.',SOURCING:'Estamos comparando proveedores y condiciones.',FIRM_QUOTE:'Revisa la oferta comercial y confirma cómo deseas proceder.',COMPLIANCE_PASS:'La operación está lista para documentación contractual.',CONTRACTED:'Completa el hito de pago indicado en tu acuerdo.',FUNDED:'SAHJONY coordina la preparación y liberación de la operación.',IN_TRANSIT:'Sigue los hitos logísticos y cualquier actualización de entrega.',DELIVERED:'Confirma recepción y reporta cualquier incidencia.',COLLECTED:'Operación completada. Puedes iniciar una nueva solicitud.'
    }[stage];
    return {own,text};
  }

  async function load(){
    if(!token){ document.getElementById('currentStatus').textContent='SESIÓN REQUERIDA'; renderRail('RESEARCH_LEAD'); return; }
    try{
      const results=await Promise.allSettled([
        api('/managed-trade/requests'), api('/documents'), api('/shipments'), api('/communications/timeline'), api('/compliance')
      ]);
      const trade=results[0].status==='fulfilled'?firstArray(results[0].value).map(visibleRecord):[];
      const docs=results[1].status==='fulfilled'?firstArray(results[1].value).map(visibleRecord):[];
      const ships=results[2].status==='fulfilled'?firstArray(results[2].value).map(visibleRecord):[];
      const msgs=results[3].status==='fulfilled'?firstArray(results[3].value).map(visibleRecord):[];
      const controls=results[4].status==='fulfilled'?firstArray(results[4].value).map(visibleRecord):[];
      const deal=chooseCase(trade);
      const stage=deal?normalizeStage(deal):'RESEARCH_LEAD'; renderRail(stage);
      document.getElementById('currentStatus').textContent=stageLabels[stage].toUpperCase();
      document.getElementById('caseId').textContent=safeText(deal?.request_id||deal?.case_id||deal?.id,'Sin operación activa');
      const next=nextFor(stage,deal||{}); document.getElementById('nextOwner').textContent=next.own;
      document.getElementById('nextAction').textContent=next.text;
      document.getElementById('nextDetail').textContent=deal?.customer_next_action_detail||'Sofía y el equipo SAHJONY mantendrán esta vista actualizada con la próxima acción autorizada.';
      document.getElementById('nextDue').textContent=deal?.next_action_due_at?`Objetivo: ${deal.next_action_due_at}`:'Sin fecha pendiente';
      document.getElementById('product').textContent=safeText(deal?.product_need||deal?.product||deal?.title,'Solicitud comercial');
      renderRows('commercial',[
        {label:'Cantidad',value:deal?.quantity||deal?.volume||deal?.container_quantity},
        {label:'Destino',value:deal?.destination||deal?.destination_port||deal?.destination_country},
        {label:'Fecha requerida',value:deal?.required_date||deal?.delivery_window},
        {label:'Término comercial',value:deal?.customer_incoterm||deal?.incoterm,status:deal?.commercial_status}
      ].filter(x=>x.value));
      renderRows('controls',(controls.length?controls.slice(0,6):[
        {control:'Identidad / KYB',status:deal?.kyb_status||'PENDING'},
        {control:'Producto / exportación',status:deal?.export_control_status||'PENDING'},
        {control:'Ruta de pago',status:deal?.payment_compliance_status||'PENDING'},
        {control:'Documentación',status:deal?.documents_status||'PENDING'}
      ]).map(c=>({label:c.control||c.name||c.type||'Control',value:c.description||c.customer_note||c.status,status:c.status})));
      renderRows('shipping',ships.slice(0,6).map(s=>({label:s.milestone||s.event||s.type||'Hito',value:s.location||s.description||s.eta||s.updated_at,status:s.status||s.state})));
      renderRows('documents',docs.slice(0,6).map(d=>({label:d.document_type||d.type||d.title||d.name||'Documento',value:d.customer_label||d.file_name||d.updated_at,status:d.status||d.state})));
      renderRows('messages',msgs.slice(0,6).map(m=>({label:m.sender_name||m.channel||m.direction||'Actualización',value:m.customer_summary||m.summary||m.message||m.body||m.created_at,status:m.status})));
    }catch(e){
      if(e.message==='AUTH'){ auth?.classList.add('show'); document.getElementById('currentStatus').textContent='SESIÓN EXPIRADA'; }
      else { document.getElementById('currentStatus').textContent='TEMPORALMENTE NO DISPONIBLE'; document.getElementById('nextAction').textContent='No pudimos cargar la operación en este momento.'; document.getElementById('nextDetail').textContent='Vuelve a intentarlo desde el portal de cliente. Ningún estado comercial se ha cambiado.'; }
      renderRail('RESEARCH_LEAD');
    }
  }
  load();
})();