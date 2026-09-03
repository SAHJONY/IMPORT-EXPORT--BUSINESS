import {useEffect,useMemo,useState} from 'react';

type PossibleProfit={status?:string;minUsd?:number;maxUsd?:number;ratePct?:number;period?:string;basis?:string;recurringUsd?:number;recurringPeriod?:string};
type Deal={id:string;title:string;market?:string;stage?:string;priority?:string;confidence?:number;economics?:string;possibleProfit?:PossibleProfit;payment?:string;blocker?:string;nextAction?:string;lastActivity?:string};

type EconomicsRow={deal:Deal;status:'EVIDENCED'|'TARGET'|'INPUTS REQUIRED';min?:number;max?:number;recurring?:number;score:number;capitalRisk:'LOW'|'MEDIUM'|'HIGH'|'UNKNOWN';reason:string};

const money=(n?:number)=>Number.isFinite(n)?`$${Number(n).toLocaleString(undefined,{maximumFractionDigits:0})}`:'—';
const daysOld=(value?:string)=>{if(!value)return 999;const t=Date.parse(value);return Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/86400000)):999};

function riskFrom(deal:Deal):EconomicsRow['capitalRisk']{
  const text=`${deal.payment||''} ${deal.blocker||''}`.toLowerCase();
  if(/100% advance|advance before|deposit/.test(text))return 'HIGH';
  if(/l\/c|letter of credit|escrow|against copy of b\/l/.test(text))return 'MEDIUM';
  if(!text.trim())return 'UNKNOWN';
  return 'LOW';
}
function normalize(deal:Deal):EconomicsRow{
  const p=deal.possibleProfit||{};
  const evidenced=p.status==='EVIDENCED_ESTIMATE';
  const target=['UNCONFIRMED_TARGET','TARGET_ONLY'].includes(String(p.status));
  const status:EcononomicsStatus=evidenced?'EVIDENCED':target?'TARGET':'INPUTS REQUIRED';
  const high=Number.isFinite(Number(p.maxUsd))?Number(p.maxUsd):Number.isFinite(Number(p.minUsd))?Number(p.minUsd):undefined;
  const low=Number.isFinite(Number(p.minUsd))?Number(p.minUsd):high;
  const confidence=Number(deal.confidence||0);
  const freshness=Math.max(0,30-daysOld(deal.lastActivity));
  const stageWeight=/REVENUE|FULFILLMENT|PAYMENT|CONTRACT|BUYER_ACCEPTANCE|FIRM_QUOTE/.test(String(deal.stage))?25:/SOURCING|QUALIFICATION/.test(String(deal.stage))?10:0;
  const evidenceWeight=evidenced?30:target?10:0;
  const economicWeight=high?Math.min(25,Math.log10(Math.max(high,1))*5):0;
  const score=Math.round(confidence*.25+freshness*.25+stageWeight+evidenceWeight+economicWeight);
  const reason=evidenced?'Supplier/buyer economics are evidenced, but this remains projected until completed and collected.':target?'Commercial target exists but one or more pricing/protection inputs are unconfirmed.':'Supplier cost, buyer price, protected compensation or other required economics are missing.';
  return {deal,status,min:low,max:high,recurring:Number.isFinite(Number(p.recurringUsd))?Number(p.recurringUsd):undefined,score,capitalRisk:riskFrom(deal),reason};
}
type EcononomicsStatus=EconomicsRow['status'];

