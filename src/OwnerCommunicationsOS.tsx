import {useEffect,useMemo,useState} from 'react';

type ChannelState='ready'|'attention'|'unknown'|'checking';
type Health={state:ChannelState;detail:string};
type Channel={key:string;label:string;endpoint?:string;notes:string};

const channels:Channel[]=[
  {key:'email',label:'Executive Email',endpoint:'/native-email/health',notes:'Commercial email continuity and relationship intake.'},
  {key:'whatsapp',label:'WhatsApp Business',endpoint:'/whatsapp/health',notes:'Primary customer and supplier messaging channel.'},
  {key:'agentmail',label:'AgentMail Bridge',endpoint:'/whatsapp/sofia/agentmail/health',notes:'Email-to-Sofía bridge; readiness comes only from its own endpoint.'},
  {key:'telegram',label:'Telegram',notes:'Fail-closed until a native health endpoint is verified.'},
  {key:'social',label:'Social Inbox',notes:'Facebook/Instagram and other networks remain evidence-gated.'},
];

const ownerGates=['Binding prices, credit or volume commitments','Contracts, payments, refunds or bank changes','Protected supplier/customer identity disclosure','Legal, sanctions and compliance determinations','Credential, ownership and security-policy changes'];
const autonomous=['Classify inbound conversations by commercial intent','Reconcile identities before creating duplicate CRM contacts','Extract genuine demand into structured RFQ fields','Draft routine one-to-one replies when channel policy permits','Track follow-up aging, duplicates and next safe action','Attribute conversations to opportunities without inventing deal stages'];

function tone(state:ChannelState){return state==='ready'?'#38d99f':state==='attention'?'#ffb454':state==='checking'?'#66dcff':'#788b9a'}

export default function OwnerCommunicationsOS(){
  const [health,setHealth]=useState<Record<string,Health>>({});
  const [loading,setLoading]=useState(true);
  const [checkedAt,setCheckedAt]=useState('');
  async function refresh(){
    setLoading(true);
    const entries=await Promise.all(channels.map(async channel=>{
      if(!channel.endpoint)return [channel.key,{state:'unknown' as const,detail:'No verified native health endpoint'}] as const;
      try{
        const response=await fetch(channel.endpoint,{headers:{accept:'application/json'},cache:'no-store'});
        const raw=await response.text();let parsed:any={};try{parsed=raw?JSON.parse(raw):{}}catch{}
        const status=String(parsed.status||'').toLowerCase();
        const explicit=parsed.send_ready??parsed.production_ready??parsed.ready??parsed.gateway_connected;
        const bad=['configuration_required','degraded','error','unavailable','offline'].includes(status);
        const ready=response.ok&&!bad&&(explicit===undefined?true:Boolean(explicit));
        return [channel.key,{state:ready?'ready' as const:'attention' as const,detail:ready?String(parsed.status||parsed.service||'Operational'):String(parsed.reason||parsed.status||`HTTP ${response.status}`)}] as const;
      }catch(error){return [channel.key,{state:'attention' as const,detail:error instanceof Error?error.message:'Unavailable'}] as const}
    }));
    setHealth(Object.fromEntries(entries));setCheckedAt(new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}));setLoading(false);
  }
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(timer)},[]);
  const checked=useMemo(()=>channels.filter(c=>Boolean(c.endpoint)).length,[]);
  const ready=useMemo(()=>channels.filter(c=>health[c.key]?.state==='ready').length,[health]);
  return <main style={s.page}>
    <header style={s.header}><a href="/owner/dashboard" style={s.brand}>SAHJONY <span style={{color:'#66dcff'}}>COMMUNICATIONS OS</span></a><nav style={s.nav}><a href="/owner/dashboard" style={s.link}>Command Center</a><a href="/owner/social" style={s.link}>Social OS</a><a href="/owner/rfqs" style={s.link}>RFQs</a><button onClick={()=>void refresh()} style={s.button}>{loading?'Checking…':'Refresh'}</button></nav></header>
    <section style={s.hero}><div><div style={s.eyebrow}>NATIVE · EVIDENCE-GATED · FAIL-CLOSED</div><h1 style={s.h1}>One operating layer for <span style={{color:'#66dcff'}}>every authorized conversation.</span></h1><p style={s.lead}>Sofía can classify, reconcile and convert legitimate conversations into CRM/RFQ evidence while owner-only commercial and compliance decisions remain protected.</p></div><aside style={s.scoreCard}><div style={s.label}>VERIFIED CHANNELS</div><div style={s.score}>{ready}<span style={s.small}>/{checked}</span></div><div style={s.muted}>{checkedAt?`Checked ${checkedAt}`:'Checking live endpoints'}</div></aside></section>
    <section style={s.grid}>{channels.map(channel=>{const value=health[channel.key]||{state:'checking' as const,detail:'Checking'};return <article key={channel.key} style={s.card}><div style={s.row}><strong>{channel.label}</strong><span style={{...s.dot,background:tone(value.state)}}/></div><div style={{...s.state,color:tone(value.state)}}>{value.state.toUpperCase()}</div><p style={s.muted}>{value.detail}</p><p style={s.notes}>{channel.notes}</p></article>})}</section>
    <section style={s.two}><article style={s.panel}><div style={s.eyebrow}>SOFÍA AUTONOMY</div><h2>Safe autonomous work</h2>{autonomous.map((x,i)=><div key={x} style={s.item}><b>{String(i+1).padStart(2,'0')}</b><span>{x}</span></div>)}</article><article style={s.panel}><div style={s.eyebrow}>OWNER AUTHORITY</div><h2>Hard gates</h2>{ownerGates.map((x,i)=><div key={x} style={s.item}><b>{String(i+1).padStart(2,'0')}</b><span>{x}</span></div>)}</article></section>
    <section style={s.panel}><div style={s.eyebrow}>COMMERCIAL EVIDENCE LADDER</div><h2>Conversation → CRM → RFQ → Revenue</h2><div style={s.flow}>{['Inbound','Identity reconciled','Intent classified','Requirement verified','RFQ complete','Firm quote','Negotiation','PO / contract','Collected GP'].map((x,i)=><div key={x} style={s.step}><span>{String(i+1).padStart(2,'0')}</span><strong>{x}</strong></div>)}</div><p style={s.muted}>No stage advances because a message was merely sent or received. Each commercial stage requires its own evidence.</p></section>
  </main>
}

