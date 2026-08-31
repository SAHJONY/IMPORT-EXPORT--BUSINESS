import hashlib, io, os, re, unicodedata
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException, Query
from pypdf import PdfReader

app=FastAPI(title='SAHJONY Cuba Private Sector CRM',version='3.1.0',docs_url=None,redoc_url=None)
ORG='org_sahjony_global_trade'; TARGET=15600; INDEX='https://www.minjus.gob.cu/es/publicaciones/prontuario'
SOURCES={
'2026-02-03':('Relación CNA-MIPYMES Registro Mercantil 03.02.2026','https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/Febrero%203.2026%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%20%203.02.26%20.pdf'),
'2026-01-29':('Relación CNA-MIPYMES Registro Mercantil 29.01.2026','https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/Enero%202026%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%20%2029.01.26%20.pdf'),
'2025-12-26':('Relación CNA-MIPYMES Registro Mercantil 26.12.2025','https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/Diciembre%202025%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%2026.12.25%20.pdf'),
'2025-11-06':('Relación CNA-MIPYMES Registro Mercantil 06.11.2025','https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/Noviembre%202025%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%206.11.25%20.pdf'),
'2025-10-30':('Relación CNA-MIPYMES Registro Mercantil 30.10.2025','https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/Octubre%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%2030.10.25.pdf')}
PRIVATE={'MIPYME_PRIVADA','CNA','EMPRESA_PRIVADA','OTHER_NON_STATE_VERIFIED'}
BAD=('actividad principal','objeto social','domicilio','comercializar','brindar servicios','municipio ','provincia ','república de cuba','republica de cuba','artículo ','articulo ','calle ','carretera ','avenida ')

def norm(v):
 t=unicodedata.normalize('NFKD',str(v or '')); t=''.join(c for c in t if not unicodedata.combining(c)); return re.sub(r'[^a-z0-9]+',' ',t.casefold()).strip()
def clean(v): return re.sub(r'\s+',' ',str(v or '')).strip(' \t\r\n,;:-')
def cfg():
 u=os.getenv('SUPABASE_URL','').rstrip('/'); k=os.getenv('SUPABASE_SERVICE_ROLE_KEY','').strip()
 if not u or not k: raise RuntimeError('Supabase server credentials are not configured')
 return u,k
async def rows():
 u,k=cfg(); h={'apikey':k,'Authorization':f'Bearer {k}','Accept':'application/json'}; out=[]; off=0
 async with httpx.AsyncClient(timeout=30) as c:
  while True:
   r=await c.get(f'{u}/rest/v1/sahjony_trade_records',headers=h,params={'logical_table':'eq.external_trade_prospects','select':'record_key,data','order':'record_key.asc','limit':'1000','offset':str(off)}); r.raise_for_status(); p=r.json() if r.content else []
   if not p: break
   for x in p:
    if isinstance(x.get('data'),dict): y=dict(x['data']); y['_record_key']=x.get('record_key'); out.append(y)
   if len(p)<1000: break
   off+=len(p)
 return out
async def upsert(items):
 if not items:return 0
 u,k=cfg(); h={'apikey':k,'Authorization':f'Bearer {k}','Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'}
 async with httpx.AsyncClient(timeout=60) as c:
  for i in range(0,len(items),100):
   r=await c.post(f'{u}/rest/v1/sahjony_trade_records',params={'on_conflict':'logical_table,record_key'},headers=h,json=items[i:i+100]); r.raise_for_status()
 return len(items)
async def download(url):
 async with httpx.AsyncClient(timeout=120,follow_redirects=True) as c:
  r=await c.get(url,headers={'User-Agent':'SAHJONY-CRM-Ingestion/3.1'}); r.raise_for_status(); return r.content

def province(text):
 m=re.findall(r'REGISTRO\s+MERCANTIL\s+([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ .\'-]{2,45}?)\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}',clean(text),re.I)
 return clean(m[-1]).title() if m else None
def good_name(n):
 q=norm(n); low=n.casefold(); return bool(q and 2<=len(n)<=140 and q not in {'srl','s r l','surl','s u r l','sociedad mercantil','mercantil'} and len(q.split())<=14 and not any(x in low for x in BAD))
