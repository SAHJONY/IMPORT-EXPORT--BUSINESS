import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import '../app/globals.css';
import './workflow.css';

const rootElement=document.getElementById('root');

function EmergencyScreen({message='The application encountered a client-side error.'}:{message?:string}){
  return <main style={{minHeight:'100vh',background:'#050b13',color:'#f5f9ff',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',padding:'28px'}}>
    <div style={{maxWidth:980,margin:'0 auto'}}>
      <div style={{fontSize:12,fontWeight:900,letterSpacing:'.16em',color:'#5ad8ff'}}>SAHJONY GLOBAL TRADE</div>
      <h1 style={{fontSize:'clamp(42px,7vw,86px)',lineHeight:.92,letterSpacing:'-.05em',margin:'28px 0 18px'}}>Global Trade Operating System</h1>
      <p style={{maxWidth:720,color:'#9db2c5',fontSize:17,lineHeight:1.6}}>{message} The application shell remains available while the affected module is recovered.</p>
      <div style={{display:'flex',gap:10,flexWrap:'wrap',marginTop:24}}>
        <a href="/" style={{background:'#5ad8ff',color:'#021018',padding:'12px 16px',borderRadius:10,textDecoration:'none',fontWeight:900}}>Business site</a>
        <a href="/start" style={{border:'1px solid rgba(255,255,255,.15)',color:'#f5f9ff',padding:'12px 16px',borderRadius:10,textDecoration:'none'}}>Start sourcing request</a>
        <a href="/owner" style={{border:'1px solid rgba(255,255,255,.15)',color:'#f5f9ff',padding:'12px 16px',borderRadius:10,textDecoration:'none'}}>Owner OS</a>
        <a href="/employee" style={{border:'1px solid rgba(255,255,255,.15)',color:'#f5f9ff',padding:'12px 16px',borderRadius:10,textDecoration:'none'}}>Employee</a>
        <a href="/customer" style={{border:'1px solid rgba(255,255,255,.15)',color:'#f5f9ff',padding:'12px 16px',borderRadius:10,textDecoration:'none'}}>Customer</a>
      </div>
    </div>
  </main>
}

class AppBoundary extends React.Component<React.PropsWithChildren, {failed:boolean;message:string}> {
  state={failed:false,message:''};
  static getDerivedStateFromError(error:unknown){return {failed:true,message:error instanceof Error?error.message:'Unexpected client-side error'};}
  componentDidCatch(error:unknown,info:React.ErrorInfo){console.error('SAHJONY_UI_CRASH',error,info);}
  render(){return this.state.failed?<EmergencyScreen message={`A workspace failed to render: ${this.state.message}`}/>:this.props.children;}
}

function hardFallback(reason:string){
  if(!rootElement)return;
  rootElement.innerHTML=`<main style="min-height:100vh;background:#050b13;color:#f5f9ff;font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:28px"><div style="max-width:980px;margin:0 auto"><div style="font-size:12px;font-weight:900;letter-spacing:.16em;color:#5ad8ff">SAHJONY GLOBAL TRADE</div><h1 style="font-size:clamp(42px,7vw,86px);line-height:.92;letter-spacing:-.05em;margin:28px 0 18px">Global Trade Operating System</h1><p style="max-width:720px;color:#9db2c5;font-size:17px;line-height:1.6">${reason.replace(/[<>&]/g,'')} The application remains accessible through the links below.</p><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:24px"><a href="/" style="background:#5ad8ff;color:#021018;padding:12px 16px;border-radius:10px;text-decoration:none;font-weight:900">Business site</a><a href="/start" style="border:1px solid rgba(255,255,255,.15);color:#f5f9ff;padding:12px 16px;border-radius:10px;text-decoration:none">Start sourcing request</a><a href="/owner" style="border:1px solid rgba(255,255,255,.15);color:#f5f9ff;padding:12px 16px;border-radius:10px;text-decoration:none">Owner OS</a></div></div></main>`;
}

window.addEventListener('error',event=>{
  console.error('SAHJONY_WINDOW_ERROR',event.error||event.message);
  setTimeout(()=>{if(rootElement && !rootElement.textContent?.trim())hardFallback('A browser error interrupted the interface.');},0);
});
window.addEventListener('unhandledrejection',event=>{
  console.error('SAHJONY_UNHANDLED_REJECTION',event.reason);
  setTimeout(()=>{if(rootElement && !rootElement.textContent?.trim())hardFallback('A browser operation failed unexpectedly.');},0);
});

if(rootElement){
  try{
    createRoot(rootElement).render(<React.StrictMode><AppBoundary><App/></AppBoundary></React.StrictMode>);
  }catch(error){
    console.error('SAHJONY_BOOT_FAILURE',error);
    hardFallback('The application could not initialize.');
  }
}
