import json,sys,unicodedata,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from cuba_market_prospects import PROSPECTS
from cuba_market_intelligence import enrich
BATCH='cuba-market-2026-09-10'
def norm(s):
 s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
 return re.sub(r'[^a-z0-9]','',s).replace('surl','').replace('srl','')
buyers=json.loads((ROOT/'data/cuba_buyer_research_2026-09-10.json').read_text())['prospects']
by={norm(p['business_name']):p for p in buyers}
for p in PROSPECTS:
 key=norm(p['business_name'])
 if key in by:
  by[key].update({k:p[k] for k in ['proposal','supplier_ids','next_step']})
 else:buyers.append({**p,'public_emails':[],'public_phones':[]})
rows=[]
for p in buyers:
 p=enrich(p);p.update(kind='BUYER',batch_id=BATCH,organization_id='org_sahjony_global_trade',buyer_company=p['business_name'],buyer_country='CU',product_category=p['sector'],product_description=p['observed_activity'],public_email=(p.get('public_emails') or [None])[0],public_phone=(p.get('public_phones') or [None])[0],qualification_stage='RESEARCH',outreach_status='DO_NOT_AUTO_SEND',demand_evidence_status='UNCONFIRMED')
 # Direct buyer correspondence supersedes category-based inference.
 if 'xproyecto' in norm(p['business_name']):
  p.update(status='FUNDING_REQUIRED',proposal='AGRORENEW busca inversión; abastecimiento de equipos condicionado a financiamiento.',ready_to_quote=False,next_step='Validar el resultado de la reunión técnica y el financiamiento antes de solicitar precios de equipos.',blockers=['FUNDING_NOT_SECURED','NO_CURRENT_PURCHASE_ORDER','CURRENT_SUPPLIER_QUOTE_MISSING'],email_evidence_url='https://mail.google.com/mail/#all/1a0309bf9ac8a3ae')
 rows.append(p)
for s in json.loads((ROOT/'public/data/worldwide-suppliers.json').read_text())['suppliers']:
 rows.append({**s,'id':'supplier-'+s['id'],'supplier_id':s['id'],'kind':'SUPPLIER','batch_id':BATCH,'organization_id':'org_sahjony_global_trade','source_reference':s['source_url'],'qualification_stage':'RESEARCH','outreach_status':'DO_NOT_AUTO_SEND'})
shipping=json.loads((ROOT/'data/cuba_shipping_intelligence_2026-09-10.json').read_text())
for kind,key in [('PROVIDER','providers'),('FREIGHT_QUOTE','quotes')]:
 for p in shipping[key]:rows.append({**p,'id':kind.lower()+'-'+p['id'],'kind':kind,'batch_id':BATCH,'organization_id':'org_sahjony_global_trade','outreach_status':'DO_NOT_AUTO_SEND'})
(ROOT/'data/cuba_crm_import_2026-09-10.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'records':len(rows),'buyers':sum(p['kind']=='BUYER' for p in rows),'buyer_supplier_matches':sum(len(p.get('supplier_ids',[])) for p in rows),'buyers_with_contacts':sum(p['kind']=='BUYER' and bool(p.get('public_email') or p.get('public_phone')) for p in rows)}))
