(()=>{
  const STORAGE='sahjony.locale';
  const defaultLocale=document.documentElement.lang||'en-US';
  const explicitLocale=localStorage.getItem(STORAGE);
  let active=explicitLocale||defaultLocale;
  let busy=false;
  let cubaAuto=false;
  const skipTags=new Set(['SCRIPT','STYLE','NOSCRIPT','CODE','PRE','TEXTAREA','INPUT','OPTION']);
  const cache=new Map();

  const css=`.sahjony-language{position:fixed;right:18px;bottom:18px;z-index:2147483000;display:flex;gap:8px;align-items:center;padding:8px 10px;border:1px solid rgba(255,255,255,.16);border-radius:999px;background:rgba(5,14,24,.94);box-shadow:0 12px 40px rgba(0,0,0,.28);backdrop-filter:blur(14px);font:600 12px Inter,system-ui,sans-serif;color:#eef6ff}.sahjony-language select{max-width:180px;background:#0a1b2a;color:#eef6ff;border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:7px 10px;font:inherit}.sahjony-language button{border:0;border-radius:999px;padding:7px 10px;background:#e9f3fb;color:#07111d;font:800 11px Inter,system-ui,sans-serif;cursor:pointer}.sahjony-language small{opacity:.66}.sahjony-language[data-state=error] small{color:#ffb8bd;opacity:1}@media(max-width:600px){.sahjony-language{left:12px;right:12px;bottom:12px;justify-content:center}.sahjony-language select{max-width:54vw}}`;
  const style=document.createElement('style');style.textContent=css;document.head.appendChild(style);

  function textNodes(root=document.body){
    const out=[];const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode(node){
      const p=node.parentElement;if(!p||skipTags.has(p.tagName)||p.closest('[data-no-translate],.sahjony-language'))return NodeFilter.FILTER_REJECT;
      const t=node.nodeValue?.trim();if(!t||t.length<2||/^[-+–—•·|/\\\s\d.,:$%()]+$/.test(t))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }});let n;while((n=walker.nextNode()))out.push(n);return out;
  }
  function remember(nodes){nodes.forEach(n=>{if(!n.parentElement?.dataset.originalText)n.parentElement.dataset.originalText=n.nodeValue||''});}
  function restore(){document.querySelectorAll('[data-original-text]').forEach(el=>{el.textContent=el.dataset.originalText||'';delete el.dataset.originalText});document.documentElement.lang=defaultLocale;document.documentElement.dir='ltr';}
  function setState(state,msg){const w=document.querySelector('.sahjony-language');if(!w)return;w.dataset.state=state;const s=w.querySelector('small');if(s)s.textContent=msg||'';}
  async function geoDefault(){
    try{const r=await fetch('/cuba-language/geo',{cache:'no-store'});if(!r.ok)return null;const j=await r.json();cubaAuto=j.country==='CU'&&j.auto_translate===true;return j;}catch{return null;}
  }
  async function locales(){
    try{const r=await fetch('/language/locales',{cache:'no-store'});if(!r.ok)throw 0;const j=await r.json();return j.locales||[];}catch{return ['en-US','es','fr','pt-BR','de','it','nl','pl','ru','uk','tr','ar','he','fa','ur','hi','bn','zh-Hans','zh-Hant','ja','ko','vi','th','id','ms','fil','sw','am','ha','yo','ig','zu','af','el','cs','ro','hu','sv','no','da','fi'];}
  }
  async function translate(locale,{persist=true}={}){
    if(busy)return;active=locale;if(persist)localStorage.setItem(STORAGE,locale);
    if(locale===defaultLocale){restore();setState('ok','Original');return;}
    busy=true;setState('busy',cubaAuto&&locale.toLowerCase().startsWith('es')?'Traduciendo al español…':'Translating…');
    try{
      restore();const nodes=textNodes();remember(nodes);
      const chunks=[];for(let i=0;i<nodes.length;i+=55)chunks.push(nodes.slice(i,i+55));
      for(const chunk of chunks){
        const texts=chunk.map(n=>(n.nodeValue||'').trim());const key=(cubaAuto?'CU|':'')+locale+'|'+texts.join('\u241e');let result=cache.get(key);
        if(!result){
          const cubaSpanish=cubaAuto&&locale.toLowerCase().split('-')[0]==='es';
          const endpoint=cubaSpanish?'/cuba-language/translate-batch':'/language/ui-translate-batch';
          const body=cubaSpanish?{texts,target_locale:'es'}:{texts,target_locale:locale,source_type:'ui'};
          const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
          const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'Translation unavailable');result=j;cache.set(key,result);
        }
        (result.translations||[]).forEach((x,i)=>{if(chunk[i])chunk[i].nodeValue=(chunk[i].nodeValue||'').replace(texts[i],x.text||texts[i]);});
        if(result.direction)document.documentElement.dir=result.direction;
      }
      document.documentElement.lang=locale;setState('ok',cubaAuto&&locale.toLowerCase().startsWith('es')?'Español · Cuba':locale);
    }catch(e){restore();setState('error','Translation unavailable');console.warn('SAHJONY language layer:',e);}
    finally{busy=false;}
  }
  async function mount(){
    const wrap=document.createElement('div');wrap.className='sahjony-language';wrap.setAttribute('data-no-translate','true');wrap.innerHTML='<small>Language</small><select aria-label="Language"></select><button type="button">Original</button>';
    document.body.appendChild(wrap);const select=wrap.querySelector('select');
    const geo=await geoDefault();if(!explicitLocale&&geo?.locale)active=geo.locale;
    const list=await locales();
    const names=new Intl.DisplayNames([navigator.language||'en'],{type:'language'});
    for(const loc of list){const o=document.createElement('option');o.value=loc;const base=loc.split('-')[0];let label=loc;try{label=names.of(base)||loc}catch{}o.textContent=label+' · '+loc;select.appendChild(o)}
    if(!list.includes(active))active=defaultLocale;select.value=active;
    select.addEventListener('change',()=>translate(select.value,{persist:true}));wrap.querySelector('button').addEventListener('click',()=>{select.value=defaultLocale;translate(defaultLocale,{persist:true})});
    if(active!==defaultLocale)translate(active,{persist:Boolean(explicitLocale)});else setState('ok','Original');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);else mount();
})();
