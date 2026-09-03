import {useEffect,useMemo,useState} from 'react';

type Health={ok:boolean;label:string;detail:string};
type Probe={key:string;label:string;url:string};

const probes:Probe[]=[
  {key:'app',label:'Trading OS',url:'/api/health'},
  {key:'whatsapp',label:'WhatsApp',url:'/whatsapp/health'},
  {key:'worldwide',label:'Worldwide Connect',url:'/api/connect/worldwide/health'},
];

const stages=[
  ['Research lead','Evidence-backed target identified'],
  ['Qualified demand','Product, quantity, destination and timing confirmed'],
  ['RFQ complete','Specification and commercial requirements complete'],
  ['Firm supplier price','Supplier economics verified'],
  ['Formal quote','SAHJONY margin protected before release'],
  ['Negotiation','Terms, payment and logistics aligned'],
  ['Purchase order','Buyer commitment documented'],
  ['Collected gross profit','Cash received and transaction closed'],
];

const priorities=[
  {title:'Convert demand, not activity',body:'Escalate only buyer requests with enough information to price and execute.'},
  {title:'Protect economics first',body:'Keep supplier identity, landed-cost logic and SAHJONY margin controlled until commercial commitment.'},
  {title:'Minimize capital exposure',body:'Prefer buyer-funded, documentary, escrow or supplier-supported structures over speculative inventory.'},
  {title:'Operate by exceptions',body:'Surface blocked quotes, stale follow-ups, logistics failures and counterparty risk before routine work.'},
];

function statusTone(value?:Health){return !value?'#708090':value.ok?'#36d399':'#ffb454'}

