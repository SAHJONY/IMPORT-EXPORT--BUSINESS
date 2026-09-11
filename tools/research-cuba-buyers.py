"""Collect public company profiles; never infer a purchase order from a listing."""
import concurrent.futures, hashlib, html, json, re, subprocess, time
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=Path('/private/tmp/sahjony-cuba-research');CACHE.mkdir(exist_ok=True)
def fetch(url):
 p=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.html')
 if not p.exists():
  r=subprocess.run(['curl','-f','-sS','-L','--max-time','25',url],capture_output=True)
  if r.returncode: raise RuntimeError('fetch failed')
  p.write_bytes(r.stdout);time.sleep(.15)
 return p.read_text(errors='replace')
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',s))).strip()
def grab(s,pattern):
 m=re.search(pattern,s,re.S);return clean(m.group(1)) if m else ''
def section(s,title):return grab(s,r'<h2>'+re.escape(title)+r'</h2>\s*<p[^>]*>(.*?)</p>')
def research(url):
 try:
  s=fetch(url);name=grab(s,r'<h1[^>]*>(.*?)</h1>');meta=grab(s,r'<div class="emp-detail-meta">(.*?)</div>')
  if not name or not any(t in meta for t in ['Privada','Trabajo por cuenta propia']):return None
  activity=section(s,'¿A qué se dedica?');need=section(s,'¿Qué busca?')
  # Keep short original evidence and explicitly distinguish directory proposals from RFQs.
  activity=' '.join(activity.split()[:65]);need=' '.join(need.split()[:45])
  contact=re.search(r'<h3>Contacto</h3>(.*?)(?=<div class="emp-contact-card|</aside>|<footer)',s,re.S)
  c=contact.group(1) if contact else ''
  emails=set(re.findall(r'mailto:([^"?<> ]+)',c))
  emails.update(u+'@'+d for u,d in re.findall(r'data-user="([^"]+)" data-domain="([^"]+)"',c))
  phones=list(dict.fromkeys(re.findall(r'(?:wa.me/|tel:)(\+?\d{8,15})',c)))
  category=grab(s,r'<span class="emp-sector-tag"[^>]*>(.*?)</span>')
  business_links=[html.unescape(u) for u in re.findall(r'href="(https?://[^"]+)"',c) if not any(x in u for x in ['cemis.io','wa.me/'])]
  return {'id':'cemis-'+url.rsplit('/',1)[-1].replace('.html',''),'business_name':name,'province':meta.split('·')[1].strip() if '·' in meta else 'Cuba','sector':category,'observed_activity':activity,'published_interest':need if need and not any(x in need for x in ['Aún no se ha especificado','No especificad']) else None,'source_url':url,'evidence_urls':[],'public_emails':sorted(emails),'public_phones':phones,'company_links':business_links,'source_classification':meta,'ownership_evidence':'Clasificada como privada por CEMÍS; propiedad actual pendiente de KYB.','status':'RESEARCH_PROSPECT','researched_on':'2026-09-10','destination_country':'CU','demand_confirmed':False,'estimated_deal_value':None,'consent_to_business_contact':False}
 except Exception:return {'error':url}
def main():
 sitemap=fetch('https://cemis.io/sitemap.xml');urls=[x.text for x in ET.fromstring(sitemap).iter() if x.tag.endswith('loc') and '/empresas/' in (x.text or '') and not x.text.endswith('/index.html')]
 rows=[];errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for i,row in enumerate(pool.map(research,urls),1):
   if row and 'error' in row:errors.append(row['error'])
   elif row:rows.append(row)
   if i%40==0:print(json.dumps({'processed':i,'private_profiles':len(rows)}),flush=True)
 seen=set();rows=[r for r in rows if not (r['business_name'].casefold() in seen or seen.add(r['business_name'].casefold()))]
 out={'researched_on':'2026-09-10','source':'https://cemis.io/sitemap.xml','method':'Public company profiles, limited excerpts, explicit business contact links only. Directory interest is not buyer-confirmed demand.','prospects':rows,'failed_urls':errors}
 (ROOT/'data/cuba_buyer_research_2026-09-10.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'private_profiles':len(rows),'with_email':sum(bool(r['public_emails']) for r in rows),'with_phone':sum(bool(r['public_phones']) for r in rows),'published_interest':sum(bool(r['published_interest']) for r in rows),'errors':len(errors)}))
if __name__=='__main__':main()
