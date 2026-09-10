import {useMemo,useState} from 'react';
import {evidenceLabel,projectEquirectangular,referenceTradeNodes,spatialLayers,type SpatialEntity,type SpatialLayerId} from './spatial/globalOperations';

const worldOutline='M1,44 C8,35 17,34 23,28 C29,22 36,24 42,19 C47,14 56,14 61,21 C66,25 73,23 78,27 C86,31 93,30 99,37 L99,68 C91,68 85,72 77,69 C69,65 63,72 55,69 C46,65 39,72 31,67 C23,62 16,66 9,61 C5,58 2,53 1,44 Z';

function MapNode({entity,onSelect,selected}:{entity:SpatialEntity;onSelect:(entity:SpatialEntity)=>void;selected:boolean}){
  const p=projectEquirectangular(entity.lat,entity.lon);
  return <button aria-label={entity.name} title={entity.name} onClick={()=>onSelect(entity)} style={{...s.node,left:`${p.x}%`,top:`${p.y}%`,...(selected?s.nodeSelected:{})}}><span style={s.nodeCore}/></button>
}

export default function GlobalOperationsCenter(){
  const [active,setActive]=useState<Set<SpatialLayerId>>(new Set(spatialLayers.filter(x=>x.enabledByDefault).map(x=>x.id)));
  const [selected,setSelected]=useState<SpatialEntity|null>(referenceTradeNodes[0]||null);
  const entities=useMemo(()=>referenceTradeNodes.filter(e=>active.has(e.layer)),[active]);
  function toggle(id:SpatialLayerId){setActive(prev=>{const next=new Set(prev);next.has(id)?next.delete(id):next.add(id);return next})}

  return <main style={s.page}>
    <header style={s.header}>
      <a href="/owner/dashboard" style={s.brand}>SAHJONY <span style={s.accent}>GLOBAL OPERATIONS</span></a>
      <nav style={s.nav}><a href="/owner/dashboard" style={s.link}>Owner OS</a><a href="/owner/intelligence" style={s.link}>Intelligence</a><a href="/owner/deals" style={s.link}>Deals</a><a href="/owner/jarvis" style={s.link}>JARVIS</a></nav>
    </header>

    <section style={s.hero}>
      <div><div style={s.eyebrow}>SPATIAL INTELLIGENCE · COMMERCIAL-FIRST</div><h1 style={s.h1}>See the business as a <span style={s.accent}>global operating picture.</span></h1><p style={s.lead}>A governed spatial layer for trade nodes, ports, qualified RFQs, verified suppliers, buyers, shipments and risk. Reference geography is explicitly separated from live business truth.</p></div>
      <div style={s.scoreCard}><div style={s.scoreLabel}>TRUTH STATE</div><div style={s.score}>0</div><div style={s.muted}>live commercial entities connected · reference geography only in this release</div></div>
    </section>

    <section style={s.layout}>
      <aside style={s.sidebar}>
        <div style={s.eyebrow}>LAYERS</div><h2 style={s.h2}>Operating picture</h2>
        {spatialLayers.map(layer=><button key={layer.id} onClick={()=>toggle(layer.id)} style={{...s.layer,...(active.has(layer.id)?s.layerActive:{})}}><span><strong>{layer.label}</strong><small style={s.small}>{layer.description}</small></span><b>{active.has(layer.id)?'ON':'OFF'}</b></button>)}
        <div style={s.policy}><strong>Commercial data policy</strong><p style={s.muted}>Only approved data sources may feed this view. Third-party God’s Eye datasets and models are not bundled here. Provider licensing and attribution remain source-specific.</p></div>
      </aside>

      <section style={s.mapPanel}>
        <div style={s.mapHead}><div><div style={s.eyebrow}>GLOBAL TRADE DIGITAL TWIN</div><h2 style={s.h2}>World operations</h2></div><div style={s.mapMeta}>{entities.length} visible reference nodes</div></div>
        <div style={s.map}>
          <div style={s.grid}/><svg viewBox="0 0 100 100" preserveAspectRatio="none" style={s.outline} aria-hidden="true"><path d={worldOutline} fill="rgba(43,105,132,.14)" stroke="rgba(102,220,255,.18)" strokeWidth=".4"/></svg>
          <div style={s.equator}/><div style={s.prime}/>
          {entities.map(entity=><MapNode key={entity.id} entity={entity} selected={selected?.id===entity.id} onSelect={setSelected}/>)}
          <div style={s.mapLegend}>REFERENCE ≠ LIVE BUSINESS DATA</div>
        </div>
      </section>

      <aside style={s.detail}>
        <div style={s.eyebrow}>ENTITY INSPECTOR</div><h2 style={s.h2}>{selected?.name||'Select a node'}</h2>
        {selected?<><div style={s.badge}>{evidenceLabel(selected.evidence)}</div><dl style={s.dl}><dt>TYPE</dt><dd>{selected.kind.toUpperCase()}</dd><dt>COORDINATES</dt><dd>{selected.lat.toFixed(4)}, {selected.lon.toFixed(4)}</dd><dt>SOURCE</dt><dd>{selected.source}</dd><dt>BUSINESS STATE</dt><dd>Reference geography — no deal, supplier, buyer or shipment implied.</dd></dl></>:<p style={s.muted}>Choose an entity on the map.</p>}
        <div style={s.policy}><strong>Next data contracts</strong><p style={s.muted}>RFQ → destination · supplier → verified facility · buyer → qualified location · shipment → authorized tracking milestone · risk → sourced event with confidence and expiry.</p></div>
      </aside>
    </section>

    <section style={s.kpis}><Kpi label="Verified RFQs mapped" value="0"/><Kpi label="Verified suppliers mapped" value="0"/><Kpi label="Qualified buyers mapped" value="0"/><Kpi label="Active shipments mapped" value="0"/><Kpi label="Unverified entities promoted" value="0"/></section>
    <footer style={s.footer}>SAHJONY Spatial Intelligence Engine · inspired by modular geospatial patterns from God’s Eye View · no restricted third-party datasets or models bundled.</footer>
  </main>
}

