(()=>{
  const GROUPS=[
    ['TODAY',[
      ['Executive Dashboard','/owner'],
      ['Execution Priority','/owner/execution-priority'],
      ['Profit Machine','/owner/profit-machine']
    ]],
    ['RECORDS',[
      ['★ Records Hub','/owner-records.html'],
      ['Cuba MIPYMEs','/owner/cuba-mipymes'],
      ['Suppliers','/suppliers'],
      ['Partners & Gestores','/owner/cuba-partners'],
      ['Buyers / CRM by Country','/owner/crm-countries'],
      ['External / Research Records','/owner-external-prospects.html'],
      ['Global Lead Search','/owner/lead-search']
    ]],
    ['DEALS & REVENUE',[
      ['CRM & Opportunities','/owner/crm'],
      ['Managed Trade','/owner/managed-trade'],
      ['Global Sourcing','/owner/global-sourcing'],
      ['Intermediary Desk','/owner/intermediary'],
      ['Finance & P&L','/owner/finance'],
      ['Energy Deal Flow','/owner/energy/deal-flow'],
      ['Energy Revenue','/owner/energy/revenue']
    ]],
    ['COUNTRIES',[
      ['🇨🇺 Cuba Bureau','/countries/cuba'],
      ['Country Intelligence','/owner/countries'],
      ['Cuba Trade Department','/owner/cuba-us-desk'],
      ['Cuba Energy Desk','/owner/cuba-energy'],
      ['Cuba Private Fuels','/owner/cuba-fuels'],
      ['Cuba Consumers','/owner/cuba-consumers']
    ]],
    ['COMMUNICATIONS',[
      ['Communication OS','/owner/communications-os'],
      ['WhatsApp','/owner/whatsapp'],
      ['WhatsApp Doctor','/owner-whatsapp-doctor.html'],
      ['Business Email','/owner/email'],
      ['Telegram Control','/owner/telegram']
    ]],
    ['OPERATIONS',[
      ['Documents','/owner/documents'],
      ['Shipments','/owner/shipping'],
      ['U.S. Import Desk','/owner/us-import'],
      ['Energy Operations','/owner/energy/operations'],
      ['Energy Transaction Room','/owner/energy/closing']
    ]],
    ['CONTROL',[
      ['Compliance & Risk','/owner/compliance'],
      ['AI Intelligence','/owner/ai-brain'],
      ['Launch Readiness','/owner/readiness'],
      ['Business Communications Admin','/owner/business-email'],
      ['Energy Executive Hub','/owner/energy'],
      ['Energy Intelligence','/owner/energy/intelligence'],
      ['Energy Providers','/owner/energy/providers'],
      ['Energy Compliance','/owner/energy/compliance'],
      ['Data Control','/owner/data-control']
    ]]
  ];
  function mount(){
    if(!location.pathname.startsWith('/owner'))return;
    const nav=document.querySelector('.grouped-nav');
    if(!nav||nav.querySelector('#sahjony-owner-nav-v3'))return;
    nav.innerHTML='';
    GROUPS.forEach(([title,items],groupIndex)=>{
      const section=document.createElement('section');
      section.className='nav-group';
      if(groupIndex===0)section.id='sahjony-owner-nav-v3';
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