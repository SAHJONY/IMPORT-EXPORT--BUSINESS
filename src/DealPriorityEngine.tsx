import {useEffect,useMemo,useState} from 'react';

type Profit={status?:string;minUsd?:number;maxUsd?:number;recurringUsd?:number;basis?:string};
type Deal={id:string;title:string;market?:string;stage?:string;priority?:string;confidence?:number;possibleProfit?:Profit;payment?:string;blocker?:string;nextAction?:string;lastActivity?:string};
type Ranked={deal:Deal;probability:number;daysToClose:number;riskFactor:number;economicValue:number;expectedGrossProfit:number;qualityScore:number;ageDays:number;urgency:number;band:'EXECUTE NOW'|'ADVANCE'|'DE-RISK'|'HOLD';reason:string};

const money=(n:number)=>`$${Math.round(n).toLocaleString()}`;
const stageProbability:Record<string,number>={LEAD:.08,QUALIFICATION:.15,SOURCING:.25,FIRM_QUOTE:.45,MARGIN_PROTECTION:.5,BUYER_ACCEPTANCE:.65,CONTRACT_PO:.78,PAYMENT_INSTRUMENT:.86,FULFILLMENT:.93,REVENUE:1,BLOCKED:.08};
const stageDays:Record<string,number>={LEAD:45,QUALIFICATION:35,SOURCING:28,FIRM_QUOTE:21,MARGIN_PROTECTION:18,BUYER_ACCEPTANCE:14,CONTRACT_PO:10,PAYMENT_INSTRUMENT:9,FULFILLMENT:7,REVENUE:1,BLOCKED:45};

function ageDays(value?:string){if(!value)return 999;const t=Date.parse(value);return Number.isFinite(t)?Math.max(0,Math.floor((Date.now()-t)/86400000)):999}
function riskFactor(deal:Deal){const text=`${deal.payment||''} ${deal.blocker||''}`.toLowerCase();if(/100% advance|advance before|deposit/.test(text))return 2;if(/payment mismatch|proof of funds|unverified|kyb/.test(text))return 1.6;if(/l\/c|letter of credit|escrow|against copy of b\/l/.test(text))return 1.2;return 1;}
function economicValue(deal:Deal){const p=deal.possibleProfit||{};if(p.status==='EVIDENCED_ESTIMATE')return Number(p.maxUsd||p.minUsd||0);if(p.status==='UNCONFIRMED_TARGET')return Number(p.maxUsd||p.minUsd||0)*.45;if(p.status==='TARGET_ONLY')return 0;return 0;}
function rank(deal:Deal):Ranked{
 const stage=String(deal.stage||'LEAD');
 const base=stageProbability[stage]??.1;
 const confidence=Math.min(1,Math.max(0,Number(deal.confidence||0)/100));
 const probability=Math.min(.99,base*(.65+.7*confidence));
 const daysToClose=stageDays[stage]??40;
 const risk=riskFactor(deal);
 const econ=economicValue(deal);
 const expected=econ*probability;
 const age=ageDays(deal.lastActivity);
 const urgency=Math.min(2,1+Math.max(0,age-3)/30);
 const qualityScore=econ>0?Math.round((expected/Math.max(1,daysToClose)/risk)*urgency*100)/100:0;
 const band:Ranked['band']=stage==='BLOCKED'||risk>=1.6?'DE-RISK':qualityScore>=20?'EXECUTE NOW':qualityScore>=5?'ADVANCE':'HOLD';
 const reason=band==='EXECUTE NOW'?'Highest quality-adjusted expected gross profit per day; immediate action justified.':band==='ADVANCE'?'Positive economics and maturity justify active follow-up.':band==='DE-RISK'?'Commercial value may exist, but capital/payment/counterparty risk must be reduced first.':'Insufficient evidenced economics or low near-term expected value.';
 return {deal,probability,daysToClose,riskFactor:risk,economicValue:econ,expectedGrossProfit:expected,qualityScore,ageDays:age,urgency,band,reason};
}

