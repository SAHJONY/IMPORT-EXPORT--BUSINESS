import {useMemo,useState} from 'react';
import {createAuthClient} from '@neondatabase/auth';

const DEFAULT_AUTH_URL='https://ep-empty-shadow-ayfporoz.neonauth.c-5.us-east-2.aws.neon.tech/neondb/auth';
const authUrl=((import.meta as any).env?.VITE_NEON_AUTH_URL||DEFAULT_AUTH_URL).replace(/\/$/,'');
const auth:any=createAuthClient(authUrl);

type AppRole='customer'|'employee';

function nextPath(role:AppRole){
  const params=new URLSearchParams(location.search);
  const requested=params.get('next')||`/${role}`;
  return requested.startsWith(`/${role}`)?requested:`/${role}`;
}

function requestedRole():AppRole{
  return new URLSearchParams(location.search).get('role')==='employee'?'employee':'customer';
}

export default function NeonAuthPage(){
  const role=useMemo(requestedRole,[]);
  const [mode,setMode]=useState<'signin'|'signup'>('signin');
  const [name,setName]=useState('');
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');

  async function finish(){
    const jwtToken=await auth.getJWTToken?.();
    if(!jwtToken)throw new Error('Neon Auth did not return an application JWT. Please sign in again.');
    const check=await fetch('/identity/session',{headers:{Authorization:`Bearer ${jwtToken}`,'X-Role':role}});
    const body=await check.json().catch(()=>({detail:`HTTP ${check.status}`}));
    if(!check.ok)throw new Error(body.detail||'This identity is not approved for this workspace.');
    sessionStorage.setItem(`sahjony.${role}.token`,jwtToken);
    if(role==='employee')sessionStorage.setItem('sahjony.employee.id',String(body.user_id||body.email||'staff'));
    location.assign(nextPath(role));
  }

  async function submit(e:React.FormEvent){
    e.preventDefault();setBusy(true);setMessage('');
    try{
      if(mode==='signup'){
        if(role==='employee')throw new Error('Employee accounts must be approved by SAHJONY. Public employee signup is disabled.');
        const result=await auth.signUp.email({name:name.trim()||email.split('@')[0],email:email.trim(),password});
        if(result?.error)throw new Error(result.error.message||'Unable to create account');
      }else{
        const result=await auth.signIn.email({email:email.trim(),password});
        if(result?.error)throw new Error(result.error.message||'Unable to sign in');
      }
      await finish();
    }catch(error:any){setMessage(error?.message||'Authentication failed.');}
    finally{setBusy(false)}
  }

  return <main style={{minHeight:'100vh',background:'radial-gradient(circle at 15% 0,rgba(90,216,255,.15),transparent 30%),#050b13',color:'#f5f9ff',fontFamily:'Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',display:'grid',placeItems:'center',padding:20}}>
    <section style={{width:'min(100%,520px)',border:'1px solid rgba(255,255,255,.13)',borderRadius:24,background:'linear-gradient(180deg,#0d1d2c,#081522)',padding:28,boxShadow:'0 35px 100px rgba(0,0,0,.35)'}}>
      <a href="/" style={{color:'#9eb5c8',textDecoration:'none',fontSize:12}}>← Back to Home</a>
      <div style={{marginTop:28,fontSize:10,fontWeight:900,letterSpacing:'.18em',color:'#6ed7ff'}}>SAHJONY GLOBAL TRADE · NEON AUTH</div>
      <h1 style={{fontSize:42,lineHeight:.96,letterSpacing:'-.045em',margin:'12px 0 10px'}}>{role==='employee'?'Employee access':'Customer access'}</h1>
      <p style={{color:'#9fb4c6',lineHeight:1.6,marginBottom:22}}>{role==='employee'?'Sign in with an approved SAHJONY employee identity. A normal public account cannot enter employee operations.':'Create or sign in to your secure trade workspace. Authentication is managed by Neon Auth and your application access is verified by SAHJONY.'}</p>
      <form onSubmit={submit} style={{display:'grid',gap:12}}>
        {mode==='signup'&&<input value={name} onChange={e=>setName(e.target.value)} placeholder="Full name" required style={inputStyle}/>} 
        <input value={email} onChange={e=>setEmail(e.target.value)} type="email" placeholder="Email" required autoComplete="email" style={inputStyle}/>
        <input value={password} onChange={e=>setPassword(e.target.value)} type="password" placeholder="Password" required minLength={8} autoComplete={mode==='signup'?'new-password':'current-password'} style={inputStyle}/>
        <button disabled={busy} style={buttonStyle}>{busy?'Authenticating…':mode==='signup'?'Create customer account':'Sign in securely'}</button>
      </form>
      {message&&<div style={{marginTop:14,padding:'11px 12px',border:'1px solid rgba(255,120,130,.35)',borderRadius:10,color:'#ffd5d9',background:'rgba(100,20,30,.25)',fontSize:12,lineHeight:1.5}}>{message}</div>}
      {role==='customer'&&<button onClick={()=>{setMode(mode==='signin'?'signup':'signin');setMessage('')}} style={{marginTop:16,border:0,background:'transparent',color:'#7fd7ff',cursor:'pointer',fontWeight:800}}>{mode==='signin'?'Create a customer account':'Already have an account? Sign in'}</button>}
      <div style={{marginTop:22,paddingTop:16,borderTop:'1px solid rgba(255,255,255,.1)',color:'#718aa0',fontSize:11,lineHeight:1.55}}>Owner authentication remains separate and restricted. Public signup never grants employee, compliance, finance, admin, or release authority.</div>
      {role==='employee'&&<a href="/sign-in?role=customer" style={{display:'inline-block',marginTop:14,color:'#9fb4c6',fontSize:11}}>Customer sign in</a>}
    </section>
  </main>
}

const inputStyle:React.CSSProperties={width:'100%',padding:'13px 14px',borderRadius:11,border:'1px solid rgba(255,255,255,.15)',background:'#06131f',color:'#f5f9ff',font:'inherit'};
const buttonStyle:React.CSSProperties={padding:'14px 16px',border:0,borderRadius:11,background:'linear-gradient(135deg,#5ad8ff,#78efb8)',color:'#021018',fontWeight:950,cursor:'pointer'};