export default function OwnerCommandCenter(){
  const [health,setHealth]=useState<Record<string,Health>>({});
  const [checkedAt,setCheckedAt]=useState<string>('');
  const [loading,setLoading]=useState(true);

  async function refresh(){
    setLoading(true);
    const entries=await Promise.all(probes.map(async probe=>{
      try{
        const response=await fetch(probe.url,{headers:{accept:'application/json'},cache:'no-store'});
        const raw=await response.text();
        let parsed:any={};
        try{parsed=raw?JSON.parse(raw):{}}catch{parsed={}}
        const explicitReady=parsed.production_ready??parsed.send_ready??parsed.gateway_connected??parsed.ready;
        const ok=response.ok&&(explicitReady===undefined?true:Boolean(explicitReady));
        const detail=ok
          ? String(parsed.status||parsed.service||'Operational')
          : String(parsed.reason||parsed.status||`HTTP ${response.status}`);
        return [probe.key,{ok,label:probe.label,detail}] as const;
      }catch(error){
        return [probe.key,{ok:false,label:probe.label,detail:error instanceof Error?error.message:'Unavailable'}] as const;
      }
    }));
    setHealth(Object.fromEntries(entries));
    setCheckedAt(new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
    setLoading(false);
  }

  useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(id)},[]);
  const healthy=useMemo(()=>Object.values(health).filter(item=>item.ok).length,[health]);
  const readiness=probes.length?Math.round((healthy/probes.length)*100):0;

  return <main style={s.page}>
    <header style={s.header}>
      <a href="/" style={s.brand}>SAHJONY <span style={{color:'#66dcff'}}>GLOBAL TRADE</span></a>
      <nav style={s.nav}>
        <a href="/owner/exceptions" style={s.link}>Exceptions</a>
        <a href="/owner/deals" style={s.link}>Deals</a>
        <a href="/owner/intelligence" style={s.link}>Intelligence</a>
        <button onClick={()=>void refresh()} style={s.button}>{loading?'Checking…':'Refresh systems'}</button>
      </nav>
    </header>

    <section style={s.hero}>
      <div>
        <div style={s.eyebrow}>OWNER COMMAND CENTER · EXECUTION FIRST</div>
        <h1 style={s.h1}>Turn verified demand into <span style={{color:'#66dcff'}}>collected gross profit.</span></h1>
        <p style={s.lead}>One operating system for buyer qualification, supplier pricing, commercial execution, communications, logistics and risk. No vanity pipeline. No invented revenue.</p>
      </div>
      <div style={s.scoreCard}>
        <div style={s.scoreLabel}>LIVE SYSTEM READINESS</div>
        <div style={s.score}>{readiness}<span style={s.scoreSmall}>%</span></div>
        <div style={s.muted}>{healthy} of {probes.length} critical services ready{checkedAt?` · checked ${checkedAt}`:''}</div>
      </div>
    </section>

    <section style={s.grid3}>
      {probes.map(probe=>{const value=health[probe.key];return <article key={probe.key} style={s.card}>
        <div style={s.row}><strong>{probe.label}</strong><span style={{...s.dot,background:statusTone(value)}}/></div>
        <div style={{...s.status,color:statusTone(value)}}>{!value?'CHECKING':value.ok?'READY':'ATTENTION'}</div>
        <div style={s.muted}>{value?.detail||'Verifying live endpoint'}</div>
      </article>})}
    </section>

    <section style={s.twoCol}>
      <article style={s.panel}>
        <div style={s.panelHead}><div><div style={s.eyebrow}>COMMERCIAL ENGINE</div><h2 style={s.h2}>Deal conversion ladder</h2></div><a href="/owner/deals" style={s.action}>Open deals →</a></div>
        <div style={s.ladder}>{stages.map((stage,index)=><div key={stage[0]} style={s.stage}>
          <span style={s.stageNo}>{String(index+1).padStart(2,'0')}</span><div><strong>{stage[0]}</strong><div style={s.muted}>{stage[1]}</div></div>
        </div>)}</div>
      </article>

      <article style={s.panel}>
        <div style={s.eyebrow}>CEO OPERATING RULES</div><h2 style={s.h2}>What the company optimizes</h2>
        <div style={s.ruleList}>{priorities.map((item,index)=><div key={item.title} style={s.rule}>
          <div style={s.ruleIndex}>0{index+1}</div><div><strong>{item.title}</strong><div style={s.muted}>{item.body}</div></div>
        </div>)}</div>
        <div style={s.callout}><strong>Primary scoreboard</strong><div style={s.muted}>Qualified RFQs · firm quotes · transaction-ready deals · collected gross profit · conversion cycle time · capital at risk.</div></div>
      </article>
    </section>

    <section style={s.panel}>
      <div style={s.panelHead}><div><div style={s.eyebrow}>EXECUTIVE ACTION QUEUE</div><h2 style={s.h2}>Move the highest-value bottleneck first</h2></div></div>
      <div style={s.grid3}>
        <a href="/owner/exceptions" style={s.actionCard}><strong>Resolve executive exceptions</strong><span>Escalate blocked RFQs, missing economics, stale deals, PO/payment and logistics risks.</span><b>OPEN EXCEPTIONS →</b></a>
        <a href="/owner/deals" style={s.actionCard}><strong>Close active opportunities</strong><span>Advance qualified demand to firm price, quote and PO.</span><b>GO TO DEALS →</b></a>
        <a href="/owner/intelligence" style={s.actionCard}><strong>Find evidence-backed demand</strong><span>Research buyers, suppliers, pricing, logistics and counterparties.</span><b>OPEN INTELLIGENCE →</b></a>
        <a href="/start" style={s.actionCard}><strong>Capture a new RFQ</strong><span>Turn inbound demand into structured commercial requirements.</span><b>START REQUEST →</b></a>
      </div>
    </section>

    <footer style={s.footer}>SAHJONY LLC · GLOBAL TRADE OS · Owner view prioritizes verified execution over reported activity.</footer>
  </main>
}

