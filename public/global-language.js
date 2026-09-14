(()=>{
  'use strict';

  const STORAGE='sahjony.locale';
  const QUERY='lang';
  const UI_TRANSLATE='/ui-language/translate-batch';
  const UI_GEO='/ui-language/geo';
  const RTL=new Set(['ar','fa','he','ur','ps','sd','ug','yi']);
  const LOCALES=['en-US','es'];
  const SKIP_TAGS=new Set(['SCRIPT','STYLE','NOSCRIPT','CODE','PRE','TEXTAREA']);
  const originalText=new WeakMap();
  const originalAttrs=new WeakMap();
  const cache=new Map();
  let busy=false;
  let active='';
  let observerTimer=null;

  function normalizeLocale(value){
    const raw=String(value||'').trim().replaceAll('_','-');
    if(!raw)return '';
    const lower=raw.toLowerCase();
    if(lower==='en'||lower.startsWith('en-'))return 'en-US';
    if(lower==='es'||lower.startsWith('es-'))return 'es';
    const parts=raw.split('-').filter(Boolean);
    if(!parts.length)return '';
    const base=parts[0].toLowerCase();
    if(!/^[a-z]{2,3}$/.test(base))return '';
    return [base,...parts.slice(1).map(part=>{
      if(/^[a-zA-Z]{2}$/.test(part))return part.toUpperCase();
      if(/^[a-zA-Z]{4}$/.test(part))return part[0].toUpperCase()+part.slice(1).toLowerCase();
      return part;
    })].join('-');
  }
  const baseLocale=value=>normalizeLocale(value).split('-')[0].toLowerCase();
  const sameLanguage=(a,b)=>baseLocale(a)===baseLocale(b);
  const direction=locale=>RTL.has(baseLocale(locale))?'rtl':'ltr';
  const sourceLocale=normalizeLocale(document.documentElement.dataset.sourceLocale||document.documentElement.lang||'en-US')||'en-US';

  function requestedLocale(){
    const p=new URLSearchParams(location.search);
    return normalizeLocale(p.get(QUERY)||p.get('locale')||'');
  }
  function storedLocale(){try{return normalizeLocale(localStorage.getItem(STORAGE)||'')}catch{return ''}}
  function setStored(locale){try{localStorage.setItem(STORAGE,normalizeLocale(locale)||sourceLocale)}catch{}}
  function rewriteUrl(locale){
    try{const u=new URL(location.href);const marker=normalizeLocale(locale)||sourceLocale;u.searchParams.delete('locale');u.searchParams.set('lang',marker);history.replaceState(history.state,'',u.pathname+u.search+u.hash)}catch{}
  }
  function propagateLinks(locale){
    const marker=normalizeLocale(locale)||sourceLocale;
    document.querySelectorAll('a[href]').forEach(a=>{
      if(a.closest('[data-no-translate]'))return;
      const raw=a.getAttribute('href');
      if(!raw||raw.startsWith('#')||raw.startsWith('mailto:')||raw.startsWith('tel:')||raw.startsWith('javascript:'))return;
      try{const u=new URL(raw,location.origin);if(u.origin!==location.origin)return;u.searchParams.delete('locale');u.searchParams.set('lang',marker);a.setAttribute('href',u.pathname+u.search+u.hash)}catch{}
    });
  }
  function propagateForms(locale){
    const marker=normalizeLocale(locale)||sourceLocale;
    document.querySelectorAll('form').forEach(form=>{
      const method=(form.getAttribute('method')||'get').toLowerCase();
      if(method!=='get'||form.closest('[data-no-translate]'))return;
      let input=form.querySelector('input[type="hidden"][name="lang"][data-sahjony-locale]');
      if(!input){input=document.createElement('input');input.type='hidden';input.name='lang';input.dataset.sahjonyLocale='true';form.appendChild(input)}
      input.value=marker;
    });
  }
  function propagateNavigation(locale){propagateLinks(locale);propagateForms(locale)}
  function announceLocale(locale){
    try{window.dispatchEvent(new CustomEvent('sahjony:localechange',{detail:{locale:normalizeLocale(locale)||sourceLocale}}))}catch{}
  }
  function meaningful(value){const text=String(value||'').trim();return text.length>=2&&!/^[-+–—•·|/\\\s\d.,:$%()]+$/.test(text)}
  function blocked(el){return !el||SKIP_TAGS.has(el.tagName)||Boolean(el.closest('[data-no-translate],.sahjony-language'))}
  function collect(){
    const items=[];
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode(node){const el=node.parentElement;return blocked(el)||!meaningful(node.nodeValue)?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT}});
    let node;
    while((node=walker.nextNode())){if(!originalText.has(node))originalText.set(node,node.nodeValue||'');items.push({kind:'text',node,text:(originalText.get(node)||'').trim()})}
    document.querySelectorAll('*').forEach(el=>{
      if(blocked(el))return;
      for(const attr of ['placeholder','title','aria-label']){const current=el.getAttribute(attr);if(!meaningful(current))continue;let map=originalAttrs.get(el);if(!map){map={};originalAttrs.set(el,map)}if(!(attr in map))map[attr]=current;items.push({kind:'attr',el,attr,text:String(map[attr]).trim()})}
      if(el.tagName==='INPUT'&&['button','submit','reset'].includes((el.getAttribute('type')||'').toLowerCase())){const current=el.getAttribute('value');if(meaningful(current)){let map=originalAttrs.get(el);if(!map){map={};originalAttrs.set(el,map)}if(!('value' in map))map.value=current;items.push({kind:'attr',el,attr:'value',text:String(map.value).trim()})}}
      if(el.tagName==='OPTION'){const current=el.textContent||'';if(meaningful(current)){if(!originalText.has(el))originalText.set(el,current);items.push({kind:'option',el,text:String(originalText.get(el)||'').trim()})}}
    });
    return items;
  }
  function restore(){const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;while((node=walker.nextNode()))if(originalText.has(node))node.nodeValue=originalText.get(node);document.querySelectorAll('*').forEach(el=>{const map=originalAttrs.get(el);if(map)for(const [key,value] of Object.entries(map))el.setAttribute(key,value);if(el.tagName==='OPTION'&&originalText.has(el))el.textContent=originalText.get(el)})}
  function state(kind,label){const root=document.querySelector('.sahjony-language');if(!root)return;root.dataset.state=kind;const small=root.querySelector('small');if(small)small.textContent=label||''}
  function applyDirection(locale){document.documentElement.lang=normalizeLocale(locale)||sourceLocale;document.documentElement.dir=direction(locale)}
  async function translateBatch(texts,target){const key=sourceLocale+'>'+target+'|'+texts.join('\u241e');if(cache.has(key))return cache.get(key);const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);try{const response=await fetch(UI_TRANSLATE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts,target_locale:target,source_locale:sourceLocale}),signal:controller.signal});const payload=await response.json().catch(()=>({}));if(!response.ok)throw new Error(payload.detail||'UI translation unavailable');const result=payload.translations||[];if(result.length!==texts.length)throw new Error('UI translation response mismatch');cache.set(key,payload);return payload}finally{clearTimeout(timer)}}
  async function applyLanguage(locale,{persist=true}={}){
    if(busy)return;const target=normalizeLocale(locale)||sourceLocale;
    const currentPath=location.pathname.replace(/\/+$/,'')||'/';
    if((currentPath==='/'||currentPath==='/business')&&baseLocale(target)==='es'){setStored('es');location.assign('/es');return}
    if(currentPath==='/es'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/');return}
    if(currentPath==='/start'&&baseLocale(target)==='es'){setStored('es');location.assign('/es/start');return}
    if((currentPath==='/about'||currentPath==='/about.html')&&baseLocale(target)==='es'){setStored('es');location.assign('/es/about');return}
    if((currentPath==='/trust-center'||currentPath==='/trust-center.html')&&baseLocale(target)==='es'){setStored('es');location.assign('/es/trust-center');return}
    if((currentPath==='/find'||currentPath==='/find.html')&&baseLocale(target)==='es'){setStored('es');location.assign('/es/find');return}
    if(currentPath==='/customer-payments'&&baseLocale(target)==='es'){setStored('es');location.assign('/es/customer-payments');return}
    if(currentPath==='/supplier-commercial-terms'&&baseLocale(target)==='es'){setStored('es');location.assign('/es/supplier-commercial-terms');return}
    if(currentPath==='/suppliers'&&baseLocale(target)==='es'){setStored('es');location.assign('/es/suppliers');return}
    if(currentPath==='/supplier-cuba-terms'&&baseLocale(target)==='es'){setStored('es');location.assign('/es/supplier-cuba-terms');return}
    if(currentPath==='/es/find'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/find.html');return}
    if(currentPath==='/es/customer-payments'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/customer-payments');return}
    if(currentPath==='/es/supplier-commercial-terms'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/supplier-commercial-terms');return}
    if(currentPath==='/es/suppliers'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/suppliers');return}
    if(currentPath==='/es/supplier-cuba-terms'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/supplier-cuba-terms');return}
    if(currentPath==='/es/about'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/about');return}
    if(currentPath==='/es/trust-center'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/trust-center.html');return}
    if(currentPath==='/es/start'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/start');return}
    if(currentPath==='/es'&&baseLocale(target)==='en'){setStored('en-US');location.assign('/');return}
    active=target;if(persist){setStored(target);rewriteUrl(target)}propagateNavigation(target);announceLocale(target);
    if(sameLanguage(target,sourceLocale)){restore();applyDirection(target);state('ok',baseLocale(target)==='en'?'English':'Original');return}
    busy=true;state('busy',baseLocale(target)==='es'?'Traduciendo…':'Translating…');
    try{restore();const items=collect();const chunks=[];let chunk=[],chars=0;for(const item of items){const size=item.text.length;if(chunk.length&&(chunk.length>=20||chars+size>4500)){chunks.push(chunk);chunk=[];chars=0}chunk.push(item);chars+=size}if(chunk.length)chunks.push(chunk);const results=await Promise.all(chunks.map(current=>translateBatch(current.map(item=>item.text),target)));results.forEach((payload,chunkIndex)=>{const current=chunks[chunkIndex];payload.translations.forEach((entry,index)=>{const item=current[index];if(!item)return;const value=entry.text||item.text;if(item.kind==='text')item.node.nodeValue=value;else if(item.kind==='attr')item.el.setAttribute(item.attr,value);else if(item.kind==='option')item.el.textContent=value})});applyDirection(target);state('ok',target);propagateNavigation(target);announceLocale(target)}catch(error){restore();applyDirection(sourceLocale);state('error',baseLocale(target)==='es'?'Traducción no disponible':'Translation unavailable');console.warn('SAHJONY language layer:',error)}finally{busy=false}
  }
  async function geoDefault(){try{const r=await fetch(UI_GEO,{cache:'no-store'});if(!r.ok)return '';const j=await r.json();return normalizeLocale(j.default_locale||'')}catch{return ''}}
  function mountSelector(){
    if(document.querySelector('.sahjony-language'))return;
    const style=document.createElement('style');
    style.textContent='.sahjony-language{position:fixed;right:16px;top:16px;bottom:auto;z-index:2147483000;display:flex;gap:7px;align-items:center;padding:8px 9px;border:1px solid rgba(255,255,255,.16);border-radius:999px;background:rgba(5,14,24,.94);box-shadow:0 12px 40px rgba(0,0,0,.28);backdrop-filter:blur(14px);font:600 12px Inter,system-ui,sans-serif;color:#eef6ff}.sahjony-language select{max-width:190px;background:#0a1b2a;color:#eef6ff;border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:7px 10px;font:inherit}.sahjony-language button{border:0;border-radius:999px;padding:7px 10px;background:#e9f3fb;color:#07111d;font:800 11px Inter,system-ui,sans-serif;cursor:pointer}.sahjony-language small{opacity:.78}.sahjony-language[data-state=error] small{color:#ffb8bd;opacity:1}@media(max-width:600px){.sahjony-language{position:fixed;top:max(10px,env(safe-area-inset-top));right:10px;bottom:auto;left:auto;z-index:2147483000;width:auto;margin:0;justify-content:center;box-shadow:0 10px 30px rgba(0,0,0,.28);padding:6px 7px}.sahjony-language select{max-width:46vw;padding:6px 8px}.sahjony-language small{display:none}.sahjony-language button{padding:6px 8px}}';
    document.head.appendChild(style);
    const root=document.createElement('div');root.className='sahjony-language';root.setAttribute('data-no-translate','true');root.innerHTML='<small>'+(baseLocale(sourceLocale)==='es'?'Idioma':'Language')+'</small><select aria-label="Language"></select><button type="button">'+(baseLocale(sourceLocale)==='es'?'Español':'English')+'</button>';document.body.appendChild(root);
    const select=root.querySelector('select');let displayNames=null;try{displayNames=new Intl.DisplayNames([sourceLocale||navigator.language||'en'],{type:'language'})}catch{}
    for(const locale of LOCALES){const option=document.createElement('option');option.value=locale;let label=locale;try{label=(displayNames?.of(baseLocale(locale))||locale)+' · '+locale}catch{}option.textContent=label;select.appendChild(option)}
    select.addEventListener('change',()=>applyLanguage(select.value,{persist:true}));root.querySelector('button').addEventListener('click',()=>{select.value=sourceLocale;applyLanguage(sourceLocale,{persist:true})});return select;
  }
  async function boot(){
    const select=mountSelector();const requested=requestedLocale();const stored=storedLocale();const nativeSpanish=(location.pathname.replace(/\/+$/,'')||'/').startsWith('/es');const geo=!requested&&!stored&&!nativeSpanish?await geoDefault():'';active=requested||(nativeSpanish?sourceLocale:(stored||geo||sourceLocale));
    if(select){if(!LOCALES.includes(active))LOCALES.push(active);if(!Array.from(select.options).some(option=>option.value===active)){const option=document.createElement('option');option.value=active;option.textContent=active;select.appendChild(option)}select.value=active}
    setStored(active);rewriteUrl(active);propagateNavigation(active);announceLocale(active);await applyLanguage(active,{persist:false});
    const observer=new MutationObserver(records=>{if(!sameLanguage(active,sourceLocale)&&!busy){if(records.every(record=>record.target.closest?.('.sahjony-language')))return;clearTimeout(observerTimer);observerTimer=setTimeout(()=>applyLanguage(active,{persist:false}),350)}});observer.observe(document.body,{childList:true,characterData:true,subtree:true});
    addEventListener('popstate',()=>{const next=requestedLocale()||storedLocale()||active||sourceLocale;active=next;propagateNavigation(next);clearTimeout(observerTimer);observerTimer=setTimeout(()=>applyLanguage(next,{persist:false}),80)});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();

(()=>{
  'use strict';
  const path=(location.pathname||'/').toLowerCase();
  const routes=[
    ['energy',/(energy|fuel|crude|oil|power|solar|battery)/],
    ['logistics',/(shipping|shipment|logistics|freight|import|incoterm)/],
    ['marketplace',/(marketplace|supplier|product|merchandising|order|quote)/],
    ['communications',/(communication|email|telegram|whatsapp|voice|call|chat)/],
    ['finance',/(payment|finance|pricing|revenue|profit|capital)/],
    ['compliance',/(compliance|trust|legal|document|data-control)/],
    ['intelligence',/(ai-brain|intelligence|strategy|lead-search|lead-scout)/],
    ['government',/(government|contracting|public-sector)/],
    ['partners',/(partner|affiliate|introducer)/],
    ['cuba',/(cuba|mipyme)/],
    ['people',/(crm|contact|prospect|customer|consumer|login)/],
    ['manufacturing',/(manufacturer|industrial|factory)/]
  ];
  const sector=(routes.find(([,pattern])=>pattern.test(path))||['global'])[0];
  const routeName=(path.split('/').filter(Boolean).pop()||'').replace(/\.html$/,'');
  const ownerRoute=path.startsWith('/owner/')?`owner-${routeName}`:routeName;
  const pageAliases={'owner-cuba-us-desk':'cuba-us-desk','cuba-consumers':'cuba-individual-consumers'};
  const visualPage=pageAliases[ownerRoute]||ownerRoute;
  document.documentElement.dataset.visualSector=sector;
  if(/cuba|mipyme/.test(visualPage))document.documentElement.dataset.visualPage=visualPage;
  document.documentElement.classList.add('sahjony-ultra-visuals');
  if(!document.querySelector('link[data-sahjony-ultra-visuals]')){
    const stylesheet=document.createElement('link');stylesheet.rel='stylesheet';stylesheet.href='/ultra-visuals.css';stylesheet.dataset.sahjonyUltraVisuals='true';document.head.appendChild(stylesheet);
  }
  function mountVisual(){
    const candidates=['.hero','.command-hero','.module-hero','.postcard','.route-card','.shell','.wrap>main>section:first-child','main>section:first-child','body>main','#root'];
    const target=candidates.map(selector=>document.querySelector(selector)).find(Boolean);
    if(!target||target.querySelector('.heroMedia,.trade-room,.livePanel,[data-native-visual]'))return;
    target.classList.add('sahjony-photo-hero');
    if(!target.querySelector('.sahjony-visual-badge')){
      const badge=document.createElement('span');badge.className='sahjony-visual-badge';badge.setAttribute('aria-hidden','true');badge.setAttribute('data-no-translate','true');badge.textContent=sector==='global'?'GLOBAL VISUAL NETWORK':sector.toUpperCase()+' · VISUAL INTELLIGENCE';target.appendChild(badge);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountVisual,{once:true});else mountVisual();
  setTimeout(mountVisual,0);
})();

(()=>{
  function mountIntentLauncher(){
    if(document.querySelector('.sahjony-intent-launcher'))return;
    const style=document.createElement('style');
    style.textContent='.sahjony-intent-launcher{position:fixed;left:16px;bottom:16px;z-index:2147482999;font:800 12px Inter,system-ui,sans-serif}.sahjony-intent-launcher a{display:flex;align-items:center;gap:8px;padding:11px 14px;border-radius:999px;background:#f4f8fb;color:#07111d;text-decoration:none;box-shadow:0 12px 40px rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.4)}.sahjony-intent-launcher a:hover{transform:translateY(-1px)}@media(max-width:600px){.sahjony-intent-launcher{position:relative;left:auto;bottom:auto;width:calc(100% - 20px);margin:10px auto 0}.sahjony-intent-launcher a{justify-content:center;border-radius:12px}}';
    document.head.appendChild(style);
    const root=document.createElement('div');root.className='sahjony-intent-launcher';root.setAttribute('data-no-translate','true');
    const isEs=(document.documentElement.lang||'').toLowerCase().startsWith('es');
    root.innerHTML='<a href="/actions.html" aria-label="Quick actions">'+(isEs?'¿Qué desea hacer?':'What do you need?')+' <span aria-hidden="true">→</span></a>';
    document.body.appendChild(root);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mountIntentLauncher,{once:true});else mountIntentLauncher();
})();

(()=>{
  function enforceOwnerPrivacy(){
    const path=location.pathname.replace(/\/+$/,'')||'/';
    const ownerArea=path==='/owner-login'||path==='/owner'||path.startsWith('/owner/');
    if(ownerArea){
      let meta=document.querySelector('meta[name="robots"]');
      if(!meta){meta=document.createElement('meta');meta.name='robots';document.head.appendChild(meta)}
      meta.content='noindex,nofollow,noarchive,nosnippet';
      return;
    }
    document.querySelectorAll('a[href]').forEach(a=>{
      try{
        const u=new URL(a.getAttribute('href')||'',location.origin);
        if(u.origin===location.origin&&(u.pathname==='/owner-login'||u.pathname==='/owner'||u.pathname.startsWith('/owner/'))){a.remove()}
      }catch{}
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',enforceOwnerPrivacy,{once:true});else enforceOwnerPrivacy();
})();

(()=>{
  const path=location.pathname.replace(/\/+$/,'');
  if(path!=='/cuba-order'&&path!=='/cuba-order.html')return;
  if(document.querySelector('script[data-cuba-product-transparency]'))return;
  const script=document.createElement('script');
  script.src='/cuba-product-transparency.js';
  script.defer=true;
  script.dataset.cubaProductTransparency='true';
  document.head.appendChild(script);
})();


(()=>{
  function normalizePublicContact(){
    document.querySelectorAll('a[href^="mailto:"]').forEach(a=>{
      const href=(a.getAttribute('href')||'').toLowerCase();
      if(href.includes('sahjonytradingus@gmail.com')||href.includes('info@sahjony.com')){a.setAttribute('href','mailto:ventas@sahjony.com');if((a.textContent||'').includes('@'))a.textContent='ventas@sahjony.com'}
    });
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;
    while((node=walker.nextNode())){
      if(node.parentElement?.closest('script,style,textarea,[data-no-contact-normalize]'))continue;
      node.nodeValue=(node.nodeValue||'').replace(/sahjonytradingus@gmail\.com|info@sahjony\.com/gi,'ventas@sahjony.com');
    }
  }
  function mountPublicFooter(){
    const path=location.pathname.replace(/\/+$/,'')||'/';
    if(path==='/owner-login'||path==='/owner'||path.startsWith('/owner/'))return;
    if(document.querySelector('.sahjony-public-contact-footer'))return;
    const style=document.createElement('style');
    style.textContent='.sahjony-public-contact-footer{border-top:1px solid rgba(255,255,255,.12);margin-top:34px;padding:24px 18px 30px;background:#050b13;color:#dbe7ee;font:600 12px Inter,system-ui,sans-serif}.sahjony-public-contact-footer .inner{max-width:1180px;margin:auto;display:flex;gap:14px;justify-content:space-between;align-items:center;flex-wrap:wrap}.sahjony-public-contact-footer .contact{display:flex;gap:10px;flex-wrap:wrap}.sahjony-public-contact-footer a{color:#dbe7ee;text-decoration:none;border:1px solid rgba(255,255,255,.13);border-radius:999px;padding:8px 11px}.sahjony-public-contact-footer .legal{display:flex;gap:10px;flex-wrap:wrap;color:#92a7b5}@media(max-width:600px){.sahjony-public-contact-footer .inner{display:grid}.sahjony-public-contact-footer .contact,.sahjony-public-contact-footer .legal{display:grid}}';
    document.head.appendChild(style);
    const footer=document.createElement('footer');footer.className='sahjony-public-contact-footer';footer.setAttribute('data-no-translate','true');
    const es=baseLocale(document.documentElement.lang||sourceLocale)==='es';footer.innerHTML='<div class="inner"><div><strong>SAHJONY LLC</strong><br><span>Houston, Texas, USA</span></div><div class="contact"><a href="https://wa.me/12816628581">WhatsApp +1 281-662-8581</a><a href="tel:+17132948801">'+(es?'Teléfono':'Voice')+' +1 713-294-8801</a><a href="mailto:ventas@sahjony.com">ventas@sahjony.com</a></div><div class="legal"><a href="/privacy?lang='+(es?'es':'en-US')+'">'+(es?'Privacidad':'Privacy')+'</a><a href="/terms?lang='+(es?'es':'en-US')+'">'+(es?'Términos':'Terms')+'</a></div></div>';
    document.body.appendChild(footer);
  }
  function bootContact(){normalizePublicContact();mountPublicFooter()}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bootContact,{once:true});else bootContact();
})();
