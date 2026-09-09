import {useEffect,useMemo,useState} from 'react';

type ChannelState='ready'|'attention'|'unknown'|'checking';
type Channel={key:string;label:string;kind:string;endpoint?:string;identity?:string;notes:string};
type Health={state:ChannelState;detail:string};

type QueueItem={priority:'OWNER'|'HIGH'|'NORMAL';title:string;body:string;action:string};

const channels:Channel[]=[
  {key:'gmail',label:'Sofía Gmail',kind:'Email',endpoint:'/native-email/health',identity:'sofiaexecutivemanager@gmail.com',notes:'Executive commercial mailbox and relationship continuity.'},
  {key:'whatsapp',label:'WhatsApp Business',kind:'Messaging',endpoint:'/whatsapp/health',identity:'+1 281-662-8581',notes:'Primary customer and supplier messaging channel.'},
  {key:'agentmail',label:'AgentMail Bridge',kind:'Email bridge',endpoint:'/whatsapp/sofia/agentmail/health',notes:'Sofía email-to-communications bridge; configuration is verified from its own endpoint only.'},
  {key:'telegram',label:'Telegram',kind:'Messaging',identity:'@SahjonyGlobalTradeBot',notes:'Native connector status is not assumed until a verified platform endpoint is exposed.'},
  {key:'meta',label:'Facebook / Instagram',kind:'Social inbox',notes:'DM and comment inbox remains fail-closed until direct authorized profile connectors are exposed to the platform.'},
  {key:'outlook',label:'Outlook',kind:'Email',notes:'Provider-independent adapter slot. Readiness is not inferred from external tool availability.'},
];

const ownerGates=[
  'Binding price, credit, volume or commercial commitments',
  'Contracts, signatures, payments, refunds or bank instruction changes',
  'Protected supplier/customer identities or sensitive counterparty disclosure',
  'Legal, sanctions, compliance or regulated-product determinations',
  'Credential, ownership, authorization or security-policy changes',
];

const autonomousActions=[
  'Classify inbound conversations by buyer, supplier, RFQ, logistics, support and risk',
  'Reconcile identities across channels without creating duplicate CRM contacts',
  'Draft or send routine one-to-one replies when policy and channel authorization permit',
  'Extract product, quantity, specification, destination and timing into structured RFQ fields',
  'Track follow-up aging, duplicate-send risk and next safe commercial action',
  'Attribute conversations to CRM opportunities without promoting unsupported deal stages',
];

function tone(state:ChannelState){return state==='ready'?'#38d99f':state==='attention'?'#ffb454':state==='checking'?'#66dcff':'#788b9a'}

