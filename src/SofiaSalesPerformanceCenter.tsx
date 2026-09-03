import {useEffect,useMemo,useState} from 'react';
import {supabase,supabaseConfigured} from './supabase';

type Rfq={
  id:string;
  source:string;
  product?:string;
  company_name?:string;
  buyer_name?:string;
  stage:string;
  qualification_status:string;
  completeness_score:number;
  next_action?:string;
  created_at?:string;
  updated_at:string;
};

type Segment='Edible Oils'|'Food & Beverage'|'Construction'|'Energy'|'Industrial'|'Other';
type SegmentMetrics={name:Segment;total:number;qualified:number;complete:number;quoted:number;po:number;rfqRate:number;quoteRate:number;poRate:number;avgCompleteness:number};

const stageRank:Record<string,number>={
  CONVERSATION:0,
  QUALIFIED_DEMAND:1,
  RFQ_COMPLETE:2,
  SUPPLIER_PRICING:3,
  FORMAL_QUOTE:4,
  NEGOTIATION:5,
  PURCHASE_ORDER:6,
  FULFILLMENT:7,
  COLLECTED_GROSS_PROFIT:8,
};

function segmentOf(product=''):Segment{
  const p=product.toLowerCase();
  if(/soy|soya|oil|aceite|sunflower|canola|palm/.test(p))return'Edible Oils';
  if(/food|rice|sugar|milk|coffee|flour|beverage|pollo|chicken/.test(p))return'Food & Beverage';
  if(/cement|tile|ceramic|pvc|steel|construction|hardware/.test(p))return'Construction';
  if(/fuel|diesel|gasoline|crude|energy|lng|lpg/.test(p))return'Energy';
  if(/machine|equipment|industrial|soda ash|chemical/.test(p))return'Industrial';
  return'Other';
}
function daysOld(ts?:string){if(!ts)return 0;return Math.max(0,Math.floor((Date.now()-new Date(ts).getTime())/86400000))}
function pct(n:number,d:number){return d?Math.round((n/d)*100):0}
function atLeast(row:Rfq,stage:number){return(stageRank[row.stage]??0)>=stage}

