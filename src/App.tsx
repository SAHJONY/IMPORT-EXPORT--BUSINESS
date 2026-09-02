import {useEffect,useMemo,useRef,useState} from 'react';
import {useCinematicMotion} from './useCinematicMotion';

type Role='owner'|'employee'|'customer';
type ModuleKey='dashboard'|'crm'|'global-sourcing'|'managed-trade'|'us-import'|'intermediary'|'documents'|'shipping'|'messages'|'compliance'|'countries'|'finance'|'ai-brain'|'readiness'|'business-email';
type ModuleConfig={label:string;employeeLabel?:string;customerLabel?:string;group:string;health?:string;data?:string;roles:Role[];description:string};
type RouteState={public:boolean;notFound:boolean;forbidden:boolean;role:Role;section:ModuleKey};

const modules:Record<ModuleKey,ModuleConfig>={
 dashboard:{label:'Executive Dashboard',employeeLabel:'My Work',customerLabel:'Home',group:'Command',health:'/health',roles:['owner','employee','customer'],description:'Operating posture, decisions, queues and next actions.'},
 crm:{label:'CRM & Opportunities',employeeLabel:'Qualification Queue',group:'Commercial',health:'/crm/health',data:'/crm/intakes',roles:['owner','employee'],description:'Qualify demand and promote viable opportunities into sourcing and managed trade.'},
 'global-sourcing':{label:'Global Sourcing',employeeLabel:'Supplier Research',group:'Trade',health:'/global-sourcing/health',data:'/global-sourcing/requests',roles:['owner','employee'],description:'Worldwide supplier discovery, RFQs, candidate comparison and corridor viability.'},
 'managed-trade':{label:'Managed Trade',employeeLabel:'Trade Cases',group:'Trade',health:'/managed-trade/health',data:'/managed-trade/requests',roles:['owner','employee'],description:'Case-centric execution from qualified need through delivery and reconciliation.'},
 'us-import':{label:'U.S. Import Desk',group:'Trade',health:'/us-import/health',roles:['owner','employee'],description:'HTS, customs, broker, IOR, duties, documents and import controls.'},
 intermediary:{label:'Intermediary Desk',group:'Trade',health:'/intermediary/health',data:'/intermediary/engagements',roles:['owner','employee'],description:'SAHJONY role, compensation, party assignments and engagement economics.'},
 documents:{label:'Documents',customerLabel:'Documents',group:'Operations',health:'/documents/health',data:'/documents',roles:['owner','employee','customer'],description:'Trade-document packages, evidence, certificates and records.'},
 shipping:{label:'Shipments',customerLabel:'Shipments',group:'Operations',health:'/shipments/health',data:'/shipments',roles:['owner','employee','customer'],description:'Logistics milestones, freight status, delivery evidence and exceptions.'},
 messages:{label:'Communications',customerLabel:'Messages',group:'Operations',health:'/communications/health',data:'/communications/timeline',roles:['owner','employee','customer'],description:'Customer, supplier and partner communications.'},
 compliance:{label:'Compliance & Risk',customerLabel:'Trade Status',group:'Risk',health:'/compliance/health',data:'/compliance',roles:['owner','employee','customer'],description:'Restricted-party, sanctions, product, corridor and release evidence.'},
 countries:{label:'Country Intelligence',group:'Risk',health:'/countries/health',data:'/countries',roles:['owner','employee'],description:'Country activation and corridor controls.'},
 finance:{label:'Finance & P&L',group:'Finance',health:'/finance/health',data:'/finance/journals',roles:['owner'],description:'Payments, settlement, margin, fees and reconciliation.'},
 'ai-brain':{label:'AI Intelligence',group:'Intelligence',health:'/ai-brain/health',roles:['owner','employee'],description:'Governed multi-model research and decision support.'},
 readiness:{label:'Launch Readiness',group:'Administration',health:'/business-readiness/health',data:'/business-readiness/partners',roles:['owner'],description:'Operational partners, integration gates and live-trade certification.'},
 'business-email':{label:'Business Communications',group:'Administration',health:'/business-email/health',data:'/business-email/departments',roles:['owner'],description:'Department identities and corporate communications infrastructure.'}
};

const ownerGroups:[string,ModuleKey[]][]=[['Command',['dashboard']],['Commercial',['crm']],['Trade',['global-sourcing','managed-trade','us-import','intermediary']],['Operations',['documents','shipping','messages']],['Risk & Compliance',['compliance','countries']],['Finance',['finance']],['Intelligence',['ai-brain']],['Administration',['readiness','business-email']]];
const employeeGroups:[string,ModuleKey[]][]=[['Daily Operations',['dashboard','crm']],['Trade Work',['global-sourcing','managed-trade','us-import','intermediary']],['Controls',['compliance','documents','shipping','messages','countries']],['Intelligence',['ai-brain']]];
const customerGroups:[string,ModuleKey[]][]=[['Workspace',['dashboard','messages','documents','shipping','compliance']]];
const publicCapabilities=[
 ['01','INTELLIGENCE','Discover verified supply','Research manufacturers, distributors and wholesalers across qualified global corridors.'],
 ['02','COMMERCE','Structure the opportunity','Compare product fit, terms, landed economics and the commercial path before execution.'],
 ['03','CONTROL','Protect every release','Keep compliance, documents, counterparties, payments and approvals tied to evidence.'],
 ['04','DELIVERY','Command the movement','Track logistics, exceptions and final reconciliation from one operating record.']
] as const;
const publicStages=['Business request','Qualification','Global sourcing','Due diligence','Commercial terms','Release controls','Shipment','Reconciliation'] as const;