def get_name(prefix):
 raw=clean(prefix); state=bool(re.search(r'\bEstatal\b',raw,re.I)); ds=list(re.finditer(r'\bdenominad[ao]\b',raw,re.I)); raw=raw[ds[-1].end():] if ds else raw; raw=re.sub(r'^\d{1,5}\s+','',raw)
 raw=re.sub(r'^(?:(?:Sociedad\s+Mercantil\s+)?(?:Estatal,?\s+)?(?:bajo\s+la\s+forma\s+de\s+)?(?:Sociedad\s+)?(?:Unipersonal\s+)?(?:de\s+Responsabilidad\s+Limitada,?\s+)?(?:de\s+nacionalidad\s+cubana,?\s+)?(?:en\s+su\s+forma\s+abreviada\s+)?)+','',raw,flags=re.I); raw=clean(raw.strip('“”"'))
 return (raw if good_name(raw) else None),state
def parse_page(text,pno,prov):
 ls=[clean(x) for x in text.replace('\x00',' ').splitlines() if clean(x)]; starts=[]
 for i,l in enumerate(ls):
  m=re.match(r'^(\d{1,5})(?:\s+(.*))?$',l)
  if not m or not (1<=int(m.group(1))<=5000): continue
  rest=clean(m.group(2) or ''); ev=rest+' '+' '.join(ls[i+1:i+8])
  if rest or re.search(r'(?:S\.?R\.?L|S\.?U\.?R\.?L|Sociedad\s+Mercantil|Cooperativa|CNA|denominad[ao])',ev,re.I): starts.append(i)
 out=[]
 for z,s in enumerate(starts):
  b=clean(' '.join(ls[s:starts[z+1] if z+1<len(starts) else len(ls)])); nm=re.match(r'^(\d{1,5})\b',b); ins=re.search(r'\b([IVXLCDM]{1,10})\s+(\d{1,4})\s+(\d{1,6})\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b',b,re.I)
  if not nm or not ins: continue
  name,state=get_name(b[:ins.start()])
  if state or not name: continue
  aft=b[ins.end():]; bd=re.search(r'\b(?:Domicilio(?:\s+Social)?|Municipio|Provincia|Calle|Carretera|Avenida|Ave\.|Reparto|Representante|Tel[eé]fono|Correo)\b',aft,re.I); spill=re.search(r'\s+\d{1,5}\s+[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ .&´’\'-]{2,80}\s+[IVXLCDM]{1,10}\s+\d{1,4}\s+\d{1,6}\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}',aft); cut=min([m.start() for m in (bd,spill) if m] or [len(aft)]); act=clean(aft[:cut]); act=act[:1200] if len(act)>=4 else None
  mm=re.search(r'\bMunicipio\s+([A-ZÁÉÍÓÚÜÑa-záéíóúüñ .\'-]{2,45}?)(?=\s+(?:Provincia|provincia|Cuba|República|Republica|$))',b); em=re.search(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}',b,re.I); ph=re.findall(r'(?<!\d)(?:\+?53\s*)?(\d{8,10})(?!\d)',b)
  out.append({'n':nm.group(1),'name':name,'province':prov,'municipality':clean(mm.group(1)).title() if mm else None,'page':pno,'actor_type':'CNA' if ('cooperativa no agropecuaria' in norm(b[:ins.start()]) or 'cooperativa' in norm(b[:ins.start()])) else 'MIPYME_PRIVADA','activity':act,'email':em.group(0) if em else None,'phone':ph[-1] if ph else None,'reg':f'{ins.group(1).upper()}-{ins.group(2)}-{ins.group(3)}','date':ins.group(4)})
 return out
def parse(content):
 r=PdfReader(io.BytesIO(content)); texts=[p.extract_text() or '' for p in r.pages]; ps=[province(t) for t in texts]; last=None
 for i in range(len(ps)):
  if ps[i]:last=ps[i]
  elif last:ps[i]=last
 nxt=None
 for i in range(len(ps)-1,-1,-1):
  if ps[i]:nxt=ps[i]
  elif nxt:ps[i]=nxt
 out=[]; seen=set(); reject=0
 for i,t in enumerate(texts):
  for x in parse_page(t,i+1,ps[i]):
   k=(norm(x['name']),x['reg'])
   if not k[0] or k in seen: reject+=1; continue
   seen.add(k); out.append(x)
 return out,len(texts),reject

