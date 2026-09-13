import json,re,unicodedata
from pathlib import Path
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
def norm(s):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()).replace('surl','').replace('srl','')
p=ROOT/'data/cuba_buyer_research_2026-09-10.json';data=json.loads(p.read_text());rows=data['prospects'];by={norm(r['business_name']):r for r in rows}
source='https://www.ipscuba.net/especial/nuevos-actores-economicos/assets/store/files/directorio-nuevos-actores-economicos.pdf'
added=enriched=0
for i,page in enumerate(PdfReader('/private/tmp/cuba-private-directory.pdf').pages):
 t=page.extract_text() or '';lines=[s.strip() for s in t.splitlines() if s.strip()]
 if i<5 or not re.search(r'mipyme privada|trabaj[ao]dora? por cuenta propia',t,re.I):continue
 name=lines[1] if lines[0].isdigit() else lines[0]
 emails=list(set(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',t)))
 phones=list(set('53'+re.sub(r'\D','',x) for x in re.findall(r'\+53\s*((?:\d[ \-]*){8})',t)))
 evidence=source+'#page='+str(i+1)
 if norm(name) in by:
  r=by[norm(name)];r['public_emails']=sorted(set(r['public_emails']+emails));r['public_phones']=sorted(set(r['public_phones']+phones));r['evidence_urls'].append(evidence);enriched+=1;continue
 provinces=['Pinar del Río','La Habana','Artemisa','Mayabeque','Matanzas','Villa Clara','Cienfuegos','Sancti Spíritus','Ciego de Ávila','Camagüey','Las Tunas','Holguín','Granma','Santiago de Cuba','Guantánamo','Isla de la Juventud']
 province=next((s for s in reversed(provinces) if s in t),'Cuba')
 category=next((label for pattern,label in [('alimento|panader|gastronom|gelato','Alimentos y gastronomía'),('solar|fotovolta','Solar y energía'),('mueble|calzado|textil|confecci','Manufactura'),('construcci','Construcción'),('software|informát','Tecnología'),('transporte|mensajería','Logística')] if re.search(pattern,t,re.I)),'Servicios privados')
 row={'id':'ips-'+norm(name),'business_name':name,'province':province,'sector':category,'observed_activity':category,'published_interest':None,'source_url':evidence,'evidence_urls':[],'public_emails':emails,'public_phones':phones,'company_links':[],'source_classification':'Mipyme privada / TCP según directorio IPS 2025','ownership_evidence':'Clasificación publicada en 2025; confirmar propiedad y actividad actuales.','status':'RESEARCH_PROSPECT','researched_on':'2026-09-10','destination_country':'CU','demand_confirmed':False,'estimated_deal_value':None,'consent_to_business_contact':False,'contact_source_date':'2025'}
 rows.append(row);by[norm(name)]=row;added+=1
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'total_buyers':len(rows),'ips_added':added,'contacts_enriched':enriched,'with_contact':sum(bool(r['public_emails'] or r['public_phones']) for r in rows)}))
