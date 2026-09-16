(()=>{'use strict';
if(location.pathname.startsWith('/owner'))return;
const sent=new Set();
const locale=()=>{try{return (localStorage.getItem('sahjony.locale')||document.documentElement.lang||'en').slice(0,16)}catch{return document.documentElement.lang||'en'}};
function emit(event,source){const key=event+'|'+location.pathname+'|'+(source||'');if(sent.has(key)&&!event.endsWith('_complete'))return;sent.add(key);fetch('/conversion/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event,page:location.pathname,locale:locale(),source:source||null}),keepalive:true}).catch(()=>{})}
function isRfqPage(){return location.pathname==='/'||location.pathname==='/start'||location.pathname==='/es/start'}
if(isRfqPage())emit('rfq_view','page_view');
document.addEventListener('click',e=>{const a=e.target.closest?.('a[href]');if(!a)return;const href=a.getAttribute('href')||'';if(href.startsWith('tel:+12816628581'))emit('call_click',href);else if(href.includes('Callback')||href.toLowerCase().includes('callback'))emit('callback_click',href);else if(href.includes('wa.me/12816628581'))emit('whatsapp_handoff',href)},true);
let supplierStarted=false;document.addEventListener('focusin',e=>{if(supplierStarted)return;const f=e.target.closest?.('form');if(f&&(location.pathname==='/suppliers'||location.pathname==='/es/suppliers')){supplierStarted=true;emit('supplier_registration_start','form_focus')}},true);
window.addEventListener('sahjony:conversion',e=>{const name=e.detail?.event;if(['rfq_submit','supplier_registration_complete'].includes(name))emit(name,e.detail?.source||'app')});
})();
