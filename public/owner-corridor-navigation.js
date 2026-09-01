(()=>{
  const GROUPS=[
    ['OWNER',[
      ['Deal Command Center','/owner/deals'],
      ['Execution Priority','/owner/execution-priority'],
      ['Finance & P&L','/owner/finance']
    ]],
    ['BUSINESS',[
      ['CRM & Opportunities','/owner/crm'],
      ['Global Sourcing','/owner/global-sourcing'],
      ['Suppliers','/suppliers'],
      ['Managed Trade','/owner/managed-trade']
    ]],
    ['OPERATIONS',[
      ['Communications','/owner/communications-os'],
      ['Documents','/owner/documents'],
      ['Shipments','/owner/shipping'],
      ['Compliance & Risk','/owner/compliance']
    ]]
  ];

  function mount(){
    if(!location.pathname.startsWith('/owner'))return;
    const nav=document.querySelector('.grouped-nav');
    if(!nav||nav.querySelector('#sahjony-owner-nav-v4'))return;
    nav.innerHTML='';
    GROUPS.forEach(([title,items],groupIndex)=>{
      const section=document.createElement('section');
      section.className='nav-group';
      if(groupIndex===0)section.id='sahjony-owner-nav-v4';
      const heading=document.createElement('small');
      heading.textContent=title;
      section.appendChild(heading);
      items.forEach(([label,dest])=>{
        const button=document.createElement('button');
        button.type='button';
        const active=location.pathname===dest||((dest!=='/owner')&&location.pathname.startsWith(dest));
        if(active)button.classList.add('active');
        button.innerHTML='<span class="nav-dot"></span><span></span>';
        button.lastElementChild.textContent=label;
        button.addEventListener('click',()=>location.assign(dest));
        section.appendChild(button);
      });
      nav.appendChild(section);
    });
  }

  let timer;
  function schedule(){clearTimeout(timer);timer=setTimeout(mount,40)}
  addEventListener('load',schedule);
  addEventListener('popstate',schedule);
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
  schedule();
})();