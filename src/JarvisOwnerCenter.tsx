import {useEffect,useMemo,useState} from 'react';

type Mode='personal'|'business';
type Status='today'|'waiting'|'scheduled'|'approval'|'done';
type Priority='urgent'|'high'|'normal';
type Task={id:string;title:string;mode:Mode;status:Status;priority:Priority;note:string;createdAt:string};

const STORAGE_KEY='sahjony.jarvis.owner.tasks.v1';
const seed:Task[]=[
  {id:'seed-1',title:'Review owner priorities',mode:'business',status:'today',priority:'high',note:'Keep business execution focused on the highest-value bottleneck.',createdAt:new Date().toISOString()},
  {id:'seed-2',title:'Prepare personal day plan',mode:'personal',status:'today',priority:'normal',note:'Consolidate appointments, reminders and personal follow-ups.',createdAt:new Date().toISOString()},
];

function loadTasks():Task[]{
  try{const raw=localStorage.getItem(STORAGE_KEY);if(!raw)return seed;const parsed=JSON.parse(raw);return Array.isArray(parsed)?parsed:seed}catch{return seed}
}
function saveTasks(tasks:Task[]){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(tasks))}catch{}}

const statusLabel:Record<Status,string>={today:'TODAY',waiting:'WAITING',scheduled:'SCHEDULED',approval:'REQUIRES APPROVAL',done:'DONE'};
const priorityRank:Record<Priority,number>={urgent:0,high:1,normal:2};

export default function JarvisOwnerCenter(){
  const [mode,setMode]=useState<Mode>('personal');
  const [tasks,setTasks]=useState<Task[]>(loadTasks);
  const [title,setTitle]=useState('');
  const [note,setNote]=useState('');
  const [status,setStatus]=useState<Status>('today');
  const [priority,setPriority]=useState<Priority>('normal');

  useEffect(()=>saveTasks(tasks),[tasks]);

  const visible=useMemo(()=>tasks.filter(t=>t.mode===mode).sort((a,b)=>priorityRank[a.priority]-priorityRank[b.priority]),[tasks,mode]);
  const today=visible.filter(t=>t.status==='today');
  const waiting=visible.filter(t=>t.status==='waiting');
  const scheduled=visible.filter(t=>t.status==='scheduled');
  const approvals=visible.filter(t=>t.status==='approval');
  const done=visible.filter(t=>t.status==='done');
  const activeCount=visible.length-done.length;

  function addTask(){
    const clean=title.trim();if(!clean)return;
    setTasks(prev=>[{id:crypto.randomUUID(),title:clean,mode,status,priority,note:note.trim(),createdAt:new Date().toISOString()},...prev]);
    setTitle('');setNote('');setStatus('today');setPriority('normal');
  }
  function updateTask(id:string,patch:Partial<Task>){setTasks(prev=>prev.map(t=>t.id===id?{...t,...patch}:t))}
  function removeTask(id:string){setTasks(prev=>prev.filter(t=>t.id!==id))}

  const top3=visible.filter(t=>t.status!=='done').slice(0,3);

  return <main style={s.page}>
    <header style={s.header}>
      <a href="/owner/dashboard" style={s.brand}>SAHJONY <span style={s.accent}>JARVIS</span></a>
      <nav style={s.nav}>
        <a href="/owner/dashboard" style={s.link}>Owner OS</a>
        <a href="/owner/sofia-performance" style={s.link}>Sofía</a>
        <a href="/owner/intelligence" style={s.link}>Intelligence</a>
      </nav>
    </header>

    <section style={s.hero}>
      <div>
        <div style={s.eyebrow}>PRIVATE OWNER AI · EXECUTIVE + PERSONAL</div>
        <h1 style={s.h1}>JARVIS <span style={s.accent}>Command Center</span></h1>
        <p style={s.lead}>One private operating layer for priorities, approvals, waiting items and daily execution. Personal and business contexts remain separated by default.</p>
      </div>
      <div style={s.scoreCard}>
        <div style={s.scoreLabel}>{mode.toUpperCase()} ACTIVE</div>
        <div style={s.score}>{activeCount}</div>
        <div style={s.muted}>open items · {approvals.length} approval{approvals.length===1?'':'s'} required</div>
      </div>
    </section>

    <section style={s.modeBar}>
      <button onClick={()=>setMode('personal')} style={{...s.modeButton,...(mode==='personal'?s.modeActive:{})}}>PERSONAL</button>
      <button onClick={()=>setMode('business')} style={{...s.modeButton,...(mode==='business'?s.modeActive:{})}}>BUSINESS</button>
    </section>

    <section style={s.gridStats}>
      <Stat label="Today" value={today.length}/><Stat label="Waiting" value={waiting.length}/><Stat label="Scheduled" value={scheduled.length}/><Stat label="Approvals" value={approvals.length}/><Stat label="Completed" value={done.length}/>
    </section>

    <section style={s.twoCol}>
      <article style={s.panel}>
        <div style={s.eyebrow}>CAPTURE</div><h2 style={s.h2}>Add owner task</h2>
        <input aria-label="Task title" value={title} onChange={e=>setTitle(e.target.value)} placeholder="What needs to happen?" style={s.input}/>
        <textarea aria-label="Task note" value={note} onChange={e=>setNote(e.target.value)} placeholder="Context, dependency or desired outcome" style={{...s.input,minHeight:90,resize:'vertical'}}/>
        <div style={s.formRow}>
          <select value={status} onChange={e=>setStatus(e.target.value as Status)} style={s.select}><option value="today">Today</option><option value="waiting">Waiting</option><option value="scheduled">Scheduled</option><option value="approval">Requires approval</option></select>
          <select value={priority} onChange={e=>setPriority(e.target.value as Priority)} style={s.select}><option value="urgent">Urgent</option><option value="high">High</option><option value="normal">Normal</option></select>
          <button onClick={addTask} style={s.primary}>Add task</button>
        </div>
      </article>

      <article style={s.panel}>
        <div style={s.eyebrow}>DAILY BRIEF</div><h2 style={s.h2}>Top 3 priorities</h2>
        {top3.length?top3.map((t,i)=><div key={t.id} style={s.briefRow}><span style={s.number}>0{i+1}</span><div><strong>{t.title}</strong><div style={s.muted}>{statusLabel[t.status]} · {t.priority.toUpperCase()}</div></div></div>):<div style={s.empty}>No active priorities.</div>}
        <div style={s.callout}><strong>Owner decisions</strong><div style={s.muted}>{approvals.length?`${approvals.length} item${approvals.length===1?'':'s'} require explicit approval.`:'No approval-gated items.'}</div></div>
      </article>
    </section>

    <section style={s.panel}>
      <div style={s.panelHead}><div><div style={s.eyebrow}>{mode.toUpperCase()} QUEUE</div><h2 style={s.h2}>Operational state</h2></div></div>
      <div style={s.taskGrid}>{visible.map(task=><TaskCard key={task.id} task={task} onUpdate={updateTask} onRemove={removeTask}/>)}</div>
      {!visible.length&&<div style={s.empty}>No {mode} tasks yet.</div>}
    </section>

    <footer style={s.footer}>JARVIS Owner OS · Local persistence enabled for this browser · Sensitive or irreversible actions remain approval-gated.</footer>
  </main>
}