const s:Record<string,any>={
  page:{minHeight:'100vh',background:'radial-gradient(circle at 20% -10%,#12334a 0,#07111d 34%,#04080e 70%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 24px 48px'},
  header:{maxWidth:1320,margin:'0 auto',height:74,display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',gap:20},
  brand:{fontWeight:950,letterSpacing:'.08em',fontSize:14,color:'#fff',textDecoration:'none'},nav:{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap'},link:{color:'#b9c7d3',textDecoration:'none',fontSize:14,padding:'9px 10px'},
  button:{background:'#66dcff',border:0,borderRadius:10,padding:'10px 13px',fontWeight:900,color:'#021018',cursor:'pointer'},
  hero:{maxWidth:1320,margin:'0 auto',padding:'70px 0 44px',display:'grid',gridTemplateColumns:'minmax(0,1.8fr) minmax(260px,.7fr)',gap:30,alignItems:'end'},
  eyebrow:{fontSize:11,fontWeight:950,letterSpacing:'.16em',color:'#66dcff',marginBottom:14},h1:{fontSize:'clamp(46px,6vw,88px)',lineHeight:.93,letterSpacing:'-.055em',maxWidth:980,margin:'0 0 22px'},lead:{maxWidth:820,fontSize:17,lineHeight:1.65,color:'#9fb2c1',margin:0},
  scoreCard:{border:'1px solid rgba(102,220,255,.23)',background:'rgba(6,18,30,.72)',backdropFilter:'blur(18px)',borderRadius:20,padding:24},scoreLabel:{fontSize:11,letterSpacing:'.14em',fontWeight:900,color:'#9fb2c1'},score:{fontSize:64,fontWeight:950,letterSpacing:'-.06em',lineHeight:1.05,margin:'10px 0'},scoreSmall:{fontSize:22,color:'#688091'},muted:{color:'#849aab',fontSize:13,lineHeight:1.55},
  grid3:{maxWidth:1320,margin:'0 auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:14},card:{padding:20,border:'1px solid rgba(255,255,255,.09)',borderRadius:16,background:'rgba(8,17,27,.76)'},row:{display:'flex',justifyContent:'space-between',gap:12},dot:{width:9,height:9,borderRadius:999,boxShadow:'0 0 18px currentColor'},status:{fontSize:11,fontWeight:950,letterSpacing:'.13em',margin:'18px 0 6px'},
  twoCol:{maxWidth:1320,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(340px,1fr))',gap:16},panel:{maxWidth:1320,margin:'16px auto',padding:24,border:'1px solid rgba(255,255,255,.09)',borderRadius:20,background:'rgba(6,14,23,.82)'},panelHead:{display:'flex',alignItems:'start',justifyContent:'space-between',gap:16},h2:{fontSize:28,letterSpacing:'-.035em',margin:'0 0 18px'},action:{color:'#66dcff',textDecoration:'none',fontWeight:850,fontSize:13,whiteSpace:'nowrap'},
  ladder:{display:'grid',gap:8},stage:{display:'grid',gridTemplateColumns:'38px 1fr',gap:10,padding:'11px 0',borderTop:'1px solid rgba(255,255,255,.06)'},stageNo:{fontSize:11,color:'#66dcff',fontWeight:900,paddingTop:3},ruleList:{display:'grid',gap:12},rule:{display:'grid',gridTemplateColumns:'42px 1fr',gap:10,padding:'10px 0'},ruleIndex:{fontWeight:950,color:'#66dcff',fontSize:12},callout:{marginTop:20,padding:17,borderRadius:14,background:'rgba(102,220,255,.07)',border:'1px solid rgba(102,220,255,.15)'},
  actionCard:{minHeight:145,padding:20,border:'1px solid rgba(255,255,255,.08)',borderRadius:15,background:'rgba(255,255,255,.025)',color:'#eef7fb',textDecoration:'none',display:'flex',flexDirection:'column',gap:10},footer:{maxWidth:1320,margin:'34px auto 0',paddingTop:18,borderTop:'1px solid rgba(255,255,255,.07)',color:'#627989',fontSize:11,letterSpacing:'.08em'}
};
