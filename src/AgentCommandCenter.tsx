import {useEffect,useState} from 'react';
import './agent-command.css';
type Probe={key:string;name:string;kind:string;endpoint?:string;detail:string;primary?:boolean};
type Health={ok:boolean;detail:string;checkedAt:string};
const probes:Probe[]=[
 {key:'platform',name:'SAHJONY Platform',kind:'CORE',endpoint:'/api/health',detail:'Trading OS and command APIs'},
 {key:'tinyfish',name:'TinyFish Live Browser',kind:'PRIMARY BROWSER',detail:'Isolated cloud browser execution',primary:true},
 {key:'codex',name:'Codex / ChatGPT',kind:'AGENT BRAIN',detail:'Planning, coding and tool orchestration'},
 {key:'desktop',name:'Remote Desktop Commander',kind:'MAC BRIDGE',detail:'Authorized filesystem and terminal access'},
 {key:'opera',name:'Opera Connector',kind:'FALLBACK',detail:'Local authenticated browser fallback'},
 {key:'guardian',name:'Connection Guardian',kind:'RECOVERY',detail:'Local application and network watchdog'},
];
const pipeline=[['01','INTAKE','Governed request'],['02','PLAN','Tools + limits'],['03','EXECUTE','Least privilege'],['04','VERIFY','Evidence check'],['05','REPORT','Owner outcome']];
const activity=[['TinyFish','Ready for isolated browser work','ON DEMAND'],['Remote Mac','Execution requires live connector','VERIFY AT RUN'],['Opera','Manual session fallback','FALLBACK']];
export default function AgentCommandCenter(){
 const [health,setHealth]=useState<Record<string,Health>>({});const [loading,setLoading]=useState(true);
 async function refresh(){setLoading(true);const checkedAt=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});try{const r=await fetch('/api/health',{cache:'no-store',headers:{accept:'application/json'}});setHealth({platform:{ok:r.ok,detail:r.ok?'Operational':`HTTP ${r.status}`,checkedAt}})}catch(e){setHealth({platform:{ok:false,detail:e instanceof Error?e.message:'Unavailable',checkedAt}})}finally{setLoading(false)}}
 useEffect(()=>{void refresh();const id=window.setInterval(()=>void refresh(),60000);return()=>window.clearInterval(id)},[]);
 const platform=health.platform;
 return <main className="agent-wallboard">
  <header className="agent-top"><a href="/owner/dashboard" className="agent-brand">SAHJONY <span>AGENT OS</span></a><nav><span>OWNER · FAIL-CLOSED</span><button onClick={()=>void refresh()} disabled={loading}>{loading?'Checking…':'↻ Refresh'}</button><a href="/owner/dashboard">Dashboard</a></nav></header>
  <section className="agent-hero"><div><small>AGENTIC OPERATIONS · TINYFISH ENABLED</small><h1>AI Agent<br/><em>Command Center</em></h1><p>One owner-controlled screen for agents, browsers, tools, approvals, health and evidence. Automation stays inside explicit permissions.</p></div><aside><small>VERIFIED PLATFORM HEALTH</small><strong className={platform?.ok?'ok':'warn'}>{platform?.ok?'ONLINE':loading?'CHECKING':'ATTENTION'}</strong><span>{platform?.detail||'Starting live probe'} · {platform?.checkedAt||'now'}</span><i>External connectors verify at execution time.</i></aside></section>
  <section className="agent-grid" aria-label="Agent system layers">{probes.map(p=>{const h=health[p.key];return <article key={p.key} className={p.primary?'primary':''}><div><small>{p.kind}</small><b className={h?.ok?'ok':''}>{h?h.ok?'LIVE':'ATTENTION':'ON DEMAND'}</b></div><h2>{p.name}</h2><p>{h?.detail||p.detail}</p><footer>{p.primary?'DEFAULT EXECUTION LAYER':'CONTROLLED ACCESS'}</footer></article>})}</section>
  <section className="agent-main-grid"><article className="agent-panel"><header><small>EXECUTION PIPELINE</small><h2>Request → verified result</h2></header><div className="agent-pipeline">{pipeline.map(([n,k,t])=><div key={n}><b>{n}</b><small>{k}</small><strong>{t}</strong></div>)}</div></article><article className="agent-panel"><header><small>AUTHORITY MATRIX</small><h2>Policy boundaries</h2></header><div className="authority"><div><b>AUTO</b><span>Read, analyze, draft, test and monitor</span></div><div><b>GATED</b><span>Send, publish, purchase, deploy or change settings</span></div><div><b>BLOCKED</b><span>Bypass MFA, consent or permissions</span></div></div></article></section>
  <section className="agent-main-grid lower"><article className="agent-panel"><header><small>CONNECTOR POSTURE</small><h2>Execution readiness</h2></header><div className="activity">{activity.map(([a,b,c])=><div key={a}><i/><strong>{a}</strong><span>{b}</span><b>{c}</b></div>)}</div></article><article className="agent-panel metric-panel"><header><small>SUCCESS SCOREBOARD</small><h2>30-day targets</h2></header><div><span><b>≥99%</b> platform availability</span><span><b>≥90%</b> low-risk task success</span><span><b>0</b> unauthorized actions</span></div></article></section>
  <footer className="agent-bottom"><div><small>RECOMMENDED STACK</small><strong>Codex → TinyFish → Remote Desktop → Opera fallback</strong></div><div><small>CONTROL PRINCIPLE</small><strong>AI recommends · Owner governs · Evidence releases</strong></div></footer>
 </main>
}
