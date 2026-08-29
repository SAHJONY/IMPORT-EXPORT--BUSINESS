(()=>{
  'use strict';

  const DATA={
    muslo:{label:'Pierna y muslo de pollo',tm:26,kg:26000,lb:57320,container:'40ft reefer',pack:'Empaque comercial sujeto a proforma',units:'Cajas / piezas: por confirmar según peso por caja y especificación final',unitStatus:'pending'},
    pechuga:{label:'Pechuga de pollo',tm:22,kg:22000,lb:48502,container:'40ft reefer',pack:'Empaque comercial sujeto a proforma',units:'Cajas / piezas: por confirmar según peso por caja y especificación final',unitStatus:'pending'},
    cerdo:{label:'Pierna de cerdo',tm:24,kg:24000,lb:52911,container:'40ft reefer',pack:'Empaque comercial sujeto a proforma',units:'Cajas / piezas: por confirmar según peso por caja y especificación final',unitStatus:'pending'},
    arroz:{label:'Arroz blanco',tm:26,kg:26000,lb:57320,container:'40ft dry',pack:'Bolsa de 50 kg',units:'520 sacos de 50 kg por contenedor, si la carga neta final es 26,000 kg',unitStatus:'calculated'},
    leche:{label:'Leche en polvo',tm:22,kg:22000,lb:48502,container:'40ft dry',pack:'Bolsa de 25 kg',units:'880 sacos de 25 kg por contenedor, si la carga neta final es 22,000 kg',unitStatus:'calculated'},
    aceite:{label:'Aceite de soya',tm:20,kg:20000,lb:44092,container:'40ft dry',pack:'Presentación final por confirmar',units:'Botellas / cajas / IBC: por confirmar según presentación aprobada del proveedor',unitStatus:'pending'},
    agua:{label:'Agua embotellada 500 ml × 24',tm:18,kg:18000,lb:39683,container:'40ft dry',pack:'500 ml × 24 por pack',units:'Equivalente teórico: aprox. 1,500 packs / 36,000 botellas si 18,000 kg corresponde al contenido neto de agua. Cantidad final depende de palletización y peso bruto.',unitStatus:'estimate'}
  };

  const fmt=n=>Number(n).toLocaleString('en-US');
  const style=document.createElement('style');
  style.textContent=`
    .sahjony-transparency-strip{margin-top:13px;padding:11px 12px;border:1px solid rgba(110,220,255,.2);border-radius:13px;background:rgba(4,14,23,.64);display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
    .sahjony-transparency-strip div{min-width:0}.sahjony-transparency-strip b{display:block;font-size:8px;letter-spacing:.07em;color:#8fa8b9;margin-bottom:3px}.sahjony-transparency-strip span{font-size:10px;color:#edf7fc;font-weight:800;line-height:1.35}
    .sahjony-transparency-panel{margin-top:12px;border:1px solid rgba(121,239,181,.25);border-radius:15px;padding:14px;background:rgba(121,239,181,.025)}
    .sahjony-transparency-panel h4{margin:0 0 10px;font-size:12px;color:#79efb5}.sahjony-transparency-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.sahjony-transparency-cell{border:1px solid rgba(255,255,255,.1);border-radius:11px;padding:10px;background:rgba(255,255,255,.02)}
    .sahjony-transparency-cell b{display:block;font-size:8px;color:#8fa8b9;margin-bottom:4px}.sahjony-transparency-cell span{font-size:11px;color:#eef7fb;line-height:1.4}.sahjony-unit-note{margin-top:9px;padding:10px 11px;border-radius:11px;background:#05101a;color:#c9dae5;font-size:10px;line-height:1.55}.sahjony-unit-note[data-status="calculated"]{border-left:3px solid #79efb5}.sahjony-unit-note[data-status="estimate"]{border-left:3px solid #e8c977}.sahjony-unit-note[data-status="pending"]{border-left:3px solid #6edcff}
    .sahjony-order-transparency{margin:11px 0;border:1px solid rgba(110,220,255,.22);border-radius:13px;padding:12px;background:rgba(110,220,255,.025);font-size:10px;line-height:1.55;color:#c8d8e3}.sahjony-order-transparency strong{color:#fff}
    @media(max-width:620px){.sahjony-transparency-strip{grid-template-columns:1fr 1fr}.sahjony-transparency-grid{grid-template-columns:1fr 1fr}}
  `;
  document.head.appendChild(style);

  function idForCard(card){return card?.dataset?.id||card?.getAttribute('data-id')||''}
  function stripMarkup(x){return `<div class="sahjony-transparency-strip"><div><b>PESO NETO NOMINAL</b><span>${fmt(x.kg)} kg</span></div><div><b>LIBRAS</b><span>${fmt(x.lb)} lb</span></div><div><b>CONTENEDOR</b><span>${x.container}</span></div></div>`}
  function panelMarkup(x){return `<section class="sahjony-transparency-panel" data-product-transparency><h4>TRANSPARENCIA DEL CONTENEDOR</h4><div class="sahjony-transparency-grid"><div class="sahjony-transparency-cell"><b>TONELADAS MÉTRICAS</b><span>${x.tm} TM</span></div><div class="sahjony-transparency-cell"><b>KILOGRAMOS</b><span>${fmt(x.kg)} kg</span></div><div class="sahjony-transparency-cell"><b>LIBRAS</b><span>${fmt(x.lb)} lb</span></div><div class="sahjony-transparency-cell"><b>PRESENTACIÓN</b><span>${x.pack}</span></div></div><div class="sahjony-unit-note" data-status="${x.unitStatus}"><strong>Cantidad de unidades/bultos:</strong> ${x.units}</div></section>`}

  function enrichCards(){
    document.querySelectorAll('.product[data-id]').forEach(card=>{
      const x=DATA[idForCard(card)]; if(!x||card.querySelector('.sahjony-transparency-strip'))return;
      const body=card.querySelector('.product-body')||card;
      body.insertAdjacentHTML('beforeend',stripMarkup(x));
    });
  }

  function currentId(){
    const select=document.getElementById('product');
    if(select?.value&&DATA[select.value])return select.value;
    return document.querySelector('.product.active[data-id]')?.dataset?.id||'';
  }

  function enrichDetails(){
    const details=document.getElementById('details');
    const id=currentId(); const x=DATA[id];
    if(!details||!x||details.querySelector('[data-product-transparency]'))return;
    const content=details.querySelector('.detail-content')||details;
    content.insertAdjacentHTML('beforeend',panelMarkup(x));
  }

  function ensureOrderBox(){
    const summary=document.getElementById('summary'); if(!summary)return null;
    let box=document.querySelector('.sahjony-order-transparency');
    if(!box){box=document.createElement('div');box.className='sahjony-order-transparency';summary.insertAdjacentElement('afterend',box)}
    return box;
  }

  function updateOrderBox(){
    const id=currentId(); const x=DATA[id]; const box=ensureOrderBox(); if(!box)return;
    if(!x){box.innerHTML='<strong>Transparencia del contenedor:</strong> seleccione un producto para ver kg, lb y unidades/bultos.';return}
    const count=Math.max(1,Number(document.getElementById('containers')?.value||1));
    const totalKg=x.kg*count,totalLb=x.lb*count,totalTm=x.tm*count;
    box.innerHTML=`<strong>${x.label}</strong><br>${count} contenedor(es) · ${totalTm} TM · ${fmt(totalKg)} kg · ${fmt(totalLb)} lb<br>${x.units}`;
  }

  function syncSpecifications(){
    const id=currentId(),x=DATA[id],ta=document.getElementById('specifications'); if(!x||!ta)return;
    const marker='TRANSPARENCIA DE CARGA:';
    const line=`${marker} ${x.tm} TM = ${fmt(x.kg)} kg = ${fmt(x.lb)} lb por contenedor. Presentación: ${x.pack}. Unidades/bultos: ${x.units}`;
    const existing=ta.value||'';
    const cleaned=existing.replace(/TRANSPARENCIA DE CARGA:[^\n]*/g,'').trim();
    ta.value=(line+(cleaned?'\n'+cleaned:'')).trim();
  }

  function boot(){
    enrichCards(); updateOrderBox();
    const catalog=document.getElementById('catalog');
    catalog?.addEventListener('click',()=>setTimeout(()=>{enrichDetails();updateOrderBox()},30));
    const select=document.getElementById('product');
    select?.addEventListener('change',()=>setTimeout(()=>{updateOrderBox();syncSpecifications();enrichDetails()},20));
    document.getElementById('containers')?.addEventListener('input',updateOrderBox);
    const observer=new MutationObserver(()=>{enrichCards();enrichDetails()});
    if(catalog)observer.observe(catalog,{childList:true,subtree:true});
    setTimeout(()=>{enrichCards();enrichDetails();updateOrderBox()},300);
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

(()=>{
  if(document.querySelector('script[data-cuba-merchandising]'))return;
  const script=document.createElement('script');
  script.src='/cuba-merchandising.js?v=20260829b';
  script.defer=true;
  script.dataset.cubaMerchandising='true';
  document.head.appendChild(script);
})();
