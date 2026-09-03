import {useEffect,useMemo,useState} from 'react';

type Deal={
  id?:string; title?:string; market?:string; stage?:string; priority?:string; buyer?:string; supplier?:string;
  blocker?:string; nextAction?:string; lastActivity?:string; confidence?:number; payment?:string; economics?:string;
  possibleProfit?:{status?:string;minUsd?:number;maxUsd?:number;basis?:string}; source?:string;
};

type Exception={
  id:string; severity:'CRITICAL'|'HIGH'|'MEDIUM'; category:string; title:string; detail:string; action:string; deal:Deal;
};

function daysSince(value?:string){
  if(!value)return null;
  const t=Date.parse(value); if(!Number.isFinite(t))return null;
  return Math.max(0,Math.floor((Date.now()-t)/86400000));
}

function derive(deal:Deal,index:number):Exception[]{
  const out:Exception[]=[];
  const stage=String(deal.stage||'').toUpperCase();
  const blocker=String(deal.blocker||'').trim();
  const next=String(deal.nextAction||'').trim();
  const age=daysSince(deal.lastActivity);
  const base=String(deal.id||`deal-${index}`);
  const add=(severity:Exception['severity'],category:string,title:string,detail:string,action:string)=>out.push({id:`${base}-${category}`,severity,category,title,detail,action,deal});

  if(stage==='BLOCKED'||(blocker&&blocker.toLowerCase()!=='none'&&blocker.toLowerCase()!=='n/a'))
    add('CRITICAL','BLOCKER',deal.title||'Blocked deal',blocker||'Deal is marked blocked.',next||'Resolve blocker and assign an accountable owner.');

  if(['LEAD','QUALIFICATION'].includes(stage))
    add('HIGH','RFQ_COMPLETENESS',deal.title||'Incomplete RFQ','Demand is not yet transaction-ready. Confirm product/specification, quantity, destination, commercial format and required shipment date.',next||'Complete buyer qualification before supplier escalation.');

  if(stage==='SOURCING')
    add('HIGH','SUPPLIER_PRICE',deal.title||'Supplier pricing required','Qualified demand is waiting for firm supplier economics.',next||'Obtain a firm supplier price, validity window, MOQ/capacity and payment terms.');

  if(stage==='FIRM_QUOTE'&&!String(deal.economics||'').trim())
    add('CRITICAL','ECONOMICS',deal.title||'Economics missing','A firm quote stage cannot proceed safely without evidenced economics.',next||'Verify landed cost and protect SAHJONY compensation before buyer release.');

  if(['MARGIN_PROTECTION','FIRM_QUOTE'].includes(stage)&&deal.possibleProfit?.status==='INPUTS_REQUIRED')
    add('HIGH','MARGIN',deal.title||'Margin inputs missing',deal.possibleProfit?.basis||'Supplier cost, buyer price or SAHJONY compensation is incomplete.',next||'Complete deal economics and margin protection.');

  if(stage==='BUYER_ACCEPTANCE')
    add('MEDIUM','BUYER_RESPONSE',deal.title||'Buyer response pending','Commercial offer is awaiting buyer acceptance or negotiation.',next||'Follow up with a specific decision deadline and document objections.');

  if(stage==='CONTRACT_PO')
    add('HIGH','PO_CONTRACT',deal.title||'PO / contract pending','Commercial alignment has not yet become documented buyer commitment.',next||'Secure purchase order or executed contract before fulfillment exposure.');

  if(stage==='PAYMENT_INSTRUMENT')
    add('CRITICAL','PAYMENT',deal.title||'Payment instrument pending',deal.payment||'Payment protection is not complete.',next||'Validate payment instrument before supplier commitment or shipment.');

  if(stage==='FULFILLMENT'&&blocker)
    add('CRITICAL','LOGISTICS',deal.title||'Fulfillment exception',blocker,next||'Resolve logistics/documentation exception immediately.');

  if(age!==null&&age>=7&&!['REVENUE'].includes(stage))
    add(age>=14?'HIGH':'MEDIUM','STALE',deal.title||'Stale opportunity',`No recorded activity for ${age} days.`,next||'Advance, re-qualify, or close the opportunity.');

  return out;
}