const groupsFor=(role:Role)=>role==='owner'?ownerGroups:role==='employee'?employeeGroups:customerGroups;
const rolePath=(role:Role,section:ModuleKey='dashboard')=>`/${role}${section==='dashboard'?'':'/'+section}`;
const labelFor=(role:Role,key:ModuleKey)=>role==='customer'?(modules[key].customerLabel||modules[key].label):role==='employee'?(modules[key].employeeLabel||modules[key].label):modules[key].label;
const safeGet=(key:string)=>{try{return sessionStorage.getItem(key)||''}catch{return ''}};
const safeSet=(key:string,value:string)=>{try{if(value)sessionStorage.setItem(key,value);else sessionStorage.removeItem(key)}catch{}};
const safeRemove=(key:string)=>{try{sessionStorage.removeItem(key)}catch{}};
function nav(path:string){history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'))}

function route():RouteState{
 const parts=location.pathname.split('/').filter(Boolean);
 if(!parts.length)return {public:true,notFound:false,forbidden:false,role:'customer',section:'dashboard'};
 if(!['owner','employee','customer'].includes(parts[0]))return {public:false,notFound:true,forbidden:false,role:'customer',section:'dashboard'};
 const role=parts[0] as Role;
 const section=(parts[1]||'dashboard') as ModuleKey;
 if(!(section in modules))return {public:false,notFound:true,forbidden:false,role,section:'dashboard'};
 if(!modules[section].roles.includes(role))return {public:false,notFound:false,forbidden:true,role,section:'dashboard'};
 return {public:false,notFound:false,forbidden:false,role,section};
}

export default function App(){
 const [r,setR]=useState(route());
 useCinematicMotion(`${r.public?'public':r.role}:${r.section}`);
 useEffect(()=>{const fn=()=>setR(route());addEventListener('popstate',fn);return()=>removeEventListener('popstate',fn)},[]);
 if(r.public)return <PublicSite/>;
 if(r.notFound)return <StatePage title="Workspace not found" text="The requested SAHJONY workspace does not exist or the link has changed." path="/"/>;
 if(r.forbidden)return <StatePage title="Access not available" text="This workspace is outside the permissions of this role." path={rolePath(r.role)}/>;
 return <Portal key={r.role} role={r.role} section={r.section}/>;
}

function Brand({ownerShortcut=false}:{ownerShortcut?:boolean}){
 const clicks=useRef(0);
 const reset=useRef<number|undefined>(undefined);
 function activate(){
  if(!ownerShortcut){nav('/');return}
  clicks.current+=1;
  if(reset.current)window.clearTimeout(reset.current);
  if(clicks.current>=3){clicks.current=0;location.assign('/owner-login');return}
  reset.current=window.setTimeout(()=>{clicks.current=0},800);
 }
 return <button className="brand-button" onClick={activate} aria-label="SAHJONY LLC home"><span className="brand-symbol" aria-hidden="true"><i/></span><span className="brand-copy"><strong>SAHJONY LLC</strong><small>GLOBAL TRADE OS</small></span></button>
}

function LegacyPublicSite(){
 return <div className="public-site institutional-public">
  <div className="signal-strip"><span><i/>GLOBAL TRADE NETWORK</span><strong>Human-led. AI-powered. Evidence-controlled.</strong><span>SAHJONY LLC · UNITED STATES</span></div>
  <header className="public-nav"><Brand ownerShortcut/><nav className="public-links" aria-label="Primary navigation"><a href="#solutions">Capabilities</a><a href="/industrial-marketplace">Marketplace</a><a href="#process">Process</a><a href="/cuba-private-sector">Cuba Desk</a><a className="primary-link" href="/start">Start a request <span aria-hidden="true">↗</span></a></nav></header>
  <main>
   <section className="public-hero ultra-hero">
    <div className="hero-copy">
     <div className="eyebrow gold"><span>01</span> GLOBAL TRADE, REENGINEERED</div>
     <h1>Move products across borders. <span>Without losing control.</span></h1>
     <p>SAHJONY LLC brings sourcing, deal intelligence, compliance, documentation, logistics and commercial execution into one premium global trade experience.</p>
     <div className="hero-actions"><a className="primary-link large" href="/start">Launch a sourcing request <span aria-hidden="true">↗</span></a><a className="secondary-link large" href="/industrial-marketplace">Explore the marketplace</a></div>
     <div className="trust-row" aria-label="Platform capabilities"><span><i/>Worldwide sourcing</span><span><i/>Case-based execution</span><span><i/>Governed releases</span></div>
    </div>
    <div className="trade-room" aria-label="SAHJONY trade control room preview">
     <div className="trade-room-media"><div className="media-top"><span>LIVE OPERATING LAYER</span><strong><i/> ONLINE</strong></div><div className="media-caption"><small>GLOBAL CORRIDOR</small><strong>Origin → SAHJONY → Destination</strong></div></div>
     <div className="trade-room-console">
      <div className="console-title"><div><small>CONTROL ROOM</small><strong>Every deal. One source of truth.</strong></div><span>TRADE OS / 26</span></div>
      <div className="console-grid"><div><small>01 · DISCOVER</small><strong>Source</strong><span>Worldwide supply intelligence</span></div><div><small>02 · VALIDATE</small><strong>Verify</strong><span>Commercial and compliance evidence</span></div><div><small>03 · EXECUTE</small><strong>Move</strong><span>Documents, payment and logistics</span></div></div>
      <div className="next-move"><span>AI NEXT MOVE</span><p>Qualify demand → compare supply → protect margin → release with evidence.</p><a href="/owner/deals" aria-label="Open deal command center">OPEN COMMAND <b aria-hidden="true">↗</b></a></div>
     </div>
    </div>
   </section>
   <section className="brand-marquee" aria-label="Trade platform scope"><span>GLOBAL SOURCING</span><i/> <span>MANAGED TRADE</span><i/> <span>INDUSTRIAL COMMERCE</span><i/> <span>AI INTELLIGENCE</span><i/> <span>LOGISTICS CONTROL</span></section>
   <section id="solutions" className="capability-showcase"><div className="section-intro"><div><div className="eyebrow gold"><span>02</span> ONE OPERATING LAYER</div><h2>Built for the full deal — not one fragment of it.</h2></div><p>From the first business need to final reconciliation, every critical decision stays visible, attributable and controlled.</p></div><div className="capability-grid">{publicCapabilities.map(([n,kicker,title,text])=><article key={n}><div className="capability-index"><span>{n}</span><small>{kicker}</small></div><div><strong>{title}</strong><p>{text}</p></div><b aria-hidden="true">↗</b></article>)}</div></section>
   <section id="process" className="institutional-section premium-process"><div className="process-copy"><div className="eyebrow gold"><span>03</span> CONTROLLED EXECUTION</div><h2>One fluid path from need to delivered value.</h2><p>Qualified opportunities become governed trade cases with a shared operational record across the complete lifecycle.</p><a className="secondary-link large" href="/start">Build your trade request</a></div><div className="process-rail">{publicStages.map((x,i)=><div className="process-node" key={x}><span>{String(i+1).padStart(2,'0')}</span><strong>{x}</strong><i aria-hidden="true">→</i></div>)}</div></section>
   <section className="final-cta"><div><small>YOUR NEXT GLOBAL OPPORTUNITY STARTS HERE</small><h2>Tell us what the business needs. We coordinate the world around it.</h2></div><a className="primary-link large" href="/start">Start now <span aria-hidden="true">↗</span></a></section>
  </main>
  <footer><span>© SAHJONY LLC · Global Trade Operating System</span><nav aria-label="Footer navigation"><a href="/trust-center">Trust center</a><a href="/partners">Partners</a><a href="/government-contracting">Government contracting</a></nav><span>www.sahjony.com</span></footer>
 </div>
}

function PublicSite(){
 const facts=[['PRODUCT','Defined need'],['QUANTITY','Commercial volume'],['DESTINATION','Named corridor'],['TIMING','Required window']];
 return <div className="public-site institutional-public cinematic-trade-os">
  <div className="signal-strip"><span><i/>GLOBAL TRADE NETWORK</span><strong>Human-led · AI-powered · Evidence-controlled</strong><span>SAHJONY LLC · UNITED STATES</span></div>
  <header className="public-nav cinematic-nav"><Brand ownerShortcut/><nav className="public-links" aria-label="Primary navigation"><a className="text-link" href="#demand">Demand</a><a className="text-link" href="#sourcing">Sourcing</a><a className="text-link" href="#control">Control</a><a className="text-link" href="/cuba-private-sector">Cuba Desk</a><a className="owner-entry" href="/owner-login">Private owner</a><a className="primary-link" href="#inquiry">Submit RFQ <span aria-hidden="true">↗</span></a></nav></header>
  <main>
   <section className="cinematic-chapter chapter-hero" data-cinematic>
    <div className="chapter-media hero-media" data-cinematic-media/>
    <div className="chapter-shade"/>
    <div className="chapter-content hero-chapter-copy">
     <div className="chapter-index" data-cinematic-reveal><span>01 / 06</span><i/> ENTRANCE</div>
     <h1 data-cinematic-reveal>Global trade.<br/><em>Under control.</em></h1>
     <p data-cinematic-reveal>SAHJONY TRADING OS coordinates sourcing, economics, compliance, documents, logistics and delivery across borders.</p>
     <div className="chapter-actions" data-cinematic-reveal><a className="primary-link large" href="#inquiry">Start a trade request ↗</a><a className="quiet-link" href="#demand">Enter the system ↓</a></div>
    </div>
    <div className="scroll-cue" data-float><span>SCROLL TO MOVE FORWARD</span><i/></div>
   </section>

   <section id="demand" className="cinematic-chapter split-chapter demand-chapter" data-cinematic>
    <div className="chapter-media manufacturing-media" data-cinematic-media/>
    <div className="chapter-shade"/>
    <div className="chapter-content split-copy">
     <div className="chapter-index" data-cinematic-reveal><span>02 / 06</span><i/> APPROACH</div>
     <h2 data-cinematic-reveal>Every movement starts with precise demand.</h2>
     <p data-cinematic-reveal>Product, volume, destination and timing become one qualified operating record before sourcing begins.</p>
     <div className="demand-facts" data-cinematic-reveal>{facts.map(([a,b],i)=><article key={a}><small>{String(i+1).padStart(2,'0')} · {a}</small><strong>{b}</strong></article>)}</div>
    </div>
   </section>

   <section id="sourcing" className="cinematic-chapter core-chapter" data-cinematic>
    <div className="chapter-media logistics-media" data-cinematic-media/>
    <div className="chapter-shade"/>
    <div className="chapter-content core-copy">
     <div className="chapter-index" data-cinematic-reveal><span>03 / 06</span><i/> CORE EXPERIENCE</div>
     <h2 data-cinematic-reveal>Source the world.<br/>Compare what matters.</h2>
     <div className="floating-callouts" data-cinematic-reveal><article data-float><small>SUPPLIER</small><strong>Identity verified</strong><span>KYB · capacity · origin</span></article><article data-float><small>COMMERCIAL</small><strong>Terms compared</strong><span>MOQ · Incoterms · lead time</span></article><article data-float><small>ECONOMICS</small><strong>Landed path</strong><span>Cost · freight · protected margin</span></article></div>
    </div>
   </section>

   <section id="control" className="cinematic-chapter control-chapter" data-cinematic>
    <div className="control-grid" data-cinematic-media/>
    <div className="chapter-content control-copy">
     <div className="chapter-index" data-cinematic-reveal><span>04 / 06</span><i/> SIGNATURE DETAIL</div>
     <h2 data-cinematic-reveal>The release is earned by evidence.</h2>
     <p data-cinematic-reveal>SAHJONY holds each transaction at the right gate until counterparty, product, corridor, payment and documents are ready.</p>
     <div className="control-rail" data-cinematic-reveal>{['KYB','HTS / ECCN','SANCTIONS','TERMS','DOCUMENTS','PAYMENT'].map((x,i)=><span key={x}><i className={i<4?'ready':''}/>{x}</span>)}</div>
     <div className="control-console" data-cinematic-reveal><small>RELEASE POSTURE</small><strong>FAIL-CLOSED</strong><span>AI recommends · Owner governs · Evidence releases</span></div>
    </div>
   </section>

   <section id="execution" className="cinematic-chapter execution-chapter" data-cinematic>
    <div className="chapter-media energy-media" data-cinematic-media/>
    <div className="chapter-shade"/>
    <div className="chapter-content execution-copy">
     <div className="chapter-index" data-cinematic-reveal><span>05 / 06</span><i/> EXECUTION</div>
     <h2 data-cinematic-reveal>Origin to destination.<br/>One visible path.</h2>
     <p data-cinematic-reveal>Factory, freight, port, vessel, customs and delivery remain linked to the same commercial truth.</p>
     <div className="execution-route" data-cinematic-reveal><span>ORIGIN</span><i/><span>SAHJONY CONTROL</span><i/><span>DESTINATION</span></div>
    </div>
   </section>

   <section id="inquiry" className="cinematic-chapter finale-chapter" data-cinematic>
    <div className="chapter-media finale-media" data-cinematic-media/>
    <div className="chapter-shade"/>
    <div className="chapter-content finale-grid">
     <div><div className="chapter-index" data-cinematic-reveal><span>06 / 06</span><i/> GRAND FINALE</div><h2 data-cinematic-reveal>Tell SAHJONY what needs to move across borders.</h2><p data-cinematic-reveal>Submit the commercial need. The system creates the controlled path.</p></div>
     <form className="finale-form" action="/start" method="get" data-cinematic-reveal><label>PRODUCT OR NEED<input name="product" required placeholder="What do you need sourced?"/></label><div><label>QUANTITY<input name="quantity" placeholder="Volume or target quantity"/></label><label>DESTINATION<input name="destination" placeholder="Country / port / city"/></label></div><label>CONTACT EMAIL<input type="email" name="email" required placeholder="name@company.com"/></label><button type="submit">Create trade request <span>↗</span></button><small>No commitment is created until commercial and compliance review is complete.</small></form>
    </div>
   </section>
  </main>
  <footer><span>© SAHJONY LLC · Global Trade Operating System</span><nav aria-label="Footer navigation"><a href="/global-sourcing">Global sourcing</a><a href="/partners">Partners</a><a href="/cuba-private-sector">Cuba Desk</a><a href="/owner-login">Private owner</a></nav><span>www.sahjony.com</span></footer>
 </div>
}

function StatePage({title,text,path}:{title:string;text:string;path:string}){return <div className="route-state"><Brand/><div className="route-card"><div className="eyebrow gold">SAHJONY GLOBAL TRADE</div><h1>{title}</h1><p>{text}</p><button className="primary-button" onClick={()=>nav(path)}>Continue</button></div></div>}

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

 useEffect(()=>{if(role==='owner'&&!token)location.replace('/owner-login')},[role,token]);
 useEffect(()=>{safeSet(`sahjony.${role}.token`,token)},[role,token]);
 useEffect(()=>{safeSet('sahjony.employee.id',employeeId)},[employeeId]);
 useEffect(()=>{const fn=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setSearchOpen(v=>!v)}if(e.key==='Escape'){setSearchOpen(false);setDrawer(false)}};addEventListener('keydown',fn);return()=>removeEventListener('keydown',fn)},[]);

 const headers=(json=false)=>{const h:Record<string,string>={'X-Role':role};if(token)h.Authorization=`Bearer ${token}`;if(role==='employee')h['X-Employee-Id']=employeeId;if(json)h['Content-Type']='application/json';return h};
 async function api(path:string,opts:RequestInit={}){const response=await fetch(path,{...opts,headers:{...headers(Boolean(opts.body)),...(opts.headers||{})}});const body=await response.json().catch(()=>({detail:`HTTP ${response.status}`}));if((response.status===401||response.status===403)&&role==='owner'){safeRemove('sahjony.owner.token');location.replace('/owner-login')}if(!response.ok)throw new Error(body.detail||`HTTP ${response.status}`);return body}
 async function refresh(){const cfg=modules[section];setLoading(true);setError('');try{if(cfg.health){const response=await fetch(cfg.health,{cache:'no-store'});setHealth({ok:response.ok,...await response.json().catch(()=>({}))})}if(cfg.data&&token){const body=await api(cfg.data,{cache:'no-store'});const list=Object.values(body).find(v=>Array.isArray(v)) as any[]|undefined;setRecords(list||[])}else setRecords([])}catch(e:any){setError(e.message||'Unable to load workspace')}finally{setLoading(false)}}
 useEffect(()=>{refresh();setDrawer(false)},[role,section]);

 const scope=role==='owner'?'OWNER COMMAND':role==='employee'?'EMPLOYEE OPERATIONS':'CUSTOMER PORTAL';
 const searchable=useMemo(()=>groupsFor(role).flatMap(([group,items])=>items.map(key=>({key,group,label:labelFor(role,key),description:modules[key].description}))).filter(item=>`${item.group} ${item.label} ${item.description}`.toLowerCase().includes(query.toLowerCase())),[role,query]);
 function signOut(){safeRemove(`sahjony.${role}.token`);setToken('');role==='owner'?location.assign('/owner-login'):nav('/')}

 return <div className={`os-shell role-${role}`}><aside className={`os-side ${drawer?'open':''}`}><div className="side-head"><Brand/><button className="close-drawer" onClick={()=>setDrawer(false)}>×</button></div><div className="scope-badge">{scope}</div><nav className="grouped-nav">{groupsFor(role).map(([group,items])=><section className="nav-group" key={group}><small>{group}</small>{items.map(key=><button key={key} className={section===key?'active':''} onClick={()=>nav(rolePath(role,key))}><span className="nav-dot"/><span>{labelFor(role,key)}</span></button>)}</section>)}{role==='owner'&&<section className="nav-group"><small>Channels</small><button onClick={()=>location.assign('/owner/telegram')}><span className="nav-dot"/><span>Telegram Control</span></button></section>}</nav><div className="side-foot"><span className="security-dot"/><div><strong>{token?'Session active':'Access required'}</strong><small>{role==='owner'?'Owner full scope':role==='employee'?`Employee · ${employeeId}`:'Customer workspace'}</small></div></div></aside>{drawer&&<button className="drawer-backdrop" onClick={()=>setDrawer(false)} aria-label="Close navigation"/>}<main className="os-main"><header className="os-top"><div className="top-left"><button className="mobile-menu" onClick={()=>setDrawer(true)}>☰</button><div className="breadcrumbs"><span>{scope}</span><strong>{labelFor(role,section)}</strong></div></div><div className="top-actions"><button className="search-button" onClick={()=>setSearchOpen(true)}>⌘K <span>Search SAHJONY</span></button><button className="icon-button" onClick={refresh}>{loading?'…':'↻'}</button><div className="profile-chip"><span className="avatar">{role[0].toUpperCase()}</span><div><strong>{role==='owner'?'Owner':role==='employee'?employeeId:'Customer'}</strong><small>{token?'Authenticated':'Limited access'}</small></div><button onClick={signOut}>Sign out</button></div></div></header>{!token&&role!=='owner'?<CredentialGate role={role} employeeId={employeeId} setEmployeeId={setEmployeeId} onToken={setToken}/>:section==='dashboard'?<Dashboard role={role} health={health} token={token} api={api}/>:section==='crm'?<CRMWorkspace role={role} records={records} refresh={refresh} api={api} error={error}/>:<GenericWorkspace role={role} section={section} health={health} records={records} loading={loading} error={error} refresh={refresh}/>}</main>{searchOpen&&<CommandPalette role={role} query={query} setQuery={setQuery} results={searchable} close={()=>setSearchOpen(false)}/>}</div>
}

