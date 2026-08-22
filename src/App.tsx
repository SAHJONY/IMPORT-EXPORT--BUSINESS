import {useEffect,useMemo,useState} from 'react';

type Role='owner'|'employee'|'customer';
type ModuleKey='dashboard'|'crm'|'managed-trade'|'global-sourcing'|'compliance'|'documents'|'shipping'|'messages'|'finance'|'ai-brain'|'readiness'|'countries'|'intermediary'|'us-import'|'business-email';
type ModuleConfig={label:string;customerLabel?:string;employeeLabel?:string;group:string;health?:string;data?:string;roles:Role[];description:string};
type RouteState={public:boolean;notFound:boolean;forbidden:boolean;role:Role;section:ModuleKey};

type NavGroup={label:string;items:ModuleKey[]};

const modules:Record<ModuleKey,ModuleConfig>={
 dashboard:{label:'Executive Dashboard',employeeLabel:'My Work',customerLabel:'Home',group:'Command',health:'/health',roles:['owner','employee','customer'],description:'Live operating posture, action queues, workflow launchers and executive decisions.'},
 crm:{label:'CRM & Opportunities',employeeLabel:'Qualification Queue',group:'Commercial',health:'/crm/health',data:'/crm/intakes',roles:['owner','employee'],description:'Customer pipeline, qualification and controlled promotion into sourcing and managed trade.'},
 'global-sourcing':{label:'Global Sourcing',employeeLabel:'Supplier Research',group:'Trade',health:'/global-sourcing/health',data:'/global-sourcing/requests',roles:['owner','employee'],description:'Worldwide supplier discovery, RFQs, candidate evaluation and corridor viability.'},
 'managed-trade':{label:'Managed Trade',employeeLabel:'Trade Cases',group:'Trade',health:'/managed-trade/health',data:'/managed-trade/requests',roles:['owner','employee'],description:'Case-centric execution from qualified need through delivery and reconciliation.'},
 'us-import':{label:'U.S. Import Desk',group:'Trade',health:'/us-import/health',roles:['owner','employee'],description:'HTS classification, customs, broker, IOR, duties, documentation and import controls.'},
 intermediary:{label:'Intermediary Desk',group:'Trade',health:'/intermediary/health',data:'/intermediary/engagements',roles:['owner','employee'],description:'SAHJONY role, compensation, legal-party assignments and engagement economics.'},
 documents:{label:'Documents',customerLabel:'Documents',group:'Operations',health:'/documents/health',data:'/documents',roles:['owner','employee','customer'],description:'Trade-document packages, evidence, certificates and case records.'},
 shipping:{label:'Shipments',customerLabel:'Shipments',group:'Operations',health:'/shipments/health',data:'/shipments',roles:['owner','employee','customer'],description:'Shipment milestones, freight status, delivery evidence and exceptions.'},
 messages:{label:'Communications',customerLabel:'Messages',group:'Operations',health:'/communications/health',data:'/communications/timeline',roles:['owner','employee','customer'],description:'Customer, supplier and partner communications across governed channels.'},
 compliance:{label:'Compliance & Risk',customerLabel:'Trade Status',group:'Risk',health:'/compliance/health',data:'/compliance',roles:['owner','employee','customer'],description:'Restricted-party, sanctions, product, corridor and release evidence.'},
 countries:{label:'Country Intelligence',group:'Risk',health:'/countries/health',data:'/countries',roles:['owner','employee'],description:'Country activation, corridor posture and jurisdiction-level controls.'},
 finance:{label:'Finance & P&L',group:'Finance',health:'/finance/health',data:'/finance/journals',roles:['owner'],description:'Payments, settlement, margin, fees and closeout reconciliation.'},
 'ai-brain':{label:'AI Intelligence',group:'Intelligence',health:'/ai-brain/health',roles:['owner','employee'],description:'Governed multi-model research and decision support without autonomous release authority.'},
 readiness:{label:'Launch Readiness',group:'Administration',health:'/business-readiness/health',data:'/business-readiness/partners',roles:['owner'],description:'Operational partners, integration gates and live-trade certification.'},
 'business-email':{label:'Business Communications',group:'Administration',health:'/business-email/health',data:'/business-email/departments',roles:['owner'],description:'Department identities, routing posture and corporate communications infrastructure.'}
};