const rank={CRITICAL:0,HIGH:1,MEDIUM:2};
const tone={CRITICAL:'#ff7a8a',HIGH:'#ffbc6e',MEDIUM:'#7edcff'};

export default function ExecutiveExceptionEngine(){
  const [deals,setDeals]=useState<Deal[]>([]); const [loading,setLoading]=useState(true); const [error,setError]=useState('');
  async function refresh(){
    setLoading(true);setError('');
    try{
      const r=await fetch('/canonical-deals.json',{cache:'no-store'}); if(!r.ok)throw new Error(`HTTP ${r.status}`);
      const body=await r.json(); setDeals(Array.isArray(body.deals)?body.deals:[]);
    }catch(e){setError(e instanceof Error?e.message:'Unable to load deals');setDeals([])}finally{setLoading(false)}
  }
  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(id)},[]);
  const exceptions=useMemo(()=>deals.flatMap(derive).sort((a,b)=>rank[a.severity]-rank[b.severity]),[deals]);
  const counts=useMemo(()=>({critical:exceptions.filter(x=>x.severity==='CRITICAL').length,high:exceptions.filter(x=>x.severity==='HIGH').length,medium:exceptions.filter(x=>x.severity==='MEDIUM').length}),[exceptions]);
  return <main style={s.page}>
    <header style={s.header}><a href="/owner/dashboard" style={s.brand}>SAHJONY <span style={{color:'#70ddff'}}>OWNER OS</span></a><nav style={s.nav}><a href="/owner/dashboard" style={s.link}>Command Center</a><a href="/owner/deals" style={s.link}>Deals</a><a href="/owner/intelligence" style={s.link}>Intelligence</a><button style={s.button} onClick={()=>void refresh()}>{loading?'Checking…':'Refresh'}</button></nav></header>
    <section style={s.hero}><div><div style={s.eyebrow}>EXECUTIVE EXCEPTION ENGINE</div><h1 style={s.h1}>Run the company by <span style={{color:'#70ddff'}}>exceptions, not noise.</span></h1><p style={s.lead}>Only conditions that can delay a quote, destroy margin, increase capital exposure or prevent collection are escalated here.</p></div></section>
    <section style={s.metrics}><Metric label="Critical" value={counts.critical} color={tone.CRITICAL}/><Metric label="High" value={counts.high} color={tone.HIGH}/><Metric label="Medium" value={counts.medium} color={tone.MEDIUM}/><Metric label="Deals scanned" value={deals.length} color="#b5c5d2"/></section>
    {error&&<div style={s.alert}>Exception source unavailable: {error}. No synthetic exceptions are displayed.</div>}
    <section style={s.panel}><div style={s.panelHead}><div><div style={s.eyebrow}>ACTION QUEUE</div><h2 style={s.h2}>{exceptions.length?`${exceptions.length} exception${exceptions.length===1?'':'s'} requiring attention`:'No derived exceptions'}</h2></div><a href="/owner/deals" style={s.action}>Open deal desk →</a></div>
      <div style={s.list}>{exceptions.map(ex=><article key={ex.id} style={s.row}><div style={{...s.badge,color:tone[ex.severity],borderColor:`${tone[ex.severity]}55`}}>{ex.severity}</div><div><div style={s.category}>{ex.category.replaceAll('_',' ')}</div><h3 style={s.h3}>{ex.title}</h3><p style={s.detail}>{ex.detail}</p><div style={s.next}><strong>Next action:</strong> {ex.action}</div><div style={s.meta}>{[ex.deal.stage,ex.deal.market,ex.deal.priority?`Priority ${ex.deal.priority}`:'',ex.deal.buyer].filter(Boolean).join(' · ')}</div></div></article>)}</div>
      {!loading&&!error&&!exceptions.length&&<div style={s.empty}>No commercial exceptions were derived from the current canonical deal file.</div>}
    </section>
    <footer style={s.footer}>Escalation policy: protect cash, margin, counterparty quality and execution speed. Revenue is recognized only when economically and operationally evidenced.</footer>
  </main>
}