function CredentialGate({role,employeeId,setEmployeeId,onToken}:any){const [value,setValue]=useState('');return <section className="credential-gate"><div className="eyebrow gold">SECURE WORKSPACE</div><h1>{role==='employee'?'Employee access':'Customer access'}</h1><p>Authenticate to load protected business records. Credentials remain in this browser session only.</p>{role==='employee'&&<label>Employee ID<input value={employeeId} onChange={e=>setEmployeeId(e.target.value)}/></label>}<label>Access credential<input type="password" value={value} onChange={e=>setValue(e.target.value)}/></label><button className="primary-button" onClick={()=>value&&onToken(value)}>Enter workspace</button></section>}

function CommandPalette({role,query,setQuery,results,close}:any){return <div className="command-overlay" onMouseDown={close}><section className="command-palette" onMouseDown={e=>e.stopPropagation()}><div className="command-search"><span>⌕</span><input autoFocus value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search workspaces, sourcing, shipments, compliance…"/><kbd>ESC</kbd></div><div className="command-results">{results.length?results.map((item:any)=><button key={item.key} onClick={()=>{nav(rolePath(role,item.key));close()}}><small>{item.group}</small><strong>{item.label}</strong><span>{item.description}</span></button>):<div className="empty-command">No matching workspace</div>}</div></section></div>}

function Dashboard({role,health,token,api}:any){
 const [counts,setCounts]=useState({crm:0,trade:0,sourcing:0});
 useEffect(()=>{if(!token||role==='customer')return;Promise.allSettled([api('/crm/intakes',{cache:'no-store'}),api('/managed-trade/requests',{cache:'no-store'}),api('/global-sourcing/requests',{cache:'no-store'})]).then(results=>{const count=(result:any)=>{if(result.status!=='fulfilled')return 0;const list=Object.values(result.value).find(v=>Array.isArray(v)) as any[]|undefined;return list?.length||0};setCounts({crm:count(results[0]),trade:count(results[1]),sourcing:count(results[2])})})},[role,token]);
 if(role==='customer')return <CustomerDashboard health={health}/>;
 const owner=role==='owner';
 const stats=owner?[['CRM PIPELINE',counts.crm,'Visible intake records'],['TRADE CASES',counts.trade,'Managed-trade records'],['SOURCING',counts.sourcing,'Global sourcing requests'],['CONTROL POSTURE',health?.production_ready?'READY':'GOVERNED',health?.production_ready?'Production gates satisfied':'Fail-closed controls active']]:[['QUALIFICATION',counts.crm,'Visible intake records'],['TRADE CASES',counts.trade,'Execution records'],['SOURCING',counts.sourcing,'Research requests'],['RELEASE','OWNER','Escalate controlled releases']];
 return <><section className="command-hero executive-hero" data-cinematic><div data-cinematic-reveal><div className="eyebrow gold">{owner?'GLOBAL TRADE COMMAND CENTER':'DAILY OPERATIONS'}</div><h1>{owner?'Control the pipeline. See the risk. Move with evidence.':'Work the queue. Resolve blockers. Escalate exceptions.'}</h1><p>{owner?'One operating layer across demand, suppliers, commercial terms, compliance, documents, payments, logistics and reconciliation.':'Your workspace is organized around the next operational action.'}</p><div className="hero-chip-row"><span>Worldwide sourcing</span><span>Case-based execution</span><span>Owner-governed release</span></div></div><div className="control-posture" data-cinematic-reveal><small>PLATFORM STATUS</small><strong>{health?.status==='ok'?'ONLINE':'CHECKING'}</strong><div><span>Release policy</span><b>FAIL-CLOSED</b></div><div><span>AI authority</span><b>ADVISORY</b></div><div><span>Access</span><b>{owner?'FULL OWNER':'OPERATIONS'}</b></div></div></section><section className="stat-grid institutional-stats" data-cinematic data-cinematic-reveal>{stats.map(([a,b,c]:any)=><article key={a}><small>{a}</small><strong>{b}</strong><span>{c}</span></article>)}</section>{owner&&<section className="executive-grid" data-cinematic data-cinematic-reveal><article className="panel trade-network"><div className="panel-head"><div><small>GLOBAL CONTROL PLANE</small><h2>Trade corridor posture</h2></div><span className="live-pill">LIVE MODEL</span></div><div className="network-canvas"><div className="world-line l1"/><div className="world-line l2"/><div className="world-line l3"/><div className="world-hub origin">ORIGIN<br/><b>SUPPLIERS</b></div><div className="world-hub center">SAHJONY<br/><b>CONTROL</b></div><div className="world-hub destination">DESTINATION<br/><b>CUSTOMERS</b></div></div><div className="network-legend"><span><i className="ok-dot"/>Qualified path</span><span><i className="hold-dot"/>Evidence gates</span><span><i className="ai-dot"/>AI advisory</span></div></article><article className="panel ai-brief"><div className="panel-head"><div><small>EXECUTIVE BRIEF</small><h2>What needs attention</h2></div></div><Brief n="01" title={`${counts.crm} intake records visible`} text="Review qualification and promote viable demand."/><Brief n="02" title={`${counts.sourcing} sourcing requests visible`} text="Compare candidates and corridor readiness."/><Brief n="03" title={`${counts.trade} trade cases visible`} text="Focus on holds, documents, logistics and reconciliation."/><button className="secondary-button" onClick={()=>nav('/owner/ai-brain')}>Open AI Intelligence</button></article></section>}<QuickActions role={role}/><Pipeline/></>
}

function Brief({n,title,text}:{n:string;title:string;text:string}){return <div className="brief-item"><span>{n}</span><div><strong>{title}</strong><small>{text}</small></div></div>}
function QuickActions({role}:{role:Role}){return <section className="workspace-section"><div className="section-title"><div><span className="eyebrow">ACTION CENTER</span><h2>Start real work</h2><p>Move directly into qualification, sourcing or trade execution.</p></div></div><div className="customer-actions"><button onClick={()=>nav(rolePath(role,'crm'))}>CRM / Qualification<span>Review and qualify new demand</span></button><button onClick={()=>nav(rolePath(role,'global-sourcing'))}>Global Sourcing<span>Research worldwide suppliers</span></button><button onClick={()=>nav(rolePath(role,'managed-trade'))}>Managed Trade<span>Work controlled trade cases</span></button><button onClick={()=>nav(rolePath(role,'shipping'))}>Shipments<span>Review logistics milestones</span></button></div></section>}
function Pipeline(){return <section className="workspace-section"><div className="section-title"><div><span className="eyebrow">CASE LIFECYCLE</span><h2>Request → reconciled delivery</h2></div></div><div className="pipeline-rail">{['Intake','Qualify','Source','Due diligence','Commercial','Release','Deliver','Reconcile'].map((item,i)=><article key={item}><span>{String(i+1).padStart(2,'0')}</span><strong>{item}</strong></article>)}</div></section>}

function CustomerDashboard({health}:any){return <><section className="command-hero customer-hero"><div><div className="eyebrow gold">YOUR GLOBAL TRADE WORKSPACE</div><h1>Know what is happening with every request.</h1><p>Submit what your business needs and follow messages, documents, shipment progress and trade status from one place.</p><div className="hero-actions"><a className="primary-link large" href="/start">Start a new request</a></div></div><div className="control-posture"><small>PLATFORM</small><strong>{health?.status==='ok'?'ONLINE':'CHECKING'}</strong><div><span>Requests</span><b>TRACKED</b></div><div><span>Documents</span><b>SECURE</b></div><div><span>Shipments</span><b>VISIBLE</b></div></div></section><section className="customer-journey">{[['1','Request submitted','Tell us what you need.'],['2','SAHJONY sourcing','We qualify and source eligible suppliers.'],['3','Trade plan','Review terms and required controls.'],['4','Execution & delivery','Follow documents and shipment status.']].map(([n,a,b])=><article key={n}><span>{n}</span><strong>{a}</strong><small>{b}</small></article>)}</section><section className="workspace-section"><div className="section-title"><div><span className="eyebrow">QUICK ACCESS</span><h2>Your business workspace</h2></div></div><div className="customer-actions"><button onClick={()=>nav('/customer/messages')}>Messages<span>Communications and updates</span></button><button onClick={()=>nav('/customer/documents')}>Documents<span>Trade evidence and files</span></button><button onClick={()=>nav('/customer/shipping')}>Shipments<span>Logistics milestones</span></button><button onClick={()=>nav('/customer/compliance')}>Trade Status<span>Required controls and status</span></button></div></section></>}

function CRMWorkspace({role,records,refresh,api,error}:any){
 const [selected,setSelected]=useState<any>(null);
 async function qualify(id:string,status:string){try{await api(`/crm/intakes/${id}/qualify`,{method:'PATCH',body:JSON.stringify({status,assigned_employee_id:role==='employee'?safeGet('sahjony.employee.id')||'staff':null})});refresh()}catch{}}
 async function promote(id:string){try{await api(`/crm/intakes/${id}/promote`,{method:'POST'});refresh()}catch{}}
 return <><section className="workspace-section full-height-section"><div className="section-title"><div><span className="eyebrow">COMMERCIAL PIPELINE</span><h1>{role==='owner'?'CRM & Opportunities':'Qualification Queue'}</h1><p>Every visible record opens into a complete evidence view. Research-only records remain non-binding until independently qualified.</p></div><a className="primary-action" href="/start">New customer intake</a></div>{error&&<div className="error">{error}</div>}<div className="records-toolbar"><span>{records.length} records visible</span><button className="secondary-button" onClick={refresh}>Refresh</button></div><div className="record-list institutional-records">{records.length?records.map((record:any,i:number)=>{const id=record.intake_id||record.id||String(i+1);const readOnly=Boolean(record.read_only||record.external_research||record.prospect_only||String(id).startsWith('external:'));const title=record.legal_name||record.buyer_company||record.business_name||record.buyer_name||record.contact_name||record.opportunity_title||record.product_need||'Trade opportunity';const subtitle=record.product_need||record.product_description||record.email||record.buyer_contact||id;return <article key={id} className="crm-record-clickable" role="button" tabIndex={0} onClick={()=>setSelected(record)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();setSelected(record)}}}><div className="record-primary"><small>{record.status||record.qualification_stage||record.verification_status||'RESEARCH'}</small><strong>{title}</strong><span>{subtitle}</span></div><div className="record-meta"><span><small>Destination</small><b>{record.destination_country||record.destination||record.country_code||record.buyer_country||'—'}</b></span><span><small>Source</small><b>{record.source_platform||record.source||record.source_type||'—'}</b></span><span><small>Verification</small><b>{record.verification_status||record.qualification_status||'Pending'}</b></span></div><div className="record-actions" onClick={e=>e.stopPropagation()}>{!readOnly&&!String(id).startsWith('prospect:')?<><button onClick={()=>qualify(id,'QUALIFIED')}>Qualify</button><button className="secondary" onClick={()=>qualify(id,'NEEDS_INFO')}>Need info</button><button className="secondary" onClick={()=>promote(id)}>Promote</button></>:<button className="secondary" onClick={()=>setSelected(record)}>Open full record</button>}</div></article>}):<EmptyState text="No CRM records are visible for this session."/>}</div></section>{selected&&<CaseDrawer record={selected} title="CRM & Opportunities" close={()=>setSelected(null)}/>}</>}

