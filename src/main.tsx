import {Component,StrictMode,type ErrorInfo,type PropsWithChildren,type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import {I18nextProvider} from 'react-i18next';
import i18n from './i18n';
import '../app/globals.css';
import './workflow.css';
import './premium.css';

const rootElement=document.getElementById('root');

(function installSafeSessionStorage(){
  try{const probe='__sahjony_storage_probe__';window.sessionStorage.setItem(probe,'1');window.sessionStorage.removeItem(probe)}catch(error){
    const memory=new Map<string,string>();
    const fallback:Storage={get length(){return memory.size},clear(){memory.clear()},getItem(k){return memory.has(k)?memory.get(k)!:null},key(i){return Array.from(memory.keys())[i]??null},removeItem(k){memory.delete(k)},setItem(k,v){memory.set(String(k),String(v))}};
    try{Object.defineProperty(window,'sessionStorage',{value:fallback,configurable:true})}catch{console.warn('SAHJONY_STORAGE_FALLBACK_UNAVAILABLE',error)}
  }
})();

function EmergencyScreen({message=i18n.t('emergency.initError')}:{message?:string}){
  return <main style={{minHeight:'100vh',background:'#050b13',color:'#f5f9ff',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'28px'}}><div style={{maxWidth:980,margin:'0 auto'}}><div style={{fontSize:12,fontWeight:900,letterSpacing:'.16em',color:'#5ad8ff'}}>SAHJONY LLC</div><h1 style={{fontSize:'clamp(42px,7vw,86px)',lineHeight:.92,letterSpacing:'-.05em',margin:'28px 0 18px'}}>{i18n.t('emergency.title')}</h1><p style={{maxWidth:720,color:'#9db2c5',fontSize:17,lineHeight:1.6}}>{message}</p><div style={{display:'flex',gap:10,flexWrap:'wrap',marginTop:24}}><a href="/" style={linkPrimary}>{i18n.t('emergency.businessSite')}</a><a href="/start" style={linkSecondary}>{i18n.t('emergency.startRequest')}</a><a href="/owner" style={linkSecondary}>{i18n.t('emergency.ownerOS')}</a><a href="/sign-in?role=employee" style={linkSecondary}>{i18n.t('roles.employee')}</a><a href="/sign-in?role=customer" style={linkSecondary}>{i18n.t('roles.customer')}</a></div></div></main>
}
const linkPrimary={background:'#5ad8ff',color:'#021018',padding:'12px 16px',borderRadius:10,textDecoration:'none',fontWeight:900} as const;
const linkSecondary={border:'1px solid rgba(255,255,255,.15)',color:'#f5f9ff',padding:'12px 16px',borderRadius:10,textDecoration:'none'} as const;

class AppBoundary extends Component<PropsWithChildren,{failed:boolean;message:string}>{
 state={failed:false,message:''};
 static getDerivedStateFromError(error:unknown){return{failed:true,message:error instanceof Error?error.message:'Unexpected client-side error'}}
 componentDidCatch(error:unknown,info:ErrorInfo){console.error('SAHJONY_UI_CRASH',error,info)}
 render(){return this.state.failed?<EmergencyScreen message={`${i18n.t('route.notFoundTitle')}: ${this.state.message}`}/>:this.props.children}
}

function hardFallback(reason:string){
 if(!rootElement)return;const safe=reason.replace(/[<>&]/g,'');
 rootElement.innerHTML=`<main style="min-height:100vh;background:#050b13;color:#f5f9ff;font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:28px"><div style="max-width:980px;margin:0 auto"><div style="font-size:12px;font-weight:900;letter-spacing:.16em;color:#5ad8ff">SAHJONY LLC</div><h1>${i18n.t('emergency.title')}</h1><p>${safe}</p><a href="/">${i18n.t('emergency.businessSite')}</a></div></main>`
}
window.addEventListener('error',e=>{console.error('SAHJONY_WINDOW_ERROR',e.error||e.message);setTimeout(()=>{if(rootElement&&!rootElement.textContent?.trim())hardFallback(i18n.t('emergency.browserError'))},0)});
window.addEventListener('unhandledrejection',e=>{console.error('SAHJONY_UNHANDLED_REJECTION',e.reason);setTimeout(()=>{if(rootElement&&!rootElement.textContent?.trim())hardFallback(i18n.t('emergency.operationError'))},0)});

function protectedRoleFromPath(){const first=location.pathname.split('/').filter(Boolean)[0];return first==='customer'||first==='employee'?first:null}
function withI18n(node:ReactNode){return <I18nextProvider i18n={i18n}>{node}</I18nextProvider>}
async function boot(){
 if(!rootElement)return;
 const path=location.pathname;
 if(path==='/sign-in'||path.startsWith('/sign-in/')){
   const {default:NeonAuthPage}=await import('./NeonAuthPage');
   createRoot(rootElement).render(withI18n(<StrictMode><AppBoundary><NeonAuthPage/></AppBoundary></StrictMode>));return
 }
 if(path==='/owner'){location.replace('/owner/dashboard');return}
 if(path==='/owner/intelligence'||path==='/owner/research-intelligence'||path.startsWith('/owner/intelligence/')||path.startsWith('/owner/research-intelligence/')){
   const {default:ResearchIntelligenceCenter}=await import('./ResearchIntelligenceCenter');
   createRoot(rootElement).render(withI18n(<StrictMode><AppBoundary><ResearchIntelligenceCenter/></AppBoundary></StrictMode>));return
 }
 if(path==='/owner/deals'||path.startsWith('/owner/deals/')){
   const {default:DealCommandCenter}=await import('./DealCommandCenter');
   createRoot(rootElement).render(withI18n(<StrictMode><AppBoundary><DealCommandCenter/></AppBoundary></StrictMode>));return
 }
 const role=protectedRoleFromPath();
 if(role&&!sessionStorage.getItem(`sahjony.${role}.token`)){
   const next=encodeURIComponent(location.pathname+location.search);
   location.replace(`/sign-in?role=${role}&next=${next}`);return
 }
 const {default:App}=await import('./App');
 createRoot(rootElement).render(withI18n(<StrictMode><AppBoundary><App/></AppBoundary></StrictMode>));
}
void boot().catch(error=>{console.error('SAHJONY_BOOT_FAILURE',error);hardFallback(i18n.t('emergency.initError'))});