function Metric({label,value,color}:{label:string;value:number;color:string}){return <article style={s.metric}><small style={s.metricLabel}>{label}</small><strong style={{...s.metricValue,color}}>{value}</strong></article>}

const s:Record<string,any>={
 page:{minHeight:'100vh',background:'radial-gradient(circle at 18% -10%,#112f44 0,#07111d 32%,#03070c 72%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 24px 50px'},
 header:{maxWidth:1320,margin:'0 auto',minHeight:74,display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',gap:18,flexWrap:'wrap'},brand:{fontWeight:950,letterSpacing:'.08em',fontSize:13,color:'#fff',textDecoration:'none'},nav:{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'},link:{color:'#a9bbc8',textDecoration:'none',fontSize:13,padding:'9px 10px'},button:{background:'#70ddff',color:'#021018',border:0,borderRadius:10,padding:'10px 13px',fontWeight:900,cursor:'pointer'},
 hero:{maxWidth:1320,margin:'0 auto',padding:'62px 0 34px'},eyebrow:{fontSize:10,fontWeight:950,letterSpacing:'.17em',color:'#70ddff',marginBottom:13},h1:{fontSize:'clamp(44px,6vw,82px)',lineHeight:.95,letterSpacing:'-.055em',maxWidth:1000,margin:'0 0 18px'},lead:{maxWidth:850,color:'#94a9b8',fontSize:16,lineHeight:1.65,margin:0},
 metrics:{maxWidth:1320,margin:'0 auto 16px',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(170px,1fr))',gap:12},metric:{background:'rgba(8,17,27,.78)',border:'1px solid rgba(255,255,255,.08)',borderRadius:16,padding:18},metricLabel:{fontSize:9,textTransform:'uppercase',letterSpacing:'.14em',color:'#778d9e',fontWeight:900},metricValue:{display:'block',fontSize:38,marginTop:6,letterSpacing:'-.04em'},
 alert:{maxWidth:1320,margin:'0 auto 14px',border:'1px solid rgba(255,188,110,.25)',background:'rgba(255,188,110,.06)',color:'#e6bd88',borderRadius:12,padding:13,fontSize:12},panel:{maxWidth:1320,margin:'0 auto',border:'1px solid rgba(255,255,255,.09)',borderRadius:20,background:'rgba(5,13,22,.86)',padding:22},panelHead:{display:'flex',justifyContent:'space-between',gap:18,alignItems:'start'},h2:{fontSize:29,letterSpacing:'-.035em',margin:'0 0 18px'},action:{color:'#70ddff',textDecoration:'none',fontWeight:850,fontSize:13},list:{display:'grid',gap:9},row:{display:'grid',gridTemplateColumns:'95px minmax(0,1fr)',gap:17,padding:'17px 0',borderTop:'1px solid rgba(255,255,255,.065)'},badge:{justifySelf:'start',height:27,padding:'6px 8px',border:'1px solid',borderRadius:999,fontSize:9,fontWeight:950,letterSpacing:'.11em'},category:{fontSize:9,letterSpacing:'.14em',fontWeight:900,color:'#6f8799'},h3:{fontSize:19,margin:'5px 0 7px'},detail:{margin:0,color:'#9bb0bf',fontSize:13,lineHeight:1.55},next:{marginTop:10,color:'#dce8ee',fontSize:13},meta:{marginTop:8,color:'#687f91',fontSize:11},empty:{padding:'42px 20px',textAlign:'center',color:'#8198aa'},footer:{maxWidth:1320,margin:'28px auto 0',paddingTop:17,borderTop:'1px solid rgba(255,255,255,.07)',color:'#61798b',fontSize:11,letterSpacing:'.04em'}
};
