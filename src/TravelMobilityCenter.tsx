import {useMemo,useState} from 'react';

type Direction='from_cuba'|'to_cuba'|'worldwide';
type Mode='public'|'owner';

type RouteCard={title:string;subtitle:string;badge:string;description:string};

const routeCards:RouteCard[]=[
  {title:'Cuba → Mundo',subtitle:'Salidas internacionales',badge:'RUTAS LEGALES',description:'Planifica rutas desde Cuba con control de destino, escalas, tránsito, visado y documentación antes de emitir.'},
  {title:'Mundo → Cuba',subtitle:'Vuelos hacia Cuba',badge:'GLOBAL',description:'Busca opciones hacia aeropuertos cubanos mediante aerolíneas regulares, consolidadores y charters habilitados.'},
  {title:'¿A dónde puedo viajar?',subtitle:'Pasaporte cubano',badge:'INTELIGENCIA',description:'Clasifica destinos por visa, eVisa, visa a la llegada, tránsito y requisitos documentales verificables.'},
  {title:'Viaje familiar',subtitle:'Una sola coordinación',badge:'FAMILIAS',description:'Organiza pasajeros, documentos, pagos, equipaje, conexiones y servicios complementarios en un expediente.'}
];

const safeguards=[
  ['01','IDENTIDAD','Nacionalidad, pasaporte, residencia y documentos del pasajero.'],
  ['02','RUTA','Origen, destino, aeropuertos de conexión, cambio de terminal y auto-transferencia.'],
  ['03','ENTRADA Y TRÁNSITO','Visa de destino y requisitos de tránsito se validan por separado.'],
  ['04','REVISIÓN','Una ruta no puede pasar a confirmada o emitida mientras exista revisión humana pendiente.']
] as const;

function go(path:string){location.assign(path)}