function GenericWorkspace({role,section,health,records,loading,error,refresh}:any){
 const [selected,setSelected]=useState<any>(null);
 const cfg=modules[section as ModuleKey];
 const status=(health?.ok||health?.status==='ok')?'ONLINE':'CHECKING';
 const description=role==='customer'&&section==='messages'?'Read updates and communications related to your SAHJONY requests.':role==='customer'&&section==='documents'?'View trade documents and evidence shared with your business.':role==='customer'&&section==='shipping'?'Follow shipment milestones, logistics progress and delivery status.':role==='customer'&&section==='compliance'?'See trade-status controls that affect your request.':cfg.description;
 return <><section className="module-hero institutional-module"><div><div className="eyebrow gold">{cfg.group.toUpperCase()}</div><h1>{labelFor(role,section)}</h1><p>{description}</p><div className="hero-chip-row"><span>Case-linked evidence</span><span>Role-aware access</span><span>Fail-closed controls</span></div></div><div className={`runtime-badge ${status==='ONLINE'?'ok':''}`}><small>MODULE STATUS</small><span>{status}</span><button className="secondary-button compact" onClick={refresh}>{loading?'Refreshing…':'Refresh data'}</button></div></section>{error&&<div className="error-banner">{error}</div>}<section className="records-card standalone institutional-card"><div className="section-title"><div><small>{cfg.group}</small><h2>{role==='customer'?'Your records':'Visible operating records'}</h2></div><span>{records.length} records</span></div>{records.length?<div className="case-table">{records.slice(0,100).map((record:any,i:number)=>{const values=Object.entries(record).filter(([,v])=>v!==null&&v!==''&&typeof v!=='object').slice(0,4);return <button className="case-row" key={record.id||record.request_id||record.intake_id||i} onClick={()=>setSelected(record)}><span className="case-index">{String(i+1).padStart(2,'0')}</span><span className="case-main"><strong>{String(record.product_need||record.legal_name||record.title||record.status||record.request_id||record.id||`Record ${i+1}`)}</strong><small>{values.slice(1).map(([,v])=>String(v)).join(' · ').slice(0,120)||'Open record details'}</small></span><span className="case-status">{String(record.status||record.state||'OPEN')}</span><span className="case-open">Open →</span></button>})}</div>:<EmptyState text={role==='customer'?'Nothing is waiting here right now.':'No records are visible for this module and session.'}/>}</section>{selected&&<CaseDrawer record={selected} title={labelFor(role,section)} close={()=>setSelected(null)}/>}</>}

