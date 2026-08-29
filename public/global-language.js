(()=>{
  'use strict';

  const STORAGE='sahjony.locale';
  const QUERY='lang';
  const UI_TRANSLATE='/ui-language/translate-batch';
  const UI_GEO='/ui-language/geo';
  const RTL=new Set(['ar','fa','he','ur','ps','sd','ug','yi']);
  const LOCALES=['en-US','es','fr','pt-BR','de','it','nl','pl','ru','uk','tr','ar','he','fa','ur','hi','bn','zh-Hans','zh-Hant','ja','ko','vi','th','id','ms','fil','sw','am','ha','yo','ig','zu','af','el','cs','ro','hu','sv','no','da','fi'];
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
  async function translateBatch(texts,target){const key=sourceLocale+'>'+target+'|'+texts.join('\u241e');if(cache.has(key))return cache.get(key);const response=await fetch(UI_TRANSLATE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts,target_locale:target,source_locale:sourceLocale})});const payload=await response.json().catch(()=>({}));if(!response.ok)throw new Error(payload.detail||'UI translation unavailable');const result=payload.translations||[];if(result.length!==texts.length)throw new Error('UI translation response mismatch');cache.set(key,payload);return payload}
  async function applyLanguage(locale,{persist=true}={}){
    if(busy)return;const target=normalizeLocale(locale)||sourceLocale;active=target;if(persist){setStored(target);rewriteUrl(target)}propagateLinks(target);
    if(sameLanguage(target,sourceLocale)){restore();applyDirection(target);state('ok',baseLocale(target)==='en'?'English':'Original');return}
    busy=true;state('busy',baseLocale(target)==='es'?'Traduciendo…':'Translating…');
    try{restore();const items=collect();for(let offset=0;offset<items.length;offset+=50){const chunk=items.slice(offset,offset+50);const payload=await translateBatch(chunk.map(item=>item.text),target);payload.translations.forEach((entry,index)=>{const item=chunk[index];if(!item)return;const value=entry.text||item.text;if(item.kind==='text')item.node.nodeValue=value;else if(item.kind==='attr')item.el.setAttribute(item.attr,value);else if(item.kind==='option')item.el.textContent=value})}applyDirection(target);state('ok',target);propagateLinks(target)}catch(error){restore();applyDirection(sourceLocale);state('error','Original');console.warn('SAHJONY language layer:',error)}finally{busy=false}
  }
  async function geoDefault(){try{const r=await fetch(UI_GEO,{cache:'no-store'});if(!r.ok)return '';const j=await r.json();return normalizeLocale(j.default_locale||'')}catch{return ''}}
  function mountSelector(){
    if(document.querySelector('.sahjony-language'))return;
    const style=document.createElement('style');
    style.textContent='.sahjony-language{position:fixed;right:16px;bottom:16px;z-index:2147483000;display:flex;gap:7px;align-items:center;padding:8px 9px;border:1px solid rgba(255,255,255,.16);border-radius:999px;background:rgba(5,14,24,.94);box-shadow:0 12px 40px rgba(0,0,0,.28);backdrop-filter:blur(14px);font:600 12px Inter,system-ui,sans-serif;color:#eef6ff}.sahjony-language select{max-width:190px;background:#0a1b2a;color:#eef6ff;border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:7px 10px;font:inherit}.sahjony-language button{border:0;border-radius:999px;padding:7px 10px;background:#e9f3fb;color:#07111d;font:800 11px Inter,system-ui,sans-serif;cursor:pointer}.sahjony-language small{opacity:.78}.sahjony-language[data-state=error] small{color:#ffb8bd;opacity:1}@media(max-width:600px){.sahjony-language{position:relative;left:auto;right:auto;bottom:auto;z-index:20;width:calc(100% - 20px);margin:14px auto max(14px,env(safe-area-inset-bottom));justify-content:center;box-shadow:none}.sahjony-language select{max-width:55vw}}';
    document.head.appendChild(style);
    const root=document.createElement('div');root.className='sahjony-language';root.setAttribute('data-no-translate','true');root.innerHTML='<small>Language</small><select aria-label="Language"></select><button type="button">Original</button>';document.body.appendChild(root);
    const select=root.querySelector('select');let displayNames=null;try{displayNames=new Intl.DisplayNames([navigator.language||'en'],{type:'language'})}catch{}
    for(const locale of LOCALES){const option=document.createElement('option');option.value=locale;let label=locale;try{label=(displayNames?.of(baseLocale(locale))||locale)+' · '+locale}catch{}option.textContent=label;select.appendChild(option)}
    select.addEventListener('change',()=>applyLanguage(select.value,{persist:true}));root.querySelector('button').addEventListener('click',()=>{select.value=sourceLocale;applyLanguage(sourceLocale,{persist:true})});return select;
  }
  async function boot(){
    const select=mountSelector();const requested=requestedLocale();const stored=storedLocale();const geo=!requested&&!stored?await geoDefault():'';active=requested||stored||geo||sourceLocale;
    if(select){if(!LOCALES.includes(active))LOCALES.push(active);if(!Array.from(select.options).some(option=>option.value===active)){const option=document.createElement('option');option.value=active;option.textContent=active;select.appendChild(option)}select.value=active}
    setStored(active);rewriteUrl(active);propagateLinks(active);await applyLanguage(active,{persist:false});
    const observer=new MutationObserver(records=>{if(!sameLanguage(active,sourceLocale)&&!busy){if(records.every(record=>record.target.closest?.('.sahjony-language')))return;clearTimeout(observerTimer);observerTimer=setTimeout(()=>applyLanguage(active,{persist:false}),350)}});observer.observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
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