export default function TravelMobilityCenter(){
  const mode:Mode=location.pathname.startsWith('/owner/')?'owner':'public';
  const [direction,setDirection]=useState<Direction>('from_cuba');
  const [origin,setOrigin]=useState('Cuba');
  const [destination,setDestination]=useState('');
  const [date,setDate]=useState('');
  const title=useMemo(()=>direction==='from_cuba'?'Salir de Cuba hacia el mundo':direction==='to_cuba'?'Viajar a Cuba desde cualquier país':'Viaje internacional mundial',[direction]);

  return <div style={s.page}>
    <style>{`*{box-sizing:border-box}body{margin:0;background:#06101a;color:#f6fbff;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,select{font:inherit}a{color:inherit}.travel-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}.travel-card{transition:transform .2s ease,border-color .2s ease}.travel-card:hover{transform:translateY(-2px);border-color:rgba(94,216,255,.55)!important}@media(max-width:900px){.travel-grid{grid-template-columns:1fr}.travel-span{grid-column:1!important}.travel-nav-links{display:none!important}}`}</style>
    <header style={s.header}>
      <button style={s.brand} onClick={()=>go(mode==='owner'?'/owner/dashboard':'/')}><span style={s.mark}>S</span><span><strong style={{display:'block'}}>SAHJONY</strong><small style={s.muted}>VIAJES GLOBALES</small></span></button>
      <nav className="travel-nav-links" style={s.navLinks}><a href="#buscar">Buscar viaje</a><a href="#movilidad">Movilidad</a><a href="#seguridad">Requisitos</a><a href="#operacion">Operación</a></nav>
      <button style={s.secondary} onClick={()=>go(mode==='owner'?'/owner/dashboard':'/start')}>{mode==='owner'?'Volver al Command Center':'Hablar con una agencia'}</button>
    </header>

    <main style={s.main}>
      <section style={s.hero}>
        <div style={s.eyebrow}>SAHJONY TRAVEL + MOBILITY OS · ESPAÑOL PRIMERO</div>
        <h1 style={s.h1}>{title}</h1>
        <p style={s.lead}>Un solo sistema para vuelos Cuba ↔ mundo, rutas internacionales, familias, requisitos de entrada y tránsito, charters, aerolíneas y operación multiagencia.</p>
        <div style={s.pills}><span style={s.pill}>Cuba → Mundo</span><span style={s.pill}>Mundo → Cuba</span><span style={s.pill}>Familias</span><span style={s.pill}>Visa + tránsito</span><span style={s.pill}>Revisión humana</span></div>
      </section>

      <section id="buscar" style={s.searchPanel}>
        <div style={s.panelHeader}><div><small style={s.kicker}>PLANIFICA PRIMERO · COMPRA DESPUÉS</small><h2 style={s.h2}>Diseña una ruta viable antes de pagar</h2></div><span style={s.status}><i style={s.dot}/>Motor de expediente activo</span></div>
        <div className="travel-grid">
          <label className="travel-span" style={{...s.field,gridColumn:'span 3'}}><span>Tipo de viaje</span><select value={direction} onChange={e=>{const v=e.target.value as Direction;setDirection(v);if(v==='from_cuba')setOrigin('Cuba');if(v==='to_cuba')setOrigin('')}} style={s.input}><option value="from_cuba">Desde Cuba</option><option value="to_cuba">Hacia Cuba</option><option value="worldwide">Mundial</option></select></label>
          <label className="travel-span" style={{...s.field,gridColumn:'span 3'}}><span>Origen</span><input value={origin} onChange={e=>setOrigin(e.target.value)} placeholder="País, ciudad o aeropuerto" style={s.input}/></label>
          <label className="travel-span" style={{...s.field,gridColumn:'span 3'}}><span>Destino</span><input value={destination} onChange={e=>setDestination(e.target.value)} placeholder={direction==='to_cuba'?'Cuba / aeropuerto':'País, ciudad o aeropuerto'} style={s.input}/></label>
          <label className="travel-span" style={{...s.field,gridColumn:'span 3'}}><span>Fecha aproximada</span><input type="date" value={date} onChange={e=>setDate(e.target.value)} style={s.input}/></label>
        </div>
        <div style={s.notice}><strong>Protección de emisión:</strong> una ruta no se considera lista para confirmar hasta que los controles requeridos de entrada, tránsito y revisión humana estén completos.</div>
        <div style={s.actions}><button style={s.primary} onClick={()=>go(mode==='owner'?'/owner/travel':'/start')}>{mode==='owner'?'Abrir operación de viajes':'Crear solicitud de viaje'} <span>↗</span></button><span style={s.muted}>Las tarifas, disponibilidad y reglas migratorias en tiempo real requieren proveedores autorizados antes de habilitar venta automática.</span></div>
      </section>

      <section id="movilidad" style={s.section}>
        <div style={s.sectionHead}><div><small style={s.kicker}>CUBA ↔ MUNDO</small><h2 style={s.h2}>Más que una agencia de boletos</h2></div><p style={s.sectionCopy}>Cada viaje se convierte en un expediente operacional con pasajeros, ruta, proveedores, requisitos, costos, reservación e incidencias.</p></div>
        <div className="travel-grid">{routeCards.map((card,i)=><article className="travel-card travel-span" key={card.title} style={{...s.card,gridColumn:'span 3'}}><div style={s.cardTop}><span style={s.cardIndex}>{String(i+1).padStart(2,'0')}</span><small style={s.badge}>{card.badge}</small></div><h3 style={s.h3}>{card.title}</h3><strong style={s.cardSub}>{card.subtitle}</strong><p style={s.cardText}>{card.description}</p></article>)}</div>
      </section>

      <section id="seguridad" style={s.section}>
        <div style={s.sectionHead}><div><small style={s.kicker}>TRAVEL READINESS GATE</small><h2 style={s.h2}>La ruta barata no gana si el pasajero no puede utilizarla</h2></div><p style={s.sectionCopy}>El sistema separa la venta del control documental. Las reglas deben provenir de fuentes autorizadas u oficiales y conservar evidencia de cuándo fueron verificadas.</p></div>
        <div style={s.safeguards}>{safeguards.map(([n,k,t])=><div key={n} style={s.safeRow}><span style={s.safeN}>{n}</span><strong>{k}</strong><p>{t}</p></div>)}</div>
      </section>

      <section id="operacion" style={s.ops}>
        <div><small style={s.kicker}>OPERACIÓN MULTIAGENCIA</small><h2 style={s.h2}>{mode==='owner'?'Command Center de Viajes':'Una red de agencias, un estándar operacional'}</h2><p style={s.sectionCopy}>Agencias, managers, agentes y partners trabajan dentro de su propio perímetro. SAHJONY mantiene una capa superior de control, auditoría y proveedores globales.</p></div>
        <div style={s.metrics}><div><small>IDIOMA BASE</small><strong>ES</strong><span>Español por defecto</span></div><div><small>DIRECCIONES</small><strong>↔</strong><span>Cuba y mundo</span></div><div><small>EMISIÓN</small><strong>GATED</strong><span>Requisitos primero</span></div></div>
      </section>
    </main>
  </div>
}