def is_private(r):
 name=r.get('buyer_company') or r.get('company_name') or r.get('business_name'); typ=str(r.get('actor_type') or '').upper(); src=' '.join(str(r.get(k) or '') for k in ('source_platform','source_name','source_type','source_provenance','external_reference')).casefold()
 status=str(r.get('registry_status') or '').upper()
 if not norm(name) or 'ESTATAL' in typ or status in {'DISSOLVED','DISSUELTA','CANCELLED','CANCELED','CANCELADA','BAJA'}: return False
 return bool(typ in PRIVATE or 'minjus' in src or 'registro mercantil' in src or 'mep' in src or str(r.get('external_reference') or '').upper().startswith('RM-'))
def data(c,sid,src,now,today):
 act=c.get('activity'); prov=c.get('province'); muni=c.get('municipality'); ref=f"RM-{norm(prov or 'CU').replace(' ','-').upper()}-{c['n']}-{c['reg']}"
 return {'organization_id':ORG,'buyer_company':c['name'],'company_name':c['name'],'business_name':c['name'],'buyer_country':'CU','country':'Cuba','province':prov,'municipality':muni,'destination':', '.join(x for x in (muni,prov,'Cuba') if x),'actor_type':c['actor_type'],'primary_activity':act,'activity':act,'product_category':act,'product_description':act,'public_email':c.get('email'),'public_phone':c.get('phone'),'buyer_contact':c.get('phone') or c.get('email'),'external_reference':ref,'registry_reference':c['reg'],'registry_number':c['n'],'registry_date':c['date'],'source_type':'OFFICIAL_REGISTRY_EXTRACTION','source_platform':'MINJUS Registro Mercantil','source_name':src[0],'source_url':src[1],'source_provenance':f"Name-level extraction from official MINJUS Registro Mercantil PDF, page {c['page']}; source snapshot {sid}.",'verification_status':'RESEARCH_VERIFIED','registry_status':'REGISTERED','verification_date':today,'outreach_status':'DO_NOT_AUTO_SEND','qualification_stage':'RESEARCH','ownership_verification_status':'NOT_PUBLICLY_VERIFIED','ownership_note':'Registry evidence does not establish current buyer demand or beneficial ownership.','import_export_relevance':'RESEARCH_PENDING_QUALIFICATION','evidence_summary':'Official MINJUS Registro Mercantil name-level record; not an active RFQ without independent demand evidence.','next_action':'Enrich public contacts and import/export relevance; independently qualify before outreach','created_at':now,'updated_at':now}
async def preview_source(sid):
 if sid not in SOURCES: raise HTTPException(404,'Unknown MINJUS source')
 cand,pages,reject=parse(await download(SOURCES[sid][1])); ex={norm(r.get('buyer_company') or r.get('company_name') or r.get('business_name')) for r in await rows()}; new=[c for c in cand if norm(c['name']) not in ex]
 return {'status':'ok','source_id':sid,'source':SOURCES[sid][1],'official_index':INDEX,'pages':pages,'parsed_unique':len(cand),'rejected_or_duplicate_in_source':reject,'new_vs_crm':len(new),'sample':new[:30]}