export default function DealEconomicsCenter(){
  const [rows,setRows]=useState<EconomicsRow[]>([]);const [loading,setLoading]=useState(true);
  useEffect(()=>{void (async()=>{try{const r=await fetch('/canonical-deals.json',{cache:'no-store'});const j=await r.json() as {deals?:Deal[]};const deals:Deal[]=Array.isArray(j.deals)?j.deals:[];setRows(deals.map(normalize).sort((a:EconomicsRow,b:EconomicsRow)=>b.score-a.score))}finally{setLoading(false)}})()},[]);
  const evidenced=useMemo(()=>rows.filter(r=>r.status==='EVIDENCED'),[rows]);
  const projected=useMemo(()=>evidenced.reduce((sum,r)=>sum+(r.max||0),0),[evidenced]);
  const recurring=useMemo(()=>evidenced.reduce((sum,r)=>sum+(r.recurring||0),0),[evidenced]);
  const highRisk=useMemo(()=>rows.filter(r=>r.capitalRisk==='HIGH').length,[rows]);
  return <main style={s.page}>
    <header style={s.header}><div><div style={s.kicker}>OWNER OS · ECONOMICS</div><h1 style={s.h1}>Deal economics & capital risk</h1><p style={s.lead}>Rank opportunities by evidenced economics, commercial maturity and capital exposure. Projected profit is never booked revenue.</p></div><nav style={s.nav}><a style={s.link} href="/owner/dashboard">Dashboard</a><a style={s.link} href="/owner/deals">Deals</a><a style={s.link} href="/owner/exceptions">Exceptions</a></nav></header>
    <section style={s.metrics}>
      <article style={s.metric}><small>Evidenced economics</small><strong>{evidenced.length}</strong></article>
      <article style={s.metric}><small>Projected profit · evidenced deals</small><strong>{money(projected)}</strong></article>
      <article style={s.metric}><small>Recurring target · evidenced basis</small><strong>{money(recurring)}</strong></article>
      <article style={s.metric}><small>High capital-risk deals</small><strong>{highRisk}</strong></article>
    </section>
    <section style={s.panel}><div style={s.panelHead}><div><div style={s.kicker}>PROFITABILITY RANKING</div><h2 style={s.h2}>{loading?'Loading governed economics…':'Highest-value bottlenecks first'}</h2></div></div>
      <div style={s.tableWrap}><table style={s.table}><thead><tr><th>Rank</th><th>Opportunity</th><th>Stage</th><th>Economics status</th><th>Possible profit</th><th>Recurring</th><th>Capital risk</th><th>Score</th><th>Next action</th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.deal.id}><td>{i+1}</td><td><strong>{r.deal.title}</strong><div style={s.muted}>{r.deal.market||'Market pending'}</div></td><td>{r.deal.stage||'—'}</td><td><span style={{...s.pill,...(r.status==='EVIDENCED'?s.good:r.status==='TARGET'?s.warn:s.bad)}}>{r.status}</span><div style={s.muted}>{r.reason}</div></td><td><strong>{r.min&&r.max&&r.min!==r.max?`${money(r.min)}–${money(r.max)}`:money(r.max)}</strong><div style={s.muted}>{r.deal.possibleProfit?.basis||'Inputs incomplete'}</div></td><td>{money(r.recurring)}</td><td><span style={{...s.pill,...(r.capitalRisk==='HIGH'?s.bad:r.capitalRisk==='MEDIUM'?s.warn:s.neutral)}}>{r.capitalRisk}</span></td><td><strong>{r.score}</strong></td><td>{r.deal.nextAction||'Define next action'}</td></tr>)}</tbody></table></div>
    </section>
    <section style={s.policy}><strong>Governance:</strong> Only <b>EVIDENCED_ESTIMATE</b> economics contribute to the evidenced projected-profit total. Targets and incomplete records remain visible but are excluded from that total. Collected gross profit must come from completed transaction evidence, not forecasts.</section>
  </main>
}

const s:Record<string,any>={page:{minHeight:'100vh',background:'#04080e',color:'#f3f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'28px'},header:{maxWidth:1500,margin:'0 auto',display:'flex',justifyContent:'space-between',gap:24,alignItems:'end',padding:'26px 0 34px',borderBottom:'1px solid rgba(255,255,255,.08)'},kicker:{fontSize:10,fontWeight:950,letterSpacing:'.17em',color:'#66dcff'},h1:{fontSize:'clamp(42px,6vw,78px)',letterSpacing:'-.055em',lineHeight:.95,margin:'12px 0'},lead:{maxWidth:800,color:'#8fa4b5',lineHeight:1.6},nav:{display:'flex',gap:10,flexWrap:'wrap'},link:{color:'#d7e6ee',textDecoration:'none',padding:'10px 13px',border:'1px solid rgba(255,255,255,.1)',borderRadius:999,fontSize:12},metrics:{maxWidth:1500,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:12},metric:{padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:16,background:'#09131d'},panel:{maxWidth:1500,margin:'16px auto',padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'#07111a'},panelHead:{display:'flex',justifyContent:'space-between'},h2:{margin:'8px 0 18px',fontSize:28},tableWrap:{overflow:'auto'},table:{width:'100%',minWidth:1350,borderCollapse:'collapse'},muted:{fontSize:11,color:'#7f95a6',lineHeight:1.45,marginTop:5},pill:{display:'inline-block',padding:'5px 8px',borderRadius:999,fontSize:10,fontWeight:900,marginBottom:4},good:{background:'rgba(54,211,153,.12)',color:'#69efaa'},warn:{background:'rgba(255,180,84,.12)',color:'#ffbd6d'},bad:{background:'rgba(255,104,104,.12)',color:'#ff8d8d'},neutral:{background:'rgba(255,255,255,.06)',color:'#b5c4ce'},policy:{maxWidth:1500,margin:'16px auto',padding:16,borderLeft:'3px solid #66dcff',background:'rgba(102,220,255,.055)',color:'#9fb3c2',fontSize:12,lineHeight:1.6}};