const s:Record<string,React.CSSProperties>={
  page:{minHeight:'100vh',background:'radial-gradient(circle at 75% 0%,rgba(36,132,176,.20),transparent 34%),#06101a'},
  header:{height:78,display:'flex',alignItems:'center',justifyContent:'space-between',padding:'0 clamp(18px,4vw,60px)',borderBottom:'1px solid rgba(255,255,255,.08)',position:'sticky',top:0,background:'rgba(6,16,26,.92)',backdropFilter:'blur(18px)',zIndex:10},
  brand:{display:'flex',gap:12,alignItems:'center',border:0,background:'transparent',color:'#fff',cursor:'pointer',padding:0,textAlign:'left'},mark:{width:38,height:38,borderRadius:12,display:'grid',placeItems:'center',background:'#5ad8ff',color:'#051018',fontWeight:950},muted:{color:'#8ca3b7',fontSize:12},navLinks:{display:'flex',gap:24,fontSize:13,color:'#bad0df'},secondary:{border:'1px solid rgba(255,255,255,.16)',background:'rgba(255,255,255,.03)',color:'#f6fbff',borderRadius:12,padding:'11px 14px',cursor:'pointer'},
  main:{maxWidth:1440,margin:'0 auto',padding:'0 clamp(18px,4vw,60px) 80px'},hero:{padding:'clamp(70px,9vw,130px) 0 56px',maxWidth:1050},eyebrow:{fontSize:12,fontWeight:900,letterSpacing:'.16em',color:'#5ad8ff',marginBottom:20},h1:{fontSize:'clamp(48px,7.6vw,106px)',letterSpacing:'-.06em',lineHeight:.89,margin:'0 0 24px',maxWidth:1100},lead:{fontSize:'clamp(17px,2vw,22px)',lineHeight:1.55,color:'#adc2d1',maxWidth:880},pills:{display:'flex',gap:9,flexWrap:'wrap',marginTop:28},pill:{border:'1px solid rgba(90,216,255,.2)',background:'rgba(90,216,255,.06)',padding:'8px 11px',borderRadius:999,fontSize:12,color:'#c8ecf8'},
  searchPanel:{background:'linear-gradient(145deg,rgba(18,41,58,.92),rgba(8,24,36,.98))',border:'1px solid rgba(90,216,255,.2)',borderRadius:24,padding:'clamp(20px,3vw,34px)',boxShadow:'0 30px 90px rgba(0,0,0,.25)'},panelHeader:{display:'flex',justifyContent:'space-between',gap:20,alignItems:'flex-start',marginBottom:24,flexWrap:'wrap'},kicker:{color:'#5ad8ff',fontWeight:900,letterSpacing:'.14em'},h2:{fontSize:'clamp(28px,4vw,52px)',letterSpacing:'-.045em',lineHeight:1,margin:'8px 0 0'},status:{border:'1px solid rgba(93,214,166,.24)',padding:'8px 11px',borderRadius:999,color:'#a8e7cd',fontSize:12},dot:{width:7,height:7,borderRadius:99,display:'inline-block',background:'#5dd6a6',marginRight:7},field:{display:'grid',gap:8,fontSize:12,color:'#a9bfce',fontWeight:750},input:{width:'100%',background:'#07131e',border:'1px solid rgba(255,255,255,.11)',borderRadius:12,padding:'13px 12px',color:'#f6fbff',outline:'none'},notice:{marginTop:18,borderLeft:'3px solid #e7bd5c',background:'rgba(231,189,92,.07)',padding:'13px 15px',fontSize:13,color:'#d8e1e8',lineHeight:1.5},actions:{display:'flex',gap:16,alignItems:'center',marginTop:20,flexWrap:'wrap'},primary:{background:'#5ad8ff',border:0,borderRadius:12,padding:'13px 17px',fontWeight:900,color:'#031018',cursor:'pointer'},
  section:{padding:'88px 0 0'},sectionHead:{display:'flex',justifyContent:'space-between',alignItems:'end',gap:30,marginBottom:28,flexWrap:'wrap'},sectionCopy:{color:'#9eb3c2',lineHeight:1.65,maxWidth:650},card:{minHeight:275,border:'1px solid rgba(255,255,255,.09)',borderRadius:20,padding:22,background:'rgba(12,27,39,.72)'},cardTop:{display:'flex',justifyContent:'space-between',alignItems:'center'},cardIndex:{fontSize:12,color:'#738a9b'},badge:{fontSize:10,letterSpacing:'.12em',color:'#5ad8ff'},h3:{fontSize:27,letterSpacing:'-.03em',margin:'38px 0 5px'},cardSub:{fontSize:13,color:'#d6e4ed'},cardText:{fontSize:14,lineHeight:1.6,color:'#8fa7b8',marginTop:18},
  safeguards:{borderTop:'1px solid rgba(255,255,255,.1)'},safeRow:{display:'grid',gridTemplateColumns:'64px minmax(140px,220px) 1fr',gap:20,alignItems:'center',padding:'22px 0',borderBottom:'1px solid rgba(255,255,255,.08)'},safeN:{color:'#5ad8ff',fontWeight:900},
  ops:{marginTop:88,borderRadius:24,padding:'clamp(24px,4vw,44px)',background:'linear-gradient(120deg,rgba(91,216,255,.11),rgba(255,255,255,.025))',border:'1px solid rgba(90,216,255,.16)',display:'grid',gridTemplateColumns:'minmax(0,1.4fr) minmax(330px,.8fr)',gap:40},metrics:{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:10,alignSelf:'center'},
  safeText:{color:'#9eb3c2'},
};

Object.assign(s.metrics,{minWidth:0});