export default function DealPriorityEngine(){
 const [rows,setRows]=useState<Ranked[]>([]);const [loading,setLoading]=useState(true);
 useEffect(()=>{void(async()=>{try{const r=await fetch('/canonical-deals.json',{cache:'no-store'});const j=await r.json();const deals=Array.isArray(j.deals)?j.deals:[];setRows(deals.map(rank).sort((a,b)=>b.qualityScore-a.qualityScore))}finally{setLoading(false)}})()},[]);
 const execute=useMemo(()=>rows.filter(r=>r.band==='EXECUTE NOW').length,[rows]);
 const derisk=useMemo(()=>rows.filter(r=>r.band==='DE-RISK').length,[rows]);
 const totalExpected=useMemo(()=>rows.reduce((s,r)=>s+r.expectedGrossProfit,0),[rows]);
 const stale=useMemo(()=>rows.filter(r=>r.ageDays>=7).length,[rows]);
 const houstonNow=new Intl.DateTimeFormat('en-US',{timeZone:'America/Chicago',dateStyle:'medium',timeStyle:'short'}).format(new Date());
 return <main style={s.page}>
  <header style={s.header}><div><div style={s.kicker}>OWNER OS · CAPITAL ALLOCATION</div><h1 style={s.h1}>Quality-adjusted deal priority</h1><p style={s.lead}>Allocate AI research, sourcing and follow-up to opportunities with the strongest expected gross profit per unit of time and risk. Scores are decision aids, not booked revenue.</p><div style={s.clock}>Houston operating time · {houstonNow}</div></div><nav style={s.nav}><a style={s.link} href="/owner/dashboard">Dashboard</a><a style={s.link} href="/owner/economics">Economics</a><a style={s.link} href="/owner/exceptions">Exceptions</a></nav></header>
  <section style={s.metrics}><article style={s.metric}><small>Execute now</small><strong>{execute}</strong></article><article style={s.metric}><small>De-risk first</small><strong>{derisk}</strong></article><article style={s.metric}><small>Probability-adjusted gross profit</small><strong>{money(totalExpected)}</strong></article><article style={s.metric}><small>Stale ≥7 days</small><strong>{stale}</strong></article></section>
  <section style={s.panel}><div style={s.kicker}>CEO WORK QUEUE</div><h2 style={s.h2}>{loading?'Calculating…':'Highest economic value per day first'}</h2><div style={s.tableWrap}><table style={s.table}><thead><tr><th>Rank</th><th>Opportunity</th><th>Decision</th><th>Economic value</th><th>Close probability</th><th>Expected GP</th><th>Age</th><th>Risk</th><th>Urgency</th><th>QAEV score</th><th>Next action</th></tr></thead><tbody>{rows.map((r,i)=><tr key={r.deal.id}><td><b>{i+1}</b></td><td><strong>{r.deal.title}</strong><div style={s.muted}>{r.deal.market||'Market pending'} · {r.deal.stage||'LEAD'}</div></td><td><span style={{...s.pill,...tone(r.band)}}>{r.band}</span><div style={s.muted}>{r.reason}</div></td><td>{money(r.economicValue)}</td><td>{Math.round(r.probability*100)}%</td><td><strong>{money(r.expectedGrossProfit)}</strong></td><td><span style={r.ageDays>=7?s.stale:undefined}>{r.ageDays>=999?'Unknown':`${r.ageDays}d`}</span></td><td>{r.riskFactor.toFixed(1)}×</td><td>{r.urgency.toFixed(2)}×</td><td><strong>{r.qualityScore.toFixed(2)}</strong></td><td>{r.deal.nextAction||'Define next action'}</td></tr>)}</tbody></table></div></section>
  <section style={s.policy}><strong>Formula:</strong> quality-adjusted expected value = economic value × estimated close probability ÷ expected days to close ÷ risk factor × aging urgency. Only governed deal data is used. Missing economics score zero until supported inputs exist.</section>
 </main>
}
function tone(band:Ranked['band']){if(band==='EXECUTE NOW')return s.good;if(band==='ADVANCE')return s.info;if(band==='DE-RISK')return s.warn;return s.neutral}
const s:Record<string,any>={page:{minHeight:'100vh',background:'#03070c',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:28},header:{maxWidth:1500,margin:'0 auto',display:'flex',justifyContent:'space-between',gap:24,alignItems:'end',padding:'28px 0 36px',borderBottom:'1px solid rgba(255,255,255,.08)'},kicker:{fontSize:10,fontWeight:950,letterSpacing:'.17em',color:'#66dcff'},h1:{fontSize:'clamp(42px,6vw,78px)',letterSpacing:'-.055em',lineHeight:.95,margin:'12px 0'},lead:{maxWidth:850,color:'#8fa4b5',lineHeight:1.6},clock:{marginTop:10,color:'#66dcff',fontSize:11,fontWeight:800},nav:{display:'flex',gap:10,flexWrap:'wrap'},link:{color:'#d7e6ee',textDecoration:'none',padding:'10px 13px',border:'1px solid rgba(255,255,255,.1)',borderRadius:999,fontSize:12},metrics:{maxWidth:1500,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:12},metric:{padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:16,background:'#09131d'},panel:{maxWidth:1500,margin:'16px auto',padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'#07111a'},h2:{margin:'8px 0 18px',fontSize:28},tableWrap:{overflow:'auto'},table:{width:'100%',minWidth:1500,borderCollapse:'collapse'},muted:{fontSize:11,color:'#7f95a6',lineHeight:1.45,marginTop:5},pill:{display:'inline-block',padding:'5px 8px',borderRadius:999,fontSize:10,fontWeight:900,marginBottom:4},good:{background:'rgba(54,211,153,.12)',color:'#69efaa'},info:{background:'rgba(102,220,255,.12)',color:'#77e3ff'},warn:{background:'rgba(255,180,84,.12)',color:'#ffbd6d'},neutral:{background:'rgba(255,255,255,.06)',color:'#b5c4ce'},stale:{color:'#ffbd6d',fontWeight:900},policy:{maxWidth:1500,margin:'16px auto',padding:16,borderLeft:'3px solid #66dcff',background:'rgba(102,220,255,.055)',color:'#9fb3c2',fontSize:12,lineHeight:1.6}};