function Stat({label,value}:{label:string;value:number}){return <article style={s.stat}><div style={s.statValue}>{value}</div><div style={s.scoreLabel}>{label.toUpperCase()}</div></article>}

function TaskCard({task,onUpdate,onRemove}:{task:Task;onUpdate:(id:string,patch:Partial<Task>)=>void;onRemove:(id:string)=>void}){
  return <article style={s.taskCard}>
    <div style={s.taskTop}><span style={{...s.badge,...(task.priority==='urgent'?s.urgent:task.priority==='high'?s.high:{})}}>{task.priority.toUpperCase()}</span><span style={s.state}>{statusLabel[task.status]}</span></div>
    <strong style={s.taskTitle}>{task.title}</strong>
    {task.note&&<p style={s.taskNote}>{task.note}</p>}
    <div style={s.actions}>
      {task.status!=='done'&&<button onClick={()=>onUpdate(task.id,{status:'done'})} style={s.smallButton}>Complete</button>}
      {task.status!=='waiting'&&task.status!=='done'&&<button onClick={()=>onUpdate(task.id,{status:'waiting'})} style={s.smallButton}>Waiting</button>}
      {task.status!=='approval'&&task.status!=='done'&&<button onClick={()=>onUpdate(task.id,{status:'approval'})} style={s.smallButton}>Approval</button>}
      {task.status==='done'&&<button onClick={()=>onUpdate(task.id,{status:'today'})} style={s.smallButton}>Reopen</button>}
      <button onClick={()=>onRemove(task.id)} style={{...s.smallButton,color:'#ff9d9d'}}>Remove</button>
    </div>
  </article>
}