const s:Record<string,any>={page:{minHeight:'100vh',background:'radial-gradient(circle at 18% -8%,#12364c 0,#07121f 34%,#04080e 72%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 24px 48px'},header:{maxWidth:1320,margin:'0 auto',minHeight:74,display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',gap:20,padding:'10px 0'},brand:{fontWeight:950,letterSpacing:'.08em',fontSize:14,color:'#fff',textDecoration:'none'},nav:{display:'flex',alignItems:'center',gap:8,flexWrap:'wrap'},link:{color:'#b9c7d3',textDecoration:'none',fontSize:13,padding:'9px'},button:{background:'#66dcff',border:0,borderRadius:10,padding:'10px 13px',fontWeight:900,color:'#021018',cursor:'pointer'},hero:{maxWidth:1320,margin:'0 auto',padding:'64px 0 38px',display:'grid',gridTemplateColumns:'minmax(0,1.8fr) minmax(260px,.7fr)',gap:30,alignItems:'end'},eyebrow:{fontSize:11,fontWeight:950,letterSpacing:'.16em',color:'#66dcff',marginBottom:14},h1:{fontSize:'clamp(44px,5.8vw,82px)',lineHeight:.94,letterSpacing:'-.055em',maxWidth:980,margin:'0 0 22px'},lead:{maxWidth:820,fontSize:17,lineHeight:1.65,color:'#9fb2c1',margin:0},scoreCard:{border:'1px solid rgba(102,220,255,.23)',background:'rgba(6,18,30,.72)',borderRadius:20,padding:24},label:{fontSize:11,letterSpacing:'.14em',fontWeight:900,color:'#9fb2c1'},score:{fontSize:62,fontWeight:950,letterSpacing:'-.06em',lineHeight:1.05,margin:'10px 0'},small:{fontSize:22,color:'#688091'},muted:{color:'#849aab',fontSize:13,lineHeight:1.55},grid:{maxWidth:1320,margin:'0 auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:14},card:{padding:20,border:'1px solid rgba(255,255,255,.09)',borderRadius:16,background:'rgba(8,17,27,.76)'},row:{display:'flex',justifyContent:'space-between',gap:12},dot:{width:10,height:10,borderRadius:999},state:{fontSize:10,fontWeight:950,letterSpacing:'.13em',margin:'18px 0 8px'},notes:{color:'#aab8c3',fontSize:12.5,lineHeight:1.55},two:{maxWidth:1320,margin:'16px auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(340px,1fr))',gap:16},panel:{maxWidth:1320,margin:'16px auto',padding:24,border:'1px solid rgba(255,255,255,.09)',borderRadius:20,background:'rgba(6,14,23,.82)'},item:{display:'grid',gridTemplateColumns:'38px 1fr',gap:10,padding:'11px 0',borderTop:'1px solid rgba(255,255,255,.06)',fontSize:13.5,lineHeight:1.5},flow:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(125px,1fr))',gap:8,marginBottom:16},step:{display:'flex',flexDirection:'column',gap:8,padding:14,borderRadius:12,border:'1px solid rgba(255,255,255,.07)',background:'rgba(255,255,255,.02)',fontSize:12}};
