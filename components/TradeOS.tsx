'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

type Role='owner'|'employee'|'customer';
type ModuleKey='command'|'messages'|'documents'|'shipping'|'compliance'|'operations'|'finance'|'sharing'|'language';

type Props={slug:string[]};

const modules:Record<ModuleKey,{label:string;health?:string;data?:string;ownerOnly?:boolean;customer?:boolean}>={
  command:{label:'Command Center',health:'/health'},
  messages:{label:'Communications',health:'/communications/health',data:'/communications/timeline',customer:true},
  documents:{label:'Documents',health:'/documents/health',data:'/documents',customer:true},
  shipping:{label:'Shipping',health:'/shipments/health',data:'/shipments',customer:true},
  compliance:{label:'Compliance',health:'/compliance/health',data:'/compliance',customer:true},
  operations:{label:'Commercial Ops',health:'/commercial/health',data:'/commercial/readiness'},
  finance:{label:'Finance',health:'/finance/health',data:'/finance/journals'},
  sharing:{label:'Sharing',health:'/collaboration/health',data:'/collaboration/grants'},
  language:{label:'Language',health:'/language/health',data:'/language/preferences',customer:true},
};

function titleCase(v:string){return v.replaceAll('_',' ').replace(/\b\w/g,x=>x.toUpperCase())}
function infer(slug:string[]):{role:Role;section:ModuleKey}{
  const r=(slug[0]==='owner'||slug[0]==='customer'||slug[0]==='employee'?slug[0]:'employee') as Role;
  const raw=slug[1]||'command';
  const section=(Object.prototype.hasOwnProperty.call(modules,raw)?raw:'command') as ModuleKey;
  return {role:r,section};
}