const s:Record<string,any>={
  page:{minHeight:'100vh',background:'radial-gradient(circle at 15% -10%,#132b43 0,#07101b 36%,#03070c 72%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 24px 48px'},
  header:{maxWidth:1320,margin:'0 auto',minHeight:74,display:'flex',alignItems:'center',justifyContent:'space-between',borderBottom:'1px solid rgba(255,255,255,.08)',gap:20,padding:'10px 0'},brand:{fontWeight:950,letterSpacing:'.09em',fontSize:14,color:'#fff',textDecoration:'none'},accent:{color:'#66dcff'},nav:{display:'flex',gap:8,flexWrap:'wrap'},link:{color:'#aebdca',textDecoration:'none',fontSize:13,padding:'9px 10px'},
  hero:{maxWidth:1320,margin:'0 auto',padding:'64px 0 34px',display:'grid',gridTemplateColumns:'minmax(0,1.8fr) minmax(240px,.6fr)',gap:28,alignItems:'end'},eyebrow:{fontSize:11,fontWeight:950,letterSpacing:'.16em',color:'#66dcff',marginBottom:12},h1:{fontSize:'clamp(42px,6vw,82px)',lineHeight:.95,letterSpacing:'-.055em',margin:'0 0 18px'},lead:{maxWidth:800,color:'#98adbd',fontSize:16,lineHeight:1.65,margin:0},
  scoreCard:{border:'1px solid rgba(102,220,255,.22)',background:'rgba(6,18,30,.75)',borderRadius:20,padding:22},scoreLabel:{fontSize:10,fontWeight:950,letterSpacing:'.14em',color:'#91a5b5'},score:{fontSize:58,fontWeight:950,lineHeight:1,margin:'10px 0'},muted:{color:'#7f95a7',fontSize:12,lineHeight:1.55},
  modeBar:{maxWidth:1320,margin:'0 auto 14px',display:'flex',gap:8},modeButton:{border:'1px solid rgba(255,255,255,.1)',background:'rgba(255,255,255,.025)',color:'#94a6b5',padding:'11px 16px',borderRadius:999,fontWeight:900,fontSize:11,letterSpacing:'.12em',cursor:'pointer'},modeActive:{background:'#66dcff',color:'#041019',borderColor:'#66dcff'},
  gridStats:{maxWidth:1320,margin:'0 auto 16px',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))',gap:10},stat:{padding:17,border:'1px solid rgba(255,255,255,.08)',borderRadius:15,background:'rgba(7,16,26,.72)'},statValue:{fontSize:31,fontWeight:950,marginBottom:6},
  twoCol:{maxWidth:1320,margin:'0 auto',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(330px,1fr))',gap:16},panel:{maxWidth:1320,margin:'16px auto',padding:22,border:'1px solid rgba(255,255,255,.09)',borderRadius:20,background:'rgba(6,14,23,.82)'},h2:{fontSize:27,letterSpacing:'-.035em',margin:'0 0 16px'},panelHead:{display:'flex',justifyContent:'space-between',gap:16},
  input:{width:'100%',boxSizing:'border-box',background:'rgba(255,255,255,.035)',border:'1px solid rgba(255,255,255,.1)',borderRadius:12,padding:'12px 13px',color:'#eef7fb',font:'inherit',marginBottom:10},formRow:{display:'flex',gap:8,flexWrap:'wrap'},select:{background:'#0b1723',border:'1px solid rgba(255,255,255,.1)',borderRadius:10,padding:'10px',color:'#dbe7ef'},primary:{background:'#66dcff',color:'#031018',border:0,borderRadius:10,padding:'10px 15px',fontWeight:950,cursor:'pointer'},
  briefRow:{display:'grid',gridTemplateColumns:'38px 1fr',gap:10,padding:'12px 0',borderTop:'1px solid rgba(255,255,255,.06)'},number:{fontSize:11,fontWeight:950,color:'#66dcff',paddingTop:3},callout:{marginTop:14,padding:15,borderRadius:13,background:'rgba(102,220,255,.06)',border:'1px solid rgba(102,220,255,.14)'},empty:{padding:'20px 0',color:'#718799'},
  taskGrid:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))',gap:12},taskCard:{padding:18,border:'1px solid rgba(255,255,255,.08)',borderRadius:15,background:'rgba(255,255,255,.025)'},taskTop:{display:'flex',justifyContent:'space-between',gap:8,marginBottom:14},badge:{fontSize:9,fontWeight:950,letterSpacing:'.12em',padding:'5px 8px',borderRadius:999,background:'rgba(255,255,255,.08)',color:'#91a5b5'},urgent:{background:'rgba(255,92,92,.14)',color:'#ff9d9d'},high:{background:'rgba(255,190,92,.12)',color:'#ffd08a'},state:{fontSize:9,letterSpacing:'.1em',fontWeight:900,color:'#66dcff'},taskTitle:{fontSize:16},taskNote:{fontSize:12,color:'#8398a8',lineHeight:1.55,minHeight:38},actions:{display:'flex',gap:6,flexWrap:'wrap',marginTop:14},smallButton:{border:'1px solid rgba(255,255,255,.1)',background:'transparent',color:'#c6d4dd',borderRadius:8,padding:'7px 9px',fontSize:11,cursor:'pointer'},footer:{maxWidth:1320,margin:'28px auto 0',paddingTop:16,borderTop:'1px solid rgba(255,255,255,.07)',color:'#607687',fontSize:11,letterSpacing:'.06em'}
};