export default function OwnerCommunicationsOS(){
  const [health,setHealth]=useState<Record<string,Health>>({});
  const [loading,setLoading]=useState(true);
  const [checkedAt,setCheckedAt]=useState('');

  async function refresh(){
    setLoading(true);
    const entries=await Promise.all(channels.map(async channel=>{
      if(!channel.endpoint)return [channel.key,{state:'unknown' as const,detail:'No verified native health endpoint configured'}] as const;
      try{
        const response=await fetch(channel.endpoint,{headers:{accept:'application/json'},cache:'no-store'});
        const raw=await response.text();
        let parsed:any={};
        try{parsed=raw?JSON.parse(raw):{}}catch{parsed={}}
        const status=String(parsed.status||'').toLowerCase();
        const explicit=parsed.send_ready??parsed.production_ready??parsed.ready??parsed.gateway_connected;
        const bad=['configuration_required','degraded','error','unavailable','offline'].includes(status);
        const ready=response.ok&&!bad&&(explicit===undefined?true:Boolean(explicit));
        const detail=ready?String(parsed.status||parsed.service||'Operational'):String(parsed.reason||parsed.status||`HTTP ${response.status}`);
        return [channel.key,{state:ready?'ready' as const:'attention' as const,detail}] as const;
      }catch(error){return [channel.key,{state:'attention' as const,detail:error instanceof Error?error.message:'Unavailable'}] as const}
    }));
    setHealth(Object.fromEntries(entries));
    setCheckedAt(new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
    setLoading(false);
  }

  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(timer)},[]);

  const verifiedReady=useMemo(()=>channels.filter(c=>health[c.key]?.state==='ready').length,[health]);
  const verifiedChecked=useMemo(()=>channels.filter(c=>Boolean(c.endpoint)).length,[]);
  const queue:QueueItem[]=[
    {priority:'OWNER',title:'Owner-only action gate',body:'Any binding commercial, payment, credential, protected-identity or compliance decision remains blocked for explicit owner authority.',action:'Governance active'},
    {priority:'HIGH',title:'Identity reconciliation',body:'Cross-channel contacts should resolve to one relationship record before new CRM contacts are created.',action:'Deduplicate first'},
    {priority:'NORMAL',title:'RFQ extraction',body:'Inbound demand becomes structured only when the message contains genuine product requirements; conversation activity alone is not qualified demand.',action:'Evidence required'},
  ];

  return <main style={s.page}>
    <header style={s.header}>
      <a href="/owner/dashboard" style={s.brand}>SAHJONY <span style={{color:'#66dcff'}}>COMMUNICATIONS OS</span></a>
      <nav style={s.nav}>
        <a href="/owner/dashboard" style={s.link}>Command Center</a>
        <a href="/owner/rfqs" style={s.link}>RFQs</a>
        <a href="/owner/deals" style={s.link}>Deals</a>
        <a href="/owner/sofia-performance" style={s.link}>Sofía</a>
        <button onClick={()=>void refresh()} style={s.button}>{loading?'Checking…':'Refresh channels'}</button>
      </nav>
    </header>

    <section style={s.hero}>
      <div><div style={s.eyebrow}>NATIVE · PROVIDER-INDEPENDENT · EVIDENCE-GATED</div><h1 style={s.h1}>One relationship layer across <span style={{color:'#66dcff'}}>every authorized conversation.</span></h1><p style={s.lead}>Unify email, WhatsApp, Telegram and social messaging around a single CRM/RFQ truth. Sofía can automate routine communication while owner-only decisions remain fail-closed.</p></div>
      <aside style={s.scoreCard}><div style={s.scoreLabel}>VERIFIED NATIVE CHANNELS</div><div style={s.score}>{verifiedReady}<span style={s.scoreSmall}>/{verifiedChecked}</span></div><div style={s.muted}>Ready among channels with configured health probes{checkedAt?` · checked ${checkedAt}`:''}. Unknown channels are never counted as ready.</div></aside>
    </section>

    <section style={s.channelGrid}>{channels.map(channel=>{const value=health[channel.key]||{state:'checking' as const,detail:'Checking'};return <article key={channel.key} style={s.card}>
      <div style={s.cardTop}><div><div style={s.kind}>{channel.kind}</div><h2 style={s.cardTitle}>{channel.label}</h2></div><span style={{...s.dot,background:tone(value.state)}}/></div>
      <div style={{...s.state,color:tone(value.state)}}>{value.state.toUpperCase()}</div>
      {channel.identity&&<div style={s.identity}>{channel.identity}</div>}
      <p style={s.muted}>{value.detail}</p><p style={s.notes}>{channel.notes}</p>
    </article>})}</section>

    <section style={s.twoCol}>
      <article style={s.panel}><div style={s.eyebrow}>SOFÍA AUTONOMY</div><h2 style={s.h2}>Actions the communications brain can perform</h2><div style={s.list}>{autonomousActions.map((x,i)=><div key={x} style={s.listItem}><span style={s.num}>{String(i+1).padStart(2,'0')}</span><span>{x}</span></div>)}</div></article>
      <article style={s.panel}><div style={s.eyebrow}>OWNER AUTHORITY</div><h2 style={s.h2}>Hard gates that cannot be bypassed</h2><div style={s.list}>{ownerGates.map((x,i)=><div key={x} style={s.listItem}><span style={{...s.num,color:'#ffb454'}}>{String(i+1).padStart(2,'0')}</span><span>{x}</span></div>)}</div></article>
    </section>

    <section style={s.panel}><div style={s.panelHead}><div><div style={s.eyebrow}>EXECUTIVE COMMUNICATION QUEUE</div><h2 style={s.h2}>Operate by evidence and exceptions</h2></div><a href="/owner/rfqs" style={s.action}>Open RFQs →</a></div><div style={s.queue}>{queue.map(item=><article key={item.title} style={s.queueItem}><div style={s.badge}>{item.priority}</div><strong>{item.title}</strong><p style={s.muted}>{item.body}</p><span style={s.actionText}>{item.action}</span></article>)}</div></section>

    <section style={s.panel}><div style={s.eyebrow}>COMMERCIAL CONVERSION CONTRACT</div><h2 style={s.h2}>Conversation → CRM → RFQ → Revenue</h2><div style={s.flow}>{['Inbound conversation','Identity reconciled','Intent classified','Genuine requirement','RFQ complete','Firm quote','Negotiation','Contract / PO','Collected gross profit'].map((x,i)=><div key={x} style={s.flowStep}><span>{String(i+1).padStart(2,'0')}</span><strong>{x}</strong></div>)}</div><p style={s.muted}>No stage is promoted merely because a message was sent, opened, liked or replied to. Commercial stages require their own evidence.</p></section>

    <footer style={s.footer}>SAHJONY LLC · Native Communications OS · External aggregators may be used as temporary adapters, never as the system of record.</footer>
  </main>
}