function CaseDrawer({record,title,close}:any){
 const fields=Object.entries(record).filter(([,v])=>v!==undefined);
 const recordTitle=record.legal_name||record.buyer_company||record.business_name||record.buyer_name||record.opportunity_title||record.product_need||record.title||record.request_id||record.id||'Operating record';
 return <div className="case-overlay" onMouseDown={close}><aside className="case-drawer" onMouseDown={e=>e.stopPropagation()}><div className="case-drawer-head"><div><small>FULL RECORD · {title}</small><h2>{recordTitle}</h2></div><button onClick={close}>×</button></div><div className="case-tabs"><span className="active">All data</span><span>Evidence</span><span>Messages</span><span>Timeline</span></div><div className="case-fields">{fields.map(([key,value])=>{const label=key.replaceAll('_',' ');if(value===null||value==='')return <div key={key}><small>{label}</small><strong>—</strong></div>;if(key.endsWith('_url')&&typeof value==='string')return <div key={key}><small>{label}</small><strong><a href={value} target="_blank" rel="noreferrer">{value}</a></strong></div>;if(typeof value==='object')return <div key={key} className="case-field-wide"><small>{label}</small><pre>{JSON.stringify(value,null,2)}</pre></div>;return <div key={key}><small>{label}</small><strong>{String(value)}</strong></div>})}</div><div className="case-governance"><span className="security-dot"/><p>All stored CRM fields are displayed here. Research-only, historical and external-directory records are not qualified demand and remain fail-closed for commitments, payments and counterparty disclosure.</p></div></aside></div>}

function EmptyState({text}:{text:string}){return <div className="empty-state"><span>◇</span><strong>No active records</strong><p>{text}</p></div>}