export default function SofiaSalesPerformanceCenter(){
  const [rows,setRows]=useState<Rfq[]>([]);
  const [loading,setLoading]=useState(true);
  const [status,setStatus]=useState('');

  async function refresh(){
    setLoading(true);setStatus('');
    if(!supabaseConfigured){setStatus('Supabase frontend configuration is unavailable.');setLoading(false);return}
    const {data,error}=await supabase.from('trade_rfq_intakes')
      .select('id,source,product,company_name,buyer_name,stage,qualification_status,completeness_score,next_action,created_at,updated_at')
      .order('updated_at',{ascending:false}).limit(500);
    if(error)setStatus(`Sales performance access unavailable: ${error.message}`);
    else setRows((data||[]) as Rfq[]);
    setLoading(false);
  }
  useEffect(()=>{void refresh()},[]);

  const metrics=useMemo(()=>{
    const total=rows.length;
    const qualified=rows.filter(r=>atLeast(r,1)).length;
    const complete=rows.filter(r=>atLeast(r,2)).length;
    const quoted=rows.filter(r=>atLeast(r,4)).length;
    const po=rows.filter(r=>atLeast(r,6)).length;
    const collected=rows.filter(r=>atLeast(r,8)).length;
    const avg=total?Math.round(rows.reduce((sum,r)=>sum+(r.completeness_score||0),0)/total):0;
    return{total,qualified,complete,quoted,po,collected,avg};
  },[rows]);

  const segments=useMemo<SegmentMetrics[]>(()=>{
    const names:Segment[]=['Edible Oils','Food & Beverage','Construction','Energy','Industrial','Other'];
    return names.map(name=>{
      const subset=rows.filter(row=>segmentOf(row.product)===name);
      const qualified=subset.filter(row=>atLeast(row,1)).length;
      const complete=subset.filter(row=>atLeast(row,2)).length;
      const quoted=subset.filter(row=>atLeast(row,4)).length;
      const po=subset.filter(row=>atLeast(row,6)).length;
      const avgCompleteness=subset.length?Math.round(subset.reduce((sum,row)=>sum+(row.completeness_score||0),0)/subset.length):0;
      return{
        name,
        total:subset.length,
        qualified,
        complete,
        quoted,
        po,
        rfqRate:pct(complete,subset.length),
        quoteRate:pct(quoted,complete),
        poRate:pct(po,quoted),
        avgCompleteness,
      };
    }).filter(segment=>segment.total>0);
  },[rows]);

  const coaching=useMemo(()=>segments.map(segment=>{
    let action='Keep the current progressive qualification pattern.';
    if(segment.rfqRate<60)action='Reduce friction: ask only the single highest-value missing RFQ fact first.';
    else if(segment.quoteRate<50&&segment.complete>=2)action='RFQs are completing but not reaching quote: accelerate firm supplier pricing and remove sourcing bottlenecks.';
    else if(segment.poRate<35&&segment.quoted>=2)action='Quote-to-PO conversion is weak: strengthen objection handling, proof, terms clarity and follow-up cadence without discounting blindly.';
    else if(segment.poRate>=50)action='Protect and reuse this segment playbook; prioritize similar qualified demand.';
    return{...segment,action};
  }),[segments]);

  const stale=useMemo(()=>rows.filter(row=>daysOld(row.updated_at)>=3&&!atLeast(row,6)).slice(0,20),[rows]);
  const cards:Array<[string,string|number]>=[
    ['Inbound/RFQs',metrics.total],['Qualified',metrics.qualified],['RFQ complete',metrics.complete],
    ['Formal quote+',metrics.quoted],['PO+',metrics.po],['Collected GP',metrics.collected],['Avg completeness',`${metrics.avg}%`],
  ];

  return <main style={s.page}>
    <header style={s.header}>
      <div><div style={s.kicker}>SOFÍA · SALES PERFORMANCE BRAIN</div><h1 style={s.h1}>Improve conversion from evidence, not guesses.</h1><p style={s.lead}>Sofía learns which qualification and follow-up patterns correlate with RFQ completion, formal quotes and purchase orders. Sensitive commercial authority stays governed.</p></div>
      <nav style={s.nav}><a href="/owner/dashboard" style={s.link}>Dashboard</a><a href="/owner/rfqs" style={s.link}>RFQs</a><a href="/owner/priorities" style={s.link}>Priorities</a><button style={s.button} onClick={()=>void refresh()}>{loading?'Checking…':'Refresh'}</button></nav>
    </header>

    <section style={s.metrics}>{cards.map(([label,value])=><article style={s.metric} key={label}><small>{label}</small><strong>{value}</strong></article>)}</section>

    <section style={s.panel}><div style={s.kicker}>FUNNEL HEALTH</div><h2 style={s.h2}>Conversion gates</h2><div style={s.funnel}><div>Qualified <b>{pct(metrics.qualified,metrics.total)}%</b></div><div>RFQ complete <b>{pct(metrics.complete,metrics.qualified)}%</b></div><div>Formal quote <b>{pct(metrics.quoted,metrics.complete)}%</b></div><div>Purchase order <b>{pct(metrics.po,metrics.quoted)}%</b></div><div>Collected GP <b>{pct(metrics.collected,metrics.po)}%</b></div></div></section>

    <section style={s.two}>
      <article style={s.panel}><div style={s.kicker}>SEGMENT LEARNING</div><h2 style={s.h2}>Where Sofía should adapt</h2>{coaching.length===0?<p style={s.muted}>No segmented RFQ evidence yet.</p>:coaching.map(item=><div style={s.rule} key={item.name}><div><b>{item.name}</b><span style={s.segmentStats}>{item.total} records · RFQ {item.rfqRate}% · quote {item.quoteRate}% · PO {item.poRate}%</span></div><p>{item.action}</p></div>)}</article>
      <article style={s.panel}><div style={s.kicker}>LEARNING GUARDRAILS</div><h2 style={s.h2}>What can and cannot self-improve</h2><div style={s.rule}><b>May adapt</b><p>Question order, message length, objection handling, follow-up timing, segment-specific terminology and next-action framing.</p></div><div style={s.rule}><b>May not adapt autonomously</b><p>Prices, margins, payment authority, sanctions/compliance policy, contracts, supplier commitments, legal claims, customer credit, refunds or security controls.</p></div><div style={s.rule}><b>Evidence threshold</b><p>Do not promote a playbook from one conversation. Prefer repeated patterns with meaningful sample size and measurable stage advancement.</p></div></article>
    </section>

    <section style={s.panel}><div style={s.kicker}>RECOVERY / FOLLOW-UP QUEUE</div><h2 style={s.h2}>Stale opportunities requiring attention</h2>{stale.length===0?<p style={s.muted}>No stale pre-PO opportunities in the current sample.</p>:<div style={s.tableWrap}><table style={s.table}><thead><tr><th>Buyer</th><th>Product</th><th>Stage</th><th>Complete</th><th>Days stale</th><th>Next action</th></tr></thead><tbody>{stale.map(row=><tr key={row.id}><td>{row.company_name||row.buyer_name||'Unknown'}</td><td>{row.product||'—'}</td><td>{row.stage}</td><td>{row.completeness_score}%</td><td>{daysOld(row.updated_at)}</td><td>{row.next_action||'Advance the next evidence gate'}</td></tr>)}</tbody></table></div>}{status&&<p style={s.status}>{status}</p>}</section>

    <footer style={s.footer}>Houston operating timezone · Sofia optimization objective: qualified RFQ → firm quote → PO → collected gross profit, with protected SAHJONY economics.</footer>
  </main>;
}