export default function TradeOS({slug}:Props){
  const router=useRouter();
  const {role,section}=useMemo(()=>infer(slug),[slug]);
  const [token,setToken]=useState('');
  const [employeeId,setEmployeeId]=useState('staff');
  const [health,setHealth]=useState<any>(null);
  const [records,setRecords]=useState<any[]>([]);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [lastRefresh,setLastRefresh]=useState<Date|null>(null);

  useEffect(()=>{
    setToken(sessionStorage.getItem('sahjony.token')||'');
    setEmployeeId(sessionStorage.getItem('sahjony.employee')||'staff');
  },[]);
  useEffect(()=>{sessionStorage.setItem('sahjony.token',token)},[token]);
  useEffect(()=>{sessionStorage.setItem('sahjony.employee',employeeId)},[employeeId]);

  const headers=()=>{
    const h:Record<string,string>={'X-Role':role};
    if(token)h.Authorization=`Bearer ${token}`;
    if(role==='employee')h['X-Employee-Id']=employeeId||'staff';
    return h;
  };

  async function refresh(){
    setLoading(true);setError('');
    const config=modules[section];
    try{
      if(config.health){
        const hr=await fetch(config.health,{cache:'no-store'});
        const hj=await hr.json().catch(()=>({status:hr.status}));
        setHealth({ok:hr.ok,...hj});
      }
      if(config.data){
        if(!token){setRecords([]);setError('Enter your role credential to load live business data.');return}
        const r=await fetch(config.data,{headers:headers(),cache:'no-store'});
        const j=await r.json().catch(()=>({detail:`HTTP ${r.status}`}));
        if(!r.ok)throw new Error(j.detail||`HTTP ${r.status}`);
        const arr=Object.values(j).find(v=>Array.isArray(v)) as any[]|undefined;
        setRecords(arr||[j]);
      }else setRecords([]);
      setLastRefresh(new Date());
    }catch(e:any){setRecords([]);setError(e?.message||'Unable to load live data')}finally{setLoading(false)}
  }

  useEffect(()=>{refresh()},[role,section]);

  const visible=(Object.entries(modules) as [ModuleKey,(typeof modules)[ModuleKey]][]).filter(([key,m])=>{
    if(role==='customer')return key==='command'||m.customer;
    if(role==='employee')return !m.ownerOnly;
    return true;
  });

  const go=(key:ModuleKey)=>router.push(`/${role}/${key==='command'?'':key}`.replace(/\/$/,''));
  const healthOk=health?.ok!==false && (health?.status==='ok'||health?.status==='healthy'||health?.status==='ready'||health?.ok===true);
  const readiness=health?.readiness?.score??health?.score??null;

  return <div className="app">
    <aside className="side">
      <div className="brand">SAHJONY GLOBAL TRADE</div>
      <div className="sub">Live Import · Export Operating System</div>
      <div className="nav">{visible.map(([key,m])=><button key={key} className={key===section?'active':''} onClick={()=>go(key)}>{m.label}</button>)}</div>
    </aside>
    <main className="main">
      <div className="topbar">
        <div><div className="role">{role.toUpperCase()} · LIVE WORKSPACE</div><div className="sub">{lastRefresh?`Last refreshed ${lastRefresh.toLocaleTimeString()}`:'Connecting to runtime…'}</div></div>
        <div className="controls">
          <select value={role} onChange={e=>router.push(`/${e.target.value}`)}><option value="owner">Owner</option><option value="employee">Employee</option><option value="customer">Customer</option></select>
          <input type="password" value={token} onChange={e=>setToken(e.target.value)} placeholder={`${titleCase(role)} credential`}/>
          {role==='employee'&&<input value={employeeId} onChange={e=>setEmployeeId(e.target.value)} placeholder="Employee ID"/>}
          <button className="btn" onClick={refresh}>Refresh live data</button>
        </div>
      </div>

      <section className="hero">
        <div className="eyebrow">{modules[section].label.toUpperCase()}</div>
        <h1>{section==='command'?'Operate the trade.\nNot the screen.':modules[section].label}</h1>
        <p>This workspace is stateful and API-driven. Changes in trade operations, documents, shipments, compliance, finance, communications and participant access are loaded from the backend instead of being painted into a static dashboard.</p>
      </section>

      <div className="grid">
        <div className="card"><h3>Runtime</h3><div className="metric"><span className={`status-dot ${healthOk?'ok':health?'bad':''}`}/>{health?healthOk?'Connected':'Attention':'Checking'}</div></div>
        <div className="card"><h3>Visible records</h3><div className="metric">{records.length}</div></div>
        <div className="card"><h3>Production readiness</h3><div className="metric">{readiness!==null?`${readiness}%`:'Live gate'}</div></div>
        <div className="card"><h3>Access model</h3><div className="metric" style={{fontSize:18}}>{role==='owner'?'Executive':'Scoped'}</div></div>
      </div>

      {error&&<div className="error">{error}</div>}
      <section className={`section ${loading?'loading':''}`}>
        <div className="section-head"><div><h2>Live {modules[section].label}</h2><div className="sub">Fetched from {modules[section].data||modules[section].health||'runtime'}</div></div><button className="btn secondary" onClick={refresh}>{loading?'Refreshing…':'Reload'}</button></div>
        {!records.length&&!loading&&!error&&<div className="empty">No live records are available in this scope yet.</div>}
        <div className="table">{records.slice(0,25).map((r,i)=>{
          const entries=Object.entries(r||{}).filter(([,v])=>['string','number','boolean'].includes(typeof v)).slice(0,4);
          return <div className="row" key={r?.id||r?.document_id||r?.shipment_id||r?.event_id||i}>{entries.length?entries.map(([k,v])=><div key={k}><small>{titleCase(k)}</small><div>{String(v??'—')}</div></div>):<div>{JSON.stringify(r)}</div>}</div>
        })}</div>
      </section>

      <section className="section"><div className="section-head"><h2>Operating signals</h2><span className="muted">Live-state behavior</span></div><div className="activity">
        <div className="activity-item"><strong>Navigation changes application state</strong><span>No static HTML page swap is required.</span></div>
        <div className="activity-item"><strong>Backend failures are visible</strong><span>Loading, permission and runtime errors render directly in the workspace.</span></div>
        <div className="activity-item"><strong>Role credentials persist per session</strong><span>Owner, employee and customer scopes use their real API authorization headers.</span></div>
      </div></section>
    </main>
  </div>;
}