async def ingest_source(sid):
 if sid not in SOURCES: raise HTTPException(404,'Unknown MINJUS source')
 old=await rows(); by={}; private_before=set()
 for r in old:
  k=norm(r.get('buyer_company') or r.get('company_name') or r.get('business_name'))
  if k and k not in by:by[k]=r
  if k and is_private(r):private_before.add(k)
 cand,pages,reject=parse(await download(SOURCES[sid][1])); now=datetime.now(timezone.utc).isoformat(); today=datetime.now(timezone.utc).date().isoformat(); pending=[]; ins=upd=dup=0; local=set()
 for c in cand:
  k=norm(c['name'])
  if not k or k in local:dup+=1;continue
  local.add(k); inc=data(c,sid,SOURCES[sid],now,today); ex=by.get(k)
  if ex:
   merged={a:b for a,b in ex.items() if a!='_record_key'}; changed=False
   for f in ('province','municipality','destination','primary_activity','activity','product_category','product_description','public_email','public_phone','buyer_contact','external_reference','registry_reference','registry_number','registry_date'):
    if inc.get(f) and not merged.get(f):merged[f]=inc[f];changed=True
   if inc.get('actor_type') and merged.get('actor_type')!=inc['actor_type']: merged['actor_type']=inc['actor_type']; changed=True
   for f in ('source_type','source_platform','source_name','source_url','source_provenance','verification_status','registry_status','verification_date','evidence_summary','next_action','import_export_relevance'):
    if inc.get(f) and merged.get(f)!=inc[f]:merged[f]=inc[f];changed=True
   if not changed or not ex.get('_record_key'):dup+=1;continue
   merged['updated_at']=now; pending.append({'logical_table':'external_trade_prospects','record_key':ex['_record_key'],'data':merged,'created_at':merged.get('created_at') or now,'updated_at':now});upd+=1
  else:
   rk='minjus:'+hashlib.sha1(f"{k}|{inc['external_reference']}".encode()).hexdigest()[:24]; pending.append({'logical_table':'external_trade_prospects','record_key':rk,'data':inc,'created_at':now,'updated_at':now}); by[k]={**inc,'_record_key':rk};ins+=1
 await upsert(pending); after=private_before|{norm(c['name']) for c in cand if norm(c.get('name'))}
 return {'status':'ok','source_id':sid,'source':SOURCES[sid][1],'source_pages':pages,'parsed_unique':len(cand),'rejected_or_duplicate_in_source':reject,'inserted':ins,'updated':upd,'duplicates_skipped':dup,'current_before':len(private_before),'current_unique':len(after),'target':TARGET,'remaining_shortfall':max(TARGET-len(after),0),'classification':'RESEARCH / VERIFIED PUBLIC SOURCE'}

@app.get('/crm/cuba-mipymes/internal/sources')
async def source_list(): return {'status':'ok','target':TARGET,'official_index':INDEX,'sources':SOURCES}
@app.get('/crm/cuba-mipymes/internal/preview-minjus')
async def preview(source:str=Query('2026-02-03')): return await preview_source(source)
@app.get('/crm/cuba-mipymes/internal/ingest-minjus')
async def ingest(source:str=Query('2026-02-03')): return await ingest_source(source)
@app.get('/crm/cuba-mipymes/internal/preview-minjus-2026')
async def old_preview(): return await preview_source('2026-02-03')
@app.get('/crm/cuba-mipymes/internal/ingest-minjus-2026')
async def old_ingest(): return await ingest_source('2026-02-03')
@app.get('/crm/internal/ingest-cuba-actors-3000')
async def mep_ceiling():
 cur=len({norm(r.get('buyer_company') or r.get('company_name') or r.get('business_name')) for r in await rows() if is_private(r)}); return {'status':'source_ceiling','source':'MEP accumulated list through May 2024','inserted':0,'updated':0,'duplicates_skipped':cur,'current_unique':cur,'target':TARGET,'remaining_shortfall':max(TARGET-cur,0),'next_source':'MINJUS Registro Mercantil 2025-2026'}
@app.get('/cuba-mipymes-api/health')
@app.get('/crm/cuba-mipymes/health')
async def health():
 cur=len({norm(r.get('buyer_company') or r.get('company_name') or r.get('business_name')) for r in await rows() if is_private(r)}); return {'status':'ok','service':'cuba-private-sector-read-only-crm','version':'3.1.0','record_count':cur,'target':TARGET,'remaining_shortfall':max(TARGET-cur,0),'source_scope':'public_registry_and_official_actor_lists_research','ownership_policy':'evidence_only','binding_actions':False}
@app.get('/cuba-mipymes-api/list')
@app.get('/crm/cuba-mipymes')
@app.get('/crm/cuba-mipymes/list')
async def list_records():
 seen=set(); out=[]
 for r in await rows():
  k=norm(r.get('buyer_company') or r.get('company_name') or r.get('business_name'))
  if not k or k in seen or not is_private(r):continue
  seen.add(k); out.append({x:r.get(x) for x in ('external_reference','buyer_company','buyer_country','buyer_contact','public_email','public_phone','actor_type','province','municipality','product_category','product_description','destination','source_type','source_platform','source_name','source_provenance','source_url','verification_status','registry_status','verification_date','qualification_stage','import_export_relevance','evidence_summary','next_action','created_at','updated_at')})
 out.sort(key=lambda x:str(x.get('buyer_company') or '').casefold()); return {'status':'ok','count':len(out),'records':out,'classification':'RESEARCH / VERIFIED PUBLIC SOURCE','notice':'Registry-only records are not active buyers or RFQs without independent demand evidence.'}