const navGroups:Record<Role,NavGroup[]>={
 owner:[
  {label:'Command',items:['dashboard']},
  {label:'Commercial',items:['crm']},
  {label:'Trade',items:['global-sourcing','managed-trade','us-import','intermediary']},
  {label:'Operations',items:['documents','shipping','messages']},
  {label:'Risk & Compliance',items:['compliance','countries']},
  {label:'Finance',items:['finance']},
  {label:'Intelligence',items:['ai-brain']},
  {label:'Administration',items:['readiness','business-email']}
 ],
 employee:[
  {label:'Daily Operations',items:['dashboard','crm']},
  {label:'Trade Work',items:['global-sourcing','managed-trade','us-import','intermediary']},
  {label:'Controls',items:['compliance','documents','shipping','messages','countries']},
  {label:'Intelligence',items:['ai-brain']}
 ],
 customer:[
  {label:'Workspace',items:['dashboard','messages','documents','shipping','compliance']}
 ]
};

const rolePath=(role:Role,section:ModuleKey='dashboard')=>`/${role}${section==='dashboard'?'':'/'+section}`;
const labelFor=(role:Role,key:ModuleKey)=>role==='customer'?(modules[key].customerLabel||modules[key].label):role==='employee'?(modules[key].employeeLabel||modules[key].label):modules[key].label;

function parseRoute():RouteState{
 const p=location.pathname.split('/').filter(Boolean);
 if(!p.length)return {public:true,notFound:false,forbidden:false,role:'customer',section:'dashboard'};
 if(!['owner','employee','customer'].includes(p[0]))return {public:false,notFound:true,forbidden:false,role:'customer',section:'dashboard'};
 const role=p[0] as Role;
 const raw=(p[1]||'dashboard') as ModuleKey;
 if(!(raw in modules))return {public:false,notFound:true,forbidden:false,role,section:'dashboard'};
 if(!modules[raw].roles.includes(role))return {public:false,notFound:false,forbidden:true,role,section:'dashboard'};
 return {public:false,notFound:false,forbidden:false,role,section:raw};
}

