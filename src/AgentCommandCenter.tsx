import {useEffect,useMemo,useState} from 'react';
import './agent-command.css';
type State={ok:boolean;detail:string};
const services=[
 {key:'platform',name:'SAHJONY Platform',kind:'Core',endpoint:'/api/health',detail:'SAHJONY LLC platform and command APIs'},
 {key:'tinyfish',name:'TinyFish Live Browser',kind:'Cloud browser',detail:'Primary isolated web execution'},
 {key:'codex',name:'Codex / ChatGPT',kind:'Agent brain',detail:'Planning, code and tool orchestration'},
 {key:'desktop',name:'Remote Desktop Commander',kind:'Mac bridge',detail:'Authorized filesystem and terminal access'},
 {key:'opera',name:'Opera Connector',kind:'Fallback browser',detail:'Manual authenticated-session fallback'},
 {key:'guardian',name:'Connection Guardian',kind:'Recovery',detail:'Local app and network watchdog'},
];
const lanes=[
 ['01','INTAKE','Request captured','Waiting for a governed task'],
 ['02','PLAN','Agent decomposes work','Tools selected by least privilege'],
 ['03','EXECUTE','TinyFish or connected tool','Actions remain policy-bound'],
 ['04','VERIFY','Evidence and health checks','Result checked before release'],
 ['05','REPORT','Owner-visible outcome','Audit-ready status and next move'],
];
export default function AgentCommandCenter(){
 const [health,setHealth]=useState<Record<string,State>>({});
 const [checked,setChecked]=useState('');
 async function refresh(){
  const next:Record<string,State>={};
  try{const r=await fetch('/api/health',{cache:'no-store'});next.platform={ok:r.ok,detail:r.ok?'Operational':`HTTP ${r.status}`}}catch(e){next.platform={ok:false,detail:e instanceof Error?e.message:'Unavailable'}}
  setHealth(next);setChecked(new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}));
 }
 useEffect(()=>{void refresh();const id=setInterval(()=>void refresh(),60000);return()=>clearInterval(id)},[]);
 const ready=useMemo(()=>Object.values(health).filter(x=>x.ok).length,[health]);
 return <main className="agent-wallboard">
  <header className="agent-top"><a href="/owner/dashboard" className="agent-brand">SAHJONY <span>AGENT OS</span></a><div className="agent-actions"><span>OWNER CONTROL · FAIL-CLOSED</span><button onClick={()=>void refresh()}>↻ Refresh</button><a href="/owner/dashboard">Dashboard</a></div></header>
  <section className="agent-hero"><div><small>MANUS-STYLE OPERATIONS · TINYFISH ENABLED</small><h1>AI Agent<br/><em>Command Center</em></h1><p>One large-screen control plane for agents, browsers, tools, approvals, health and evidence. Autonomous execution stays inside permissions; consequential actions require an explicit gate.</p></div><div className="agent-score"><small>VERIFIED PLATFORM HEALTH</small><strong>{health.platform?.ok?'ONLINE':'CHECKING'}</strong><span>{ready}/1 locally probeable · {checked||'starting'}</span><i>External connectors are verified at execution time.</i></div></section>  <section className="agent-grid">{services.map(s=>{const local=s.endpoint?health[s.key]:undefined;return <article key={s.key} className={`agent-card ${local?.ok?'ready':''}`}><div><small>{s.kind}</small><b className={local?.ok?'green':'cyan'}>{local?local.ok?'LIVE':'ATTENTION':'ON-DEMAND'}</b></div><h2>{s.name}</h2><p>{local?.detail||s.detail}</p><span>{s.key==='tinyfish'?'PRIMARY BROWSER':s.key==='opera'?'FALLBACK ONLY':'CONTROLLED ACCESS'}</span></article>})}</section>
  <section className="agent-panels"><article><header><small>EXECUTION PIPELINE</small><h2>From request to verified result</h2></header><div className="agent-lanes">{lanes.map(([n,k,t,d])=><div key={n}><b>{n}</b><small>{k}</small><strong>{t}</strong><span>{d}</span></div>)}</div></article><article><header><small>AUTHORITY MATRIX</small><h2>What the system may do</h2></header><div className="authority"><div><b>AUTO</b><span>Read, research, analyze, draft, test, monitor health</span></div><div><b>GATED</b><span>Send, publish, purchase, deploy, change accounts or settings</span></div><div><b>BLOCKED</b><span>Bypass MFA, permissions, consent or safety controls</span></div></div></article></section>
  <section className="agent-footer"><div><small>RECOMMENDED OPERATING STACK</small><strong>Codex → TinyFish → Remote Desktop → Opera fallback</strong></div><div><small>SUCCESS METRICS</small><strong>Uptime · task success · verified evidence · recovery time · zero unauthorized actions</strong></div></section>
 </main>
}
