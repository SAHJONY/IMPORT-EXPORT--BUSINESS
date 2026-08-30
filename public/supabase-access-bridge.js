(()=>{
  const role=location.pathname.split('/').filter(Boolean)[0];
  if(!['customer','employee'].includes(role)) return;
  const tokenKey=`sahjony.${role}.token`;
  function wire(){
    if(sessionStorage.getItem(tokenKey)) return;
    const gate=document.querySelector('.credential-gate');
    if(!gate||gate.querySelector('[data-supabase-login]')) return;
    const a=document.createElement('a');
    a.dataset.supabaseLogin='true';
    a.href=`/supabase-login.html?role=${encodeURIComponent(role)}`;
    a.textContent='Sign in with Supabase';
    a.style.display='inline-flex';
    a.style.alignItems='center';
    a.style.justifyContent='center';
    a.style.minHeight='48px';
    a.style.padding='0 18px';
    a.style.marginTop='12px';
    a.style.borderRadius='10px';
    a.style.fontWeight='800';
    a.style.textDecoration='none';
    a.style.background='linear-gradient(135deg,#5ad8ff,#74efb5)';
    a.style.color='#031017';
    gate.appendChild(a);
    const note=document.createElement('p');
    note.dataset.supabaseLogin='true';
    note.textContent='Supabase Auth is the canonical login. The credential field above remains only as a temporary session-token compatibility path.';
    note.style.fontSize='12px';
    note.style.opacity='.72';
    note.style.marginTop='10px';
    gate.appendChild(note);
  }
  addEventListener('DOMContentLoaded',wire);
  new MutationObserver(wire).observe(document.documentElement,{childList:true,subtree:true});
})();