function nav(path:string){history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'))}

export default function App(){
 const [route,setRoute]=useState(parseRoute());
 useEffect(()=>{const fn=()=>setRoute(parseRoute());addEventListener('popstate',fn);return()=>removeEventListener('popstate',fn)},[]);
 if(route.public)return <PublicSite/>;
 if(route.notFound)return <RouteStatePage title="Workspace not found" text="The requested SAHJONY workspace does not exist or the link has changed." action="Go to SAHJONY home" path="/"/>;
 if(route.forbidden)return <RouteStatePage title="Access not available" text="This workspace is outside the permissions of the selected role." action="Return to dashboard" path={rolePath(route.role)}/>;
 return <Portal key={route.role} role={route.role} section={route.section}/>;
}

function Brand({compact=false}:{compact?:boolean}){return <button className="brand-button" onClick={()=>nav('/')}><span className="brand-symbol">S</span><span className="brand-copy"><strong>SAHJONY</strong>{!compact&&<small>GLOBAL TRADE</small>}</span></button>}

function PublicSite(){return <div className="public-site institutional-public"><header className="public-nav"><Brand/><nav className="public-links"><a href="#solutions">Solutions</a><a href="#process">How It Works</a><a href="/cuba-private-sector">Cuba Private Sector</a><a className="text-link" href="/owner-login">Sign In</a><a className="primary-link" href="/start">Start a Request</a></nav></header><main><section className="public-hero"><div className="hero-copy"><div className="eyebrow gold">GLOBAL TRADE INFRASTRUCTURE</div><h1>From business need to <span>controlled delivery.</span></h1><p>SAHJONY operates as an AI-enabled global sourcing and managed-trade department—coordinating suppliers, commercial terms, compliance, documentation, logistics, payments and reconciliation across eligible trade corridors.</p><div className="hero-actions"><a className="primary-link large" href="/start">Start a sourcing request</a><a className="secondary-link large" href="#process">See how SAHJONY works</a></div><div className="trust-row"><span>Worldwide sourcing</span><span>Case-based execution</span><span>Fail-closed controls</span><span>Owner-governed releases</span></div></div><div className="global-orbit" aria-label="Global trade operating model"><div className="orbit-core"><span>SAHJONY</span><strong>TRADE OS</strong></div><div className="orbit-ring ring-a"/><div className="orbit-ring ring-b"/><div className="orbit-node n1">SOURCE</div><div className="orbit-node n2">VERIFY</div><div className="orbit-node n3">MOVE</div><div className="orbit-node n4">RECONCILE</div></div></section><section id="solutions" className="public-kpis institutional-kpis"><article><small>COMMERCIAL</small><strong>Find & qualify demand</strong><p>Capture customer need, commercial targets and fit before spending sourcing time.</p></article><article><small>SUPPLY</small><strong>Source worldwide</strong><p>Search globally and compare supplier quality, MOQ, lead time and landed economics.</p></article><article><small>CONTROL</small><strong>Release with evidence</strong><p>Compliance, documents, payment and logistics gates remain explicit and fail-closed.</p></article><article><small>EXECUTION</small><strong>Track to reconciliation</strong><p>Coordinate delivery, exceptions, proof of receipt and final transaction economics.</p></article></section><section id="process" className="institutional-section"><div><div className="eyebrow gold">ONE CONTROLLED WORKFLOW</div><h2>Need → source → qualify → execute → deliver.</h2><p>Every transaction becomes a case with one source of truth for supplier, commercial, compliance, documents, payments, logistics, communications and audit history.</p></div><div className="process-rail">{['Business request','Qualification','Global sourcing','Due diligence','Commercial terms','Release controls','Shipment','Reconciliation'].map((x,i)=><div className="process-node" key={x}><span>{String(i+1).padStart(2,'0')}</span><strong>{x}</strong></div>)}</div></section></main><footer><span>© SAHJONY · Global Trade Operating System</span><span>www.sahjony.com</span></footer></div>}

function RouteStatePage({title,text,action,path}:{title:string;text:string;action:string;path:string}){return <div className="route-state"><Brand/><div className="route-card"><div className="eyebrow gold">SAHJONY GLOBAL TRADE</div><h1>{title}</h1><p>{text}</p><button className="primary-button" onClick={()=>nav(path)}>{action}</button></div></div>}

function Portal({role,section}:{role:Role;section:ModuleKey}){
 const [token,setToken]=useState(()=>safeGet(`sahjony.${role}.token`));
 const [employeeId,setEmployeeId]=useState(()=>safeGet('sahjony.employee.id')||'staff');
 const [health,setHealth]=useState<any>(null);
 const [records,setRecords]=useState<any[]>([]);
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 const [drawer,setDrawer]=useState(false);
 const [searchOpen,setSearchOpen]=useState(false);
 const [query,setQuery]=useState('');

 useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setSearchOpen(v=>!v)}if(e.key==='Escape'){setSearchOpen(false);setDrawer(false)}};addEventListener('keydown',onKey);return()=>removeEventListener('keydown',onKey)},[]);
 useEffect(()=>{if(role==='owner'&&!token&&location.pathname.startsWith('/owner'))location.replace('/owner-login')},[role,token]);
 useEffect(()=>{safeSet(`sahjony.${role}.token`,token)},[token,role]);
 useEffect(()=>{safeSet('sahjony.employee.id',employeeId)},[employeeId]);

 const headers=(json=false)=>{const h:Record<string,string>={'X-Role':role};if(token)h.Authorization=`Bearer ${token}`;if(role==='employee')h['X-Employee-Id']=employeeId;if(json)h['Content-Type']='application/json';return h};
 async function api(path:string,opts:RequestInit={}){const r=await fetch(path,{...opts,headers:{...headers(Boolean(opts.body)),...(opts.headers||{})}});const j=await r.json().catch(()=>({detail:`HTTP ${r.status}`}));if((r.status===401||r.status===403)&&role==='owner'){safeRemove('sahjony.owner.token');setToken('');location.replace('/owner-login');throw new Error('Owner session expired')}if(!r.ok)throw new Error(j.detail||`HTTP ${r.status}`);return j}
 async function refresh(){const cfg=modules[section];setLoading(true);setError('');try{if(cfg.health){const r=await fetch(cfg.health,{cache:'no-store'});setHealth({ok:r.ok,...await r.json().catch(()=>({}))})}if(cfg.data&&token){const j=await api(cfg.data,{cache:'no-store'});const arr=Object.values(j).find(v=>Array.isArray(v)) as any[]|undefined;setRecords(arr||[])}else setRecords([])}catch(e:any){setError(e.message||'Unable to load workspace')}finally{setLoading(false)}}
 useEffect(()=>{refresh();setDrawer(false)},[role,section]);

 const scope=role==='owner'?'OWNER COMMAND':role==='employee'?'EMPLOYEE OPERATIONS':'CUSTOMER PORTAL';
 const searchable=useMemo(()=>navGroups[role].flatMap(g=>g.items.map(k=>({key:k,label:labelFor(role,k),group:g.label,description:modules[k].description}))).filter(x=>`${x.label} ${x.group} ${x.description}`.toLowerCase().includes(query.toLowerCase())),[role,query]);

 function signOut(){safeRemove(`sahjony.${role}.token`);setToken('');if(role==='owner')location.assign('/owner-login');else nav('/')}

 return <div className={`os-shell role-${role}`}>
  <aside className={`os-side ${drawer?'open':''}`}>
   <div className="side-head"><Brand/><button className="close-drawer" onClick={()=>setDrawer(false)}>×</button></div>
   <div className="scope-badge">{scope}</div>
   <nav className="grouped-nav">{navGroups[role].map(group=><section className="nav-group" key={group.label}><small>{group.label}</small>{group.items.map(k=><button key={k} className={section===k?'active':''} onClick={()=>nav(rolePath(role,k))}><span className="nav-dot"/><span>{labelFor(role,k)}</span></button>)}</section>)}{role==='owner'&&<section className="nav-group"><small>Channels</small><button onClick={()=>location.assign('/owner/telegram')}><span className="nav-dot"/><span>Telegram Control</span></button></section>}</nav>
   <div className="side-foot"><span className="security-dot"/><div><strong>{token?'Session active':'Access required'}</strong><small>{role==='owner'?'Owner full scope':role==='employee'?`Employee · ${employeeId}`:'Customer workspace'}</small></div></div>
  </aside>
  {drawer&&<button className="drawer-backdrop" onClick={()=>setDrawer(false)} aria-label="Close navigation"/>}
  <main className="os-main">
   <header className="os-top"><div className="top-left"><button className="mobile-menu" onClick={()=>setDrawer(true)}>☰</button><div className="breadcrumbs"><span>{scope}</span><strong>{labelFor(role,section)}</strong></div></div><div className="top-actions"><button className="search-button" onClick={()=>setSearchOpen(true)}>⌘K <span>Search SAHJONY</span></button><button className="icon-button" title="Refresh" onClick={refresh}>{loading?'…':'↻'}</button><div className="profile-chip"><span className="avatar">{role==='owner'?'O':role==='employee'?'E':'C'}</span><div><strong>{role==='owner'?'Owner':role==='employee'?employeeId:'Customer'}</strong><small>{token?'Authenticated':'Limited access'}</small></div><button onClick={signOut}>Sign out</button></div></div></header>
   {!token&&role!=='owner'?<CredentialGate role={role} employeeId={employeeId} setEmployeeId={setEmployeeId} onToken={setToken}/>:section==='dashboard'?<Dashboard role={role} health={health} token={token} api={api} setError={setError} error={error}/>:section==='crm'?<CRMWorkspace role={role} records={records} refresh={refresh} api={api} error={error}/>:<GenericWorkspace role={role} section={section} cfg={modules[section]} health={health} records={records} loading={loading} error={error} refresh={refresh}/>} 
  </main>
  {searchOpen&&<CommandPalette role={role} query={query} setQuery={setQuery} results={searchable} close={()=>setSearchOpen(false)}/>} 
 </div>
}