const s:Record<string,any>={
  page:{minHeight:'100vh',background:'#03070c',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:28},
  header:{maxWidth:1500,margin:'0 auto',display:'flex',justifyContent:'space-between',gap:24,alignItems:'end',padding:'28px 0 36px',borderBottom:'1px solid rgba(255,255,255,.08)'},
  kicker:{fontSize:10,fontWeight:950,letterSpacing:'.17em',color:'#66dcff'},h1:{fontSize:'clamp(42px,6vw,78px)',letterSpacing:'-.055em',lineHeight:.95,margin:'12px 0'},lead:{maxWidth:850,color:'#8fa4b5',lineHeight:1.6},
  nav:{display:'flex',gap:10,flexWrap:'wrap'},link:{color:'#d7e6ee',textDecoration:'none',padding:'10px 13px',border:'1px solid rgba(255,255,255,.1)',borderRadius:999,fontSize:12},button:{background:'#66dcff',color:'#021018',border:0,borderRadius:999,padding:'10px 13px',fontWeight:900},
  metrics:{maxWidth:1500,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:12},metric:{padding:18,border:'1px solid rgba(255,255,255,.08)',borderRadius:16,background:'#09131d',display:'grid',gap:8},
  panel:{maxWidth:1500,margin:'16px auto',padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'#07111a'},h2:{margin:'8px 0 18px',fontSize:28},funnel:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:10},two:{maxWidth:1500,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(360px,1fr))',gap:16},
  rule:{padding:'12px 0',borderTop:'1px solid rgba(255,255,255,.06)',color:'#9eb0bd'},segmentStats:{display:'block',fontSize:11,color:'#70899a',marginTop:4},muted:{color:'#8397a6'},tableWrap:{overflow:'auto'},table:{width:'100%',minWidth:900,borderCollapse:'collapse'},status:{color:'#ffbd6d'},footer:{maxWidth:1500,margin:'24px auto',color:'#6e8291',fontSize:11},
};
