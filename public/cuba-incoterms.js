(()=>{
  'use strict';
  const path=location.pathname.replace(/\/+$/,'');
  if(path!=='/cuba-order'&&path!=='/cuba-order.html'&&path!=='/cuba-payments'&&path!=='/cuba-payments.html')return;
  if(document.querySelector('.sahjony-incoterms-card'))return;

  const style=document.createElement('style');
  style.textContent=`
    .sahjony-incoterms-card{margin:18px 0 24px;border:1px solid rgba(232,201,119,.28);border-radius:18px;background:linear-gradient(135deg,rgba(232,201,119,.07),rgba(110,220,255,.045));padding:18px;color:#eaf3f8}
    .sahjony-incoterms-card h3{margin:0 0 7px;font-size:18px;letter-spacing:-.02em}.sahjony-incoterms-card>p{margin:0 0 14px;color:#aebfca;font-size:11px;line-height:1.65}
    .sahjony-incoterms-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.sahjony-incoterm{border:1px solid rgba(255,255,255,.11);border-radius:13px;padding:13px;background:rgba(4,14,23,.52)}
    .sahjony-incoterm b{display:block;font-size:12px;margin-bottom:5px}.sahjony-incoterm span{display:block;color:#b9c9d3;font-size:10px;line-height:1.55}.sahjony-incoterm.cif b{color:#79efb5}.sahjony-incoterm.cfr b{color:#6edcff}
    .sahjony-cif-scope{margin-top:10px;padding:12px 13px;border-left:3px solid #e8c977;background:rgba(232,201,119,.04);border-radius:9px;color:#cfc7ae;font-size:10px;line-height:1.6}.sahjony-cif-scope strong{color:#f6e7b3}
    @media(max-width:620px){.sahjony-incoterms-grid{grid-template-columns:1fr}}
  `;
  document.head.appendChild(style);

  const card=document.createElement('section');
  card.className='sahjony-incoterms-card';
  card.innerHTML=`<h3>¿Qué significa CIF Mariel?</h3><p>Los precios identificados como CIF Mariel usan el Incoterm CIF — Cost, Insurance and Freight. Para que el comprador entienda exactamente la oferta, mostramos también la diferencia con CFR.</p><div class="sahjony-incoterms-grid"><div class="sahjony-incoterm cfr"><b>CFR · Cost and Freight</b><span>Incluye mercancía y flete marítimo hasta el puerto de destino acordado. El vendedor no tiene la obligación CIF de contratar el seguro marítimo del comprador.</span></div><div class="sahjony-incoterm cif"><b>CIF · Cost, Insurance and Freight</b><span>Incluye mercancía, flete marítimo y la cobertura de seguro requerida por la regla CIF hasta el puerto de destino acordado.</span></div></div><div class="sahjony-cif-scope"><strong>CIF Mariel no significa entrega total hasta su negocio.</strong> Cargos de destino, despacho aduanero, impuestos, almacenaje, transporte interior en Cuba u otros costos locales no se consideran incluidos salvo que la proforma final lo indique expresamente. En CFR y CIF, la transferencia de riesgo se rige por el Incoterm pactado y no debe confundirse con quién paga el flete.</div>`;

  const anchor=document.querySelector('.hero')||document.querySelector('main')||document.body;
  if(anchor.classList?.contains('hero')) anchor.insertAdjacentElement('afterend',card);
  else anchor.prepend(card);
})();