function Kpi({label,value}:{label:string;value:string}){return <article style={s.kpi}><div style={s.kpiValue}>{value}</div><div style={s.scoreLabel}>{label.toUpperCase()}</div></article>}

const s:Record<string,any>={
 page:{minHeight:'100vh',background:'radial-gradient(circle at 50% -20%,#12334a 0,#06111c 36%,#02060b 75%)',color:'#f4f8fb',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'0 22px 44px'},header:{maxWidth:1500,margin:'0 auto',minHeight:72,display:'flex',alignItems:'center',justifyContent:'space-between',gap:16,borderBottom:'1px solid rgba(255,255,255,.08)'},brand:{fontSize:13,fontWeight:950,letterSpacing:'.09em',color:'#fff',textDecoration:'none'},accent:{color:'#66dcff'},nav:{display:'flex',gap:7,flexWrap:'wrap'},link:{color:'#a8bac7',textDecoration:'none',fontSize:12,padding:'9px'},hero:{maxWidth:1500,margin:'0 auto',padding:'48px 0 26px',display:'grid',gridTemplateColumns:'minmax(0,1.8fr) minmax(240px,.55fr)',gap:24,alignItems:'end'},eyebrow:{fontSize:10,fontWeight:950,letterSpacing:'.16em',color:'#66dcff',marginBottom:11},h1:{fontSize:'clamp(40px,5vw,76px)',lineHeight:.94,letterSpacing:'-.05em',margin:'0 0 16px',maxWidth:1000},lead:{color:'#99adbc',fontSize:15,lineHeight:1.65,maxWidth:840,margin:0},scoreCard:{padding:20,border:'1px solid rgba(102,220,255,.2)',borderRadius:18,background:'rgba(5,16,27,.8)'},scoreLabel:{fontSize:9,fontWeight:950,letterSpacing:'.14em',color:'#8fa5b5'},score:{fontSize:50,fontWeight:950,lineHeight:1,margin:'9px 0'},muted:{color:'#8197a8',fontSize:12,lineHeight:1.55},layout:{maxWidth:1500,margin:'0 auto',display:'grid',gridTemplateColumns:'260px minmax(0,1fr) 280px',gap:12},sidebar:{padding:16,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'rgba(5,13,22,.82)'},detail:{padding:16,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'rgba(5,13,22,.82)'},h2:{fontSize:22,letterSpacing:'-.03em',margin:'0 0 14px'},layer:{width:'100%',display:'flex',alignItems:'center',justifyContent:'space-between',gap:12,textAlign:'left',padding:'11px',margin:'0 0 7px',border:'1px solid rgba(255,255,255,.07)',borderRadius:11,background:'rgba(255,255,255,.02)',color:'#a7bac8',cursor:'pointer'},layerActive:{borderColor:'rgba(102,220,255,.28)',background:'rgba(102,220,255,.07)',color:'#eefaff'},small:{display:'block',fontSize:9,color:'#718696',lineHeight:1.35,marginTop:4},policy:{marginTop:15,padding:13,border:'1px solid rgba(102,220,255,.12)',borderRadius:12,background:'rgba(102,220,255,.04)'},mapPanel:{padding:16,border:'1px solid rgba(255,255,255,.08)',borderRadius:18,background:'rgba(4,12,20,.88)',minWidth:0},mapHead:{display:'flex',justifyContent:'space-between',gap:12,alignItems:'start'},mapMeta:{fontSize:10,color:'#7890a1',letterSpacing:'.08em'},map:{position:'relative',height:'clamp(430px,62vh,720px)',overflow:'hidden',borderRadius:14,border:'1px solid rgba(102,220,255,.12)',background:'radial-gradient(circle at 50% 44%,rgba(13,48,67,.72),rgba(2,7,12,.98) 68%)'},grid:{position:'absolute',inset:0,backgroundImage:'linear-gradient(rgba(102,220,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(102,220,255,.045) 1px,transparent 1px)',backgroundSize:'10% 10%'},outline:{position:'absolute',inset:0,width:'100%',height:'100%'},equator:{position:'absolute',left:0,right:0,top:'50%',height:1,background:'rgba(102,220,255,.10)'},prime:{position:'absolute',top:0,bottom:0,left:'50%',width:1,background:'rgba(102,220,255,.08)'},node:{position:'absolute',width:20,height:20,transform:'translate(-50%,-50%)',borderRadius:999,border:'1px solid rgba(102,220,255,.55)',background:'rgba(102,220,255,.08)',padding:0,cursor:'pointer',boxShadow:'0 0 16px rgba(102,220,255,.18)'},nodeCore:{display:'block',width:5,height:5,borderRadius:999,background:'#66dcff',margin:'6px auto'},nodeSelected:{width:28,height:28,boxShadow:'0 0 26px rgba(102,220,255,.5)',background:'rgba(102,220,255,.18)'},mapLegend:{position:'absolute',left:14,bottom:12,fontSize:9,fontWeight:950,letterSpacing:'.15em',color:'#66dcff'},badge:{display:'inline-block',padding:'6px 9px',borderRadius:999,background:'rgba(102,220,255,.08)',border:'1px solid rgba(102,220,255,.2)',fontSize:9,fontWeight:950,letterSpacing:'.14em',color:'#66dcff'},dl:{display:'grid',gridTemplateColumns:'1fr',gap:5,marginTop:18},kpis:{maxWidth:1500,margin:'12px auto 0',display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:10},kpi:{padding:15,border:'1px solid rgba(255,255,255,.08)',borderRadius:13,background:'rgba(5,13,22,.82)'},kpiValue:{fontSize:28,fontWeight:950,marginBottom:5},footer:{maxWidth:1500,margin:'26px auto 0',paddingTop:15,borderTop:'1px solid rgba(255,255,255,.07)',fontSize:10,color:'#627889',letterSpacing:'.06em'}
};