function CredentialGate({role,employeeId,setEmployeeId,onToken}:any){const [value,setValue]=useState('');return <section className="credential-gate"><div className="eyebrow gold">SECURE WORKSPACE</div><h1>{role==='employee'?'Employee access':'Customer access'}</h1><p>Authenticate to load protected business records. Credentials remain in this browser session only.</p>{role==='employee'&&<label>Employee ID<input value={employeeId} onChange={e=>setEmployeeId(e.target.value)}/></label>}<label>Access credential<input type="password" value={value} onChange={e=>setValue(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&value)onToken(value)}}/></label><button className="primary-button" onClick={()=>value&&onToken(value)}>Enter workspace</button></section>}

function CommandPalette({role,query,setQuery,results,close}:any){return <div className="command-overlay" onMouseDown={close}><section className="command-palette" onMouseDown={e=>e.stopPropagation()}><div className="command-search"><span>⌕</span><input autoFocus value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search workspaces, sourcing, shipments, compliance…"/><kbd>ESC</kbd></div><div className="command-results">{results.length?results.map((r:any)=><button key={r.key} onClick={()=>{nav(rolePath(role,r.key));close()}}><small>{r.group}</small><strong>{r.label}</strong><span>{r.description}</span></button>):<div className="empty-command">No matching workspace</div>}</div></section></div>}

function Dashboard({role,health,token,api,setError,error}:any){
 const [form,setForm]=useState({customer:'',product_need:'',specifications:'',quantity:'',budget:'',currency:'USD',destination:'US',delivery:''});
 const [snapshot,setSnapshot]=useState({crm:0,trade:0,sourcing:0});
 useEffect(()=>{if(!token||role==='customer')return;Promise.allSettled([api('/crm/intakes',{cache:'no-store'}),api('/managed-trade/requests',{cache:'no-store'}),api('/global-sourcing/requests',{cache:'no-store'})]).then(rs=>{const count=(r:any)=>r.status==='fulfilled'?(Object.values(r.value).find((v:any)=>Array.isArray(v)) as any[]|undefined)?.length||0:0;setSnapshot({crm:count(rs[0]),trade:count(rs[1]),sourcing:count(rs[2])})})},[role,token]);
 async function submit(kind:'trade'|'source'){setError('');try{const base={product_need:form.product_need,specifications:form.specifications||null,quantity:form.quantity?Number(form.quantity):null,target_budget:form.budget?Number(form.budget):null,currency:form.currency,destination_country:form.destination.toUpperCase(),target_delivery_date:form.delivery||null};if(kind==='trade')await api('/managed-trade/requests',{method:'POST',body:JSON.stringify({requester_type:'BUYER',requester_ref:form.customer||null,...base})});else await api('/global-sourcing/requests',{method:'POST',body:JSON.stringify({...base,worldwide_search:true})});nav(rolePath(role,kind==='trade'?'managed-trade':'global-sourcing'))}catch(e:any){setError(e.message)}}
 if(role==='customer')return <CustomerDashboard health={health}/>;
 const owner=role==='owner';
 const stats=owner?[['CRM PIPELINE',snapshot.crm,'Visible intake records'],['TRADE CASES',snapshot.trade,'Managed-trade records'],['SOURCING',snapshot.sourcing,'Global sourcing requests'],['CONTROL POSTURE',health?.production_ready?'READY':'GOVERNED',health?.production_ready?'Production gates satisfied':'Fail-closed controls active']]:[['MY WORK',snapshot.crm,'Qualification records visible'],['TRADE CASES',snapshot.trade,'Execution records visible'],['SOURCING',snapshot.sourcing,'Research requests visible'],['RELEASE AUTHORITY','OWNER','Escalate controlled releases']];
 return <>
  <section className="command-hero executive-hero"><div><div className="eyebrow gold">{owner?'GLOBAL TRADE COMMAND CENTER':'DAILY OPERATIONS'}</div><h1>{owner?'Control the pipeline. See the risk. Move with evidence.':'Work the queue. Resolve blockers. Escalate exceptions.'}</h1><p>{owner?'One operating layer across demand, suppliers, commercial terms, compliance, documents, payments, logistics and reconciliation.':'Your workspace is organized around the next operational action, not the underlying system architecture.'}</p><div className="hero-chip-row"><span>Worldwide sourcing</span><span>Case-based execution</span><span>Owner-governed release</span></div></div><div className="control-posture"><small>PLATFORM STATUS</small><strong>{health?.status==='ok'?'ONLINE':'CHECKING'}</strong><div><span>Release policy</span><b>FAIL-CLOSED</b></div><div><span>AI authority</span><b>ADVISORY</b></div><div><span>Owner scope</span><b>{owner?'FULL':'ESCALATION'}</b></div></div></section>
  <section className="stat-grid institutional-stats">{stats.map(([a,b,c]:any)=><article key={a}><small>{a}</small><strong>{b}</strong><span>{c}</span></article>)}</section>
  {owner&&<section className="executive-grid"><article className="panel trade-network"><div className="panel-head"><div><small>GLOBAL CONTROL PLANE</small><h2>Trade corridor posture</h2></div><span className="live-pill">LIVE MODEL</span></div><div className="network-canvas"><div className="world-line l1"/><div className="world-line l2"/><div className="world-line l3"/><div className="world-hub origin">ORIGIN<br/><b>SUPPLIERS</b></div><div className="world-hub center">SAHJONY<br/><b>CONTROL</b></div><div className="world-hub destination">DESTINATION<br/><b>CUSTOMERS</b></div></div><div className="network-legend"><span><i className="ok-dot"/>Qualified path</span><span><i className="hold-dot"/>Evidence gates</span><span><i className="ai-dot"/>AI advisory</span></div></article><article className="panel ai-brief"><div className="panel-head"><div><small>EXECUTIVE BRIEF</small><h2>What needs attention</h2></div></div><div className="brief-item"><span>01</span><div><strong>{snapshot.crm} intake records visible</strong><small>Review qualification state and promote qualified demand.</small></div></div><div className="brief-item"><span>02</span><div><strong>{snapshot.sourcing} sourcing requests visible</strong><small>Compare supplier candidates and corridor readiness.</small></div></div><div className="brief-item"><span>03</span><div><strong>{snapshot.trade} managed-trade cases visible</strong><small>Focus on holds, documents, logistics and reconciliation.</small></div></div><button className="secondary-button" onClick={()=>nav('/owner/ai-brain')}>Open AI Intelligence</button></article></section>}
  <section className="workspace-section"><div className="section-title"><div><span className="eyebrow">ACTION CENTER</span><h2>{owner?'Create controlled work':'Start assigned trade work'}</h2><p>Launch sourcing or a managed-trade case from one structured business need.</p></div></div><div className="action-form labeled-form"><label>Customer / business reference<input value={form.customer} onChange={e=>setForm({...form,customer:e.target.value})} placeholder="Acme Manufacturing"/></label><label>Product needed<input value={form.product_need} onChange={e=>setForm({...form,product_need:e.target.value})} placeholder="Industrial pump assemblies"/></label><label className="wide-label">Specifications<textarea value={form.specifications} onChange={e=>setForm({...form,specifications:e.target.value})} placeholder="Grade, model, material, packaging, intended use…"/></label><label>Quantity<input value={form.quantity} onChange={e=>setForm({...form,quantity:e.target.value})} placeholder="500"/></label><label>Target budget<input value={form.budget} onChange={e=>setForm({...form,budget:e.target.value})} placeholder="50000"/></label><label>Currency<select value={form.currency} onChange={e=>setForm({...form,currency:e.target.value})}><option>USD</option><option>EUR</option><option>GBP</option><option>CAD</option><option>JPY</option></select></label><label>Destination country<input value={form.destination} onChange={e=>setForm({...form,destination:e.target.value})} placeholder="US"/></label><label>Target delivery date<input type="date" value={form.delivery} onChange={e=>setForm({...form,delivery:e.target.value})}/></label><div className="action-buttons"><button onClick={()=>submit('trade')}>Create Managed Trade Case</button><button className="secondary" onClick={()=>submit('source')}>Launch Global Sourcing</button></div></div>{error&&<div className="error">{error}</div>}</section>
  <Pipeline/>
 </>
}

function CustomerDashboard({health}:any){return <><section className="command-hero customer-hero"><div><div className="eyebrow gold">YOUR GLOBAL TRADE WORKSPACE</div><h1>Know what is happening with every request.</h1><p>Submit what your business needs and follow quotes, messages, documents, shipment progress and trade status from one place.</p><div className="hero-actions"><a className="primary-link large" href="/start">Start a new request</a></div></div><div className="control-posture"><small>PLATFORM</small><strong>{health?.status==='ok'?'ONLINE':'CHECKING'}</strong><div><span>Requests</span><b>TRACKED</b></div><div><span>Documents</span><b>SECURE</b></div><div><span>Shipments</span><b>VISIBLE</b></div></div></section><section className="customer-journey">{[['1','Request submitted','Tell us what you need.'],['2','SAHJONY sourcing','We qualify and source eligible suppliers.'],['3','Quote & trade plan','Review commercial terms and required controls.'],['4','Execution & delivery','Follow documents, shipment and delivery status.']].map(([n,a,b])=><article key={n}><span>{n}</span><strong>{a}</strong><small>{b}</small></article>)}</section><section className="workspace-section"><div className="section-title"><div><span className="eyebrow">QUICK ACCESS</span><h2>Your business workspace</h2></div></div><div className="customer-actions"><button onClick={()=>nav('/customer/messages')}>Messages<span>See communications and updates</span></button><button onClick={()=>nav('/customer/documents')}>Documents<span>View trade evidence and files</span></button><button onClick={()=>nav('/customer/shipping')}>Shipments<span>Track logistics milestones</span></button><button onClick={()=>nav('/customer/compliance')}>Trade Status<span>See required controls and status</span></button></div></section></>}

function Pipeline(){return <section className="workspace-section"><div className="section-title"><div><span className="eyebrow">CASE LIFECYCLE</span><h2>Request → reconciled delivery</h2></div></div><div className="pipeline-rail">{['Intake','Qualify','Source','Due diligence','Commercial','Release','Deliver','Reconcile'].map((x,i)=><article key={x}><span>{String(i+1).padStart(2,'0')}</span><strong>{x}</strong></article>)}</div></section>}

function CRMWorkspace({role,records,refresh,api,error}:any){
 async function act(id:string,status:'QUALIFIED'|'NEEDS_INFO'|'DISQUALIFIED'){try{await api(`/crm/intakes/${id}/qualify`,{method:'PATCH',body:JSON.stringify({status,assigned_employee_id:role==='employee'?safeGet('sahjony.employee.id')||'staff':null})});refresh()}catch{}}
 async function promote(id:string){try{await api(`/crm/intakes/${id}/promote`,{method:'POST'});refresh()}catch{}}
 return <section className="workspace-section full-height-section"><div className="section-title"><div><span className="eyebrow">COMMERCIAL PIPELINE</span><h1>{role==='owner'?'CRM & Opportunities':'Qualification Queue'}</h1><p>Qualify demand before committing sourcing time, supplier outreach or transaction resources.</p></div><a className="primary-action" href="/start">New customer intake</a></div>{error&&<div className="error">{error}</div>}<div className="records-toolbar"><span>{records.length} records visible</span><button className="secondary-button" onClick={refresh}>Refresh</button></div><div className="record-list institutional-records">{records.length?records.map((r:any,i:number)=>{const id=r.intake_id||r.id||String(i+1);const status=r.status||'NEW';return <article key={id}><div className="record-primary"><small>{status}</small><strong>{r.legal_name||r.business_name||r.contact_name||r.product_need||'Trade opportunity'}</strong><span>{r.product_need||r.email||id}</span></div><div className="record-meta"><span><small>Destination</small><b>{r.destination_country||r.country_code||'—'}</b></span><span><small>Budget</small><b>{r.target_budget?`${r.currency||'USD'} ${r.target_budget}`:'—'}</b></span><span><small>Assigned</small><b>{r.assigned_employee_id||'Unassigned'}</b></span></div><div className="record-actions"><button onClick={()=>act(id,'QUALIFIED')}>Qualify</button><button className="secondary" onClick={()=>act(id,'NEEDS_INFO')}>Need info</button><button className="secondary" onClick={()=>promote(id)}>Promote</button></div></article>}):<EmptyState text="No CRM records are visible for this session."/>}</div></section>}

function GenericWorkspace({role,section,cfg,health,records,loading,error,refresh}:any){
 const [selected,setSelected]=useState<any>(null);
 const state=health?.status||health?.service||health?.ok?'ONLINE':'CHECKING';
 return <><section className="module-hero institutional-module"><div><div className="eyebrow gold">{cfg.group.toUpperCase()}</div><h1>{labelFor(role,section)}</h1><p>{customerDescription(role,section,cfg.description)}</p><div className="hero-chip-row"><span>Case-linked evidence</span><span>Role-aware access</span><span>Fail-closed controls</span></div></div><div className={`runtime-badge ${health?.ok||health?.status==='ok'?'ok':''}`}><small>MODULE STATUS</small><span>{state}</span><button className="secondary-button compact" onClick={refresh}>{loading?'Refreshing…':'Refresh data'}</button></div></section>{error&&<div className="error-banner">{error}</div>}<section className="records-card standalone institutional-card"><div className="section-title"><div><small>{cfg.group}</small><h2>{role==='customer'?'Your records':'Visible operating records'}</h2></div><span>{records.length} records</span></div>{records.length?<div className="case-table">{records.slice(0,100).map((r:any,i:number)=>{const values=Object.entries(r).filter(([,v])=>v!==null&&v!==''&&typeof v!=='object').slice(0,4);return <button className="case-row" key={r.id||r.request_id||r.intake_id||i} onClick={()=>setSelected(r)}><span className="case-index">{String(i+1).padStart(2,'0')}</span><span className="case-main"><strong>{String(r.product_need||r.legal_name||r.title||r.status||r.request_id||r.id||`Record ${i+1}`)}</strong><small>{values.slice(1).map(([,v])=>String(v)).join(' · ').slice(0,120)||'Open record details'}</small></span><span className="case-status">{String(r.status||r.state||'OPEN')}</span><span className="case-open">Open →</span></button>)}</div>:<EmptyState text={role==='customer'?'Nothing is waiting here right now.':'No records are visible for this module and session.'}/>}</section>{selected&&<CaseDrawer record={selected} title={labelFor(role,section)} close={()=>setSelected(null)}/>}</>}

function CaseDrawer({record,title,close}:any){return <div className="case-overlay" onMouseDown={close}><aside className="case-drawer" onMouseDown={e=>e.stopPropagation()}><div className="case-drawer-head"><div><small>CASE VIEW · {title}</small><h2>{record.product_need||record.legal_name||record.title||record.request_id||record.id||'Operating record'}</h2></div><button onClick={close}>×</button></div><div className="case-tabs"><span className="active">Overview</span><span>Documents</span><span>Messages</span><span>Timeline</span></div><div className="case-fields">{Object.entries(record).filter(([,v])=>v!==null&&v!==''&&typeof v!=='object').map(([k,v])=><div key={k}><small>{k.replaceAll('_',' ')}</small><strong>{String(v)}</strong></div>)}</div><div className="case-governance"><span className="security-dot"/><p>This view preserves the source record. Trade releases, payments and compliance decisions remain governed by their existing backend controls.</p></div></aside></div>}

function EmptyState({text}:{text:string}){return <div className="empty-state"><span>◇</span><strong>No active records</strong><p>{text}</p></div>}

function customerDescription(role:Role,section:ModuleKey,defaultText:string){if(role!=='customer')return defaultText;const map:Partial<Record<ModuleKey,string>>={messages:'Read updates and communications related to your SAHJONY requests.',documents:'View trade documents and evidence shared with your business.',shipping:'Follow shipment milestones, logistics progress and delivery status.',compliance:'See the current trade-status controls that affect your request.'};return map[section]||defaultText}

function safeGet(key:string){try{return sessionStorage.getItem(key)||''}catch{return ''}}
function safeSet(key:string,value:string){try{if(value)sessionStorage.setItem(key,value);else sessionStorage.removeItem(key)}catch{}}
function safeRemove(key:string){try{sessionStorage.removeItem(key)}catch{}}
