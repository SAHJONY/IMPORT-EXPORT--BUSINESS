(()=>{
  'use strict';
  if(location.pathname!=='/cuba-order.html'&&location.pathname!=='/cuba-order')return;

  const catalog={
    'pierna y muslo de pollo':{theme:'blue',label:'MÁS VENDIDO',price:'$39,150',facts:['26 TM','26,000 KG','57,320 LB'],extra:'Cajas / piezas: por confirmar según empaque final',img:'https://unsplash.com/photos/gpkRa3elzrI/download?force=true&w=3200',alt:'Pierna y muslo de pollo congelado'},
    'pechuga de pollo':{theme:'red',price:'$82,350',facts:['22 TM','22,000 KG','48,502 LB'],extra:'Cajas / piezas: por confirmar según corte y empaque final',img:'https://unsplash.com/photos/CzvSe6Q1H7Y/download?force=true&w=3200',alt:'Pechuga de pollo cruda'},
    'pierna de cerdo':{theme:'burgundy',price:'$73,350',facts:['24 TM','24,000 KG','52,911 LB'],extra:'Cajas / piezas: por confirmar según corte y empaque final',img:'https://unsplash.com/photos/DxJvLtab4ak/download?force=true&w=3200',alt:'Pierna de cerdo cruda'},
    'arroz blanco':{theme:'green',price:'$30,150',facts:['26 TM','26,000 KG','57,320 LB'],extra:'520 sacos × 50 KG si la carga neta final es 26 TM',img:'https://unsplash.com/photos/McsOzv-Ieoc/download?force=true&w=3200',alt:'Arroz blanco de grano largo'},
    'leche en polvo':{theme:'milk',price:'$70,650',facts:['22 TM','22,000 KG','48,502 LB'],extra:'880 sacos × 25 KG si la carga neta final es 22 TM',img:'https://unsplash.com/photos/8manzosRGPE/download?force=true&w=3200',alt:'Leche en polvo'},
    'aceite de soya':{theme:'yellow',price:'$39,600',facts:['20 TM','20,000 KG','44,092 LB'],extra:'Presentación solicitada: 5 L · unidades por confirmar con proveedor',img:'https://unsplash.com/photos/9aOswReDKPo/download?force=true&w=3200',alt:'Aceite de soya comestible'},
    'agua embotellada':{theme:'aqua',price:'$30,150',facts:['18 TM','18,000 KG','39,683 LB'],extra:'500 ml × 24 · packs y botellas finales sujetos a palletización y peso bruto',img:'https://unsplash.com/photos/1AhGNGKuhR0/download?force=true&w=3200',alt:'Agua embotellada de 500 ml'}
  };

  const style=document.createElement('style');
  style.textContent=`
    .product{position:relative}
    .product[data-merch-theme=blue]{box-shadow:0 18px 55px rgba(20,97,255,.22)}
    .product[data-merch-theme=green]{box-shadow:0 18px 55px rgba(40,180,95,.20)}
    .product[data-merch-theme=yellow]{box-shadow:0 18px 55px rgba(255,190,20,.20)}
    .product[data-merch-theme=red]{box-shadow:0 18px 55px rgba(225,43,53,.20)}
    .product[data-merch-theme=burgundy]{box-shadow:0 18px 55px rgba(145,25,45,.22)}
    .product[data-merch-theme=milk]{box-shadow:0 18px 55px rgba(88,173,255,.18)}
    .product[data-merch-theme=aqua]{box-shadow:0 18px 55px rgba(44,190,235,.20)}
    .merch-ribbon{position:absolute;right:13px;top:13px;z-index:5;border-radius:999px;padding:7px 9px;font-size:8px;font-weight:950;letter-spacing:.08em;background:#ffd400;color:#151515;border:1px solid rgba(255,255,255,.5)}
    .merch-facts{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:13px}
    .merch-fact{border:1px solid rgba(255,255,255,.10);border-radius:10px;padding:8px 7px;background:rgba(255,255,255,.035);text-align:center;font-size:10px;font-weight:900}
    .merch-extra{margin-top:8px;font-size:9px;line-height:1.45;color:#a9bdcb}
    .merch-price-note{margin-top:9px;font-size:9px;color:#79efb5;font-weight:900}
    .merch-transparency{margin:20px 0;border:1px solid rgba(110,220,255,.25);border-radius:18px;background:linear-gradient(135deg,rgba(110,220,255,.06),rgba(121,239,181,.04));padding:18px}
    .merch-transparency h3{margin:0 0 6px;font-size:18px}.merch-transparency p{margin:0;color:#9eb2c1;font-size:11px;line-height:1.6}
    @media(max-width:620px){.merch-facts{grid-template-columns:1fr 1fr 1fr}.merch-fact{font-size:9px}}
  `;
  document.head.appendChild(style);

  function keyFor(card){
    const t=(card.textContent||'').toLowerCase();
    return Object.keys(catalog).find(k=>t.includes(k));
  }

  function decorate(){
    const cards=[...document.querySelectorAll('.product')];
    if(!cards.length)return false;
    cards.forEach(card=>{
      if(card.dataset.merchDone==='1')return;
      const key=keyFor(card); if(!key)return;
      const m=catalog[key];
      card.dataset.merchDone='1';card.dataset.merchTheme=m.theme;
      const img=card.querySelector('img'); if(img){img.src=m.img;img.alt=m.alt;img.loading='lazy';img.decoding='async'}
      if(m.label){const r=document.createElement('div');r.className='merch-ribbon';r.textContent=m.label;card.appendChild(r)}
      const body=card.querySelector('.product-body')||card;
      const facts=document.createElement('div');facts.className='merch-facts';
      m.facts.forEach(x=>{const el=document.createElement('div');el.className='merch-fact';el.textContent=x;facts.appendChild(el)});
      const extra=document.createElement('div');extra.className='merch-extra';extra.textContent=m.extra;
      const note=document.createElement('div');note.className='merch-price-note';note.textContent=`Precio indicativo CIF Mariel: ${m.price} por contenedor`;
      body.append(facts,extra,note);
    });
    const host=document.querySelector('.catalog')?.parentElement;
    if(host&&!document.querySelector('.merch-transparency')){
      const box=document.createElement('section');box.className='merch-transparency';
      box.innerHTML='<h3>Transparencia total por contenedor</h3><p>La foto corresponde a la categoría del producto seleccionado. Peso, presentación y cantidades se muestran por contenedor. Cuando cajas, piezas, packs o botellas dependen del empaque final del proveedor, la aplicación lo identifica expresamente como pendiente de confirmación antes de la proforma.</p>';
      host.insertBefore(box,host.querySelector('.notice')||null);
    }
    return true;
  }

  if(!decorate()){
    const o=new MutationObserver(()=>{if(decorate())o.disconnect()});
    o.observe(document.body,{childList:true,subtree:true});
    setTimeout(()=>o.disconnect(),10000);
  }
})();