const s:Record<string,any>={page:{minHeight:'100vh',background:'radial-gradient(circle at 18% -8%,#12364c 0,#07121f 34%,#04080e 72%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 24px 48px'},header:{maxWidth:1320,margin:'0 auto',minHeight:74,display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',gap:20,padding:'10px 0'},brand:{fontWeight:950,letterSpacing:'.08em',fontSize:14,color:'#fff',textDecoration:'none'},nav:{display:'flex',alignItems:'center',gap:7,flexWrap:'wrap',justifyContent:'flex-end'},link:{color:'#b9c7d3',textDecoration:'none',fontSize:13,padding:'9px 9px'},button:{background:'#66dcff',border:0,borderRadius:10,padding:'10px 13px',fontWeight:900,color:'#021018',cursor:'pointer'},hero:{maxWidth:1320,margin:'0 auto',padding:'64px 0 38px',display:'grid',gridTemplateColumns:'minmax(0,1.8fr) minmax(260px,.7fr)',gap:30,alignItems:'end'},eyebrow:{fontSize:11,fontWeight:950,letterSpacing:'.16em',color:'#66dcff',marginBottom:14},h1:{fontSize:'clamp(44px,5.8vw,82px)',lineHeight:.94,letterSpacing:'-.055em',maxWidth:980,margin:'0 0 22px'},lead:{maxWidth:820,fontSize:17,lineHeight:1.65,color:'#9fb2c1',margin:0},scoreCard:{border:'1px solid rgba(102,220,255,.23)',background:'rgba(6,18,30,.72)',borderRadius:20,padding:24},scoreLabel:{fontSize:11,letterSpacing:'.14em',fontWeight:900,color:'#9fb2c1'},score:{fontSize:62,fontWeight:950,letterSpacing:'-.06em',lineHeight:1.05,margin:'10px 0'},scoreSmall:{fontSize:22,color:'#688091'},muted:{color:'#849aab',fontSize:13,lineHeight:1.55},channelGrid:{maxWidth:1320,margin:'0 auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))',gap:14},card:{padding:20,border:'1px solid rgba(255,255,255,.09)',borderRadius:16,background:'rgba(8,17,27,.76)'},cardTop:{display:'flex',justifyContent:'space-between',gap:12},kind:{fontSize:10,fontWeight:900,letterSpacing:'.13em',color:'#718a9a',textTransform:'uppercase'},cardTitle:{fontSize:19,margin:'7px 0 0'},dot:{width:10,height:10,borderRadius:999,boxShadow:'0 0 18px currentColor'},state:{fontSize:10,fontWeight:950,letterSpacing:'.13em',margin:'18px 0 8px'},identity:{fontSize:13,color:'#d7e7ef',fontWeight:800,wordBreak:'break-word'},notes:{color:'#aab8c3',fontSize:12.5,lineHeight:1.55,marginBottom:0},twoCol:{maxWidth:1320,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(340px,1fr))',gap:16},panel:{maxWidth:1320,margin:'16px auto',padding:24,border:'1px solid rgba(255,255,255,.09)',borderRadius:20,background:'rgba(6,14,23,.82)'},panelHead:{display:'flex',alignItems:'start',justifyContent:'space-between',gap:16},h2:{fontSize:28,letterSpacing:'-.035em',margin:'0 0 18px'},list:{display:'grid',gap:8},listItem:{display:'grid',gridTemplateColumns:'38px 1fr',gap:10,padding:'11px 0',borderTop:'1px solid rgba(255,255,255,.06)',fontSize:13.5,lineHeight:1.5},num:{fontSize:11,color:'#66dcff',fontWeight:900,paddingTop:3},action:{color:'#66dcff',textDecoration:'none',fontWeight:850,fontSize:13,whiteSpace:'nowrap'},queue:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(250px,1fr))',gap:12},queueItem:{padding:18,border:'1px solid rgba(255,255,255,.07)',borderRadius:14,background:'rgba(255,255,255,.025)'},badge:{display:'inline-flex',fontSize:9,fontWeight:950,letterSpacing:'.12em',padding:'5px 7px',borderRadius:999,background:'rgba(102,220,255,.09)',color:'#66dcff',marginBottom:12},actionText:{fontSize:11,fontWeight:900,color:'#d6f5ff'},flow:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(125px,1fr))',gap:8,marginBottom:16},flowStep:{display:'flex',flexDirection:'column',gap:8,padding:14,borderRadius:12,border:'1px solid rgba(255,255,255,.07)',background:'rgba(255,255,255,.02)',fontSize:12},footer:{maxWidth:1320,margin:'34px auto 0',paddingTop:18,borderTop:'1px solid rgba(255,255,255,.07)',color:'#627989',fontSize:11,letterSpacing:'.08em'}};
