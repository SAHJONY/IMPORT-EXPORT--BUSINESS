from __future__ import annotations
import json, os, secrets, urllib.error, urllib.parse, urllib.request
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from auth import verify_owner_token
from communication_agentic_api import ContactCreate, EndpointCreate, add_endpoint, create_contact

app=FastAPI(title="SAHJONY Private Google Contacts",docs_url=None,redoc_url=None)
TOKEN_URL=os.getenv("GOOGLE_TOKEN_URL","https://oauth2.googleapis.com/token")
PEOPLE_API=os.getenv("GOOGLE_PEOPLE_API_BASE","https://people.googleapis.com/v1").rstrip("/")
FIELDS="names,emailAddresses,phoneNumbers,organizations,memberships,biographies,birthdays,addresses,relations,urls"
def _env(*names): return next((os.getenv(n,"").strip() for n in names if os.getenv(n,"").strip()),"")
def _config(): return (_env("GOOGLE_CONTACTS_CLIENT_ID","GOOGLE_CALENDAR_CLIENT_ID","GMAIL_CLIENT_ID"),_env("GOOGLE_CONTACTS_CLIENT_SECRET","GOOGLE_CALENDAR_CLIENT_SECRET","GMAIL_CLIENT_SECRET"),_env("GOOGLE_CONTACTS_REFRESH_TOKEN","GOOGLE_CALENDAR_REFRESH_TOKEN","GMAIL_REFRESH_TOKEN"))
def _auth(bearer,sofia,owner_only=False):
    if bearer and bearer.startswith("Bearer ") and verify_owner_token(bearer.removeprefix("Bearer ").strip()): return "owner"
    expected=_env("SOFIA_OWNER_CONTACTS_SECRET")
    if not owner_only and len(expected)>=32 and sofia and secrets.compare_digest(expected,sofia): return "sofia"
    raise HTTPException(403,"Private owner authorization required")
def _http(url,method="GET",headers=None,data=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,method=method,headers=headers or {},data=data),timeout=25) as r:
            raw=r.read().decode(); return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if e.code in (401,403): raise HTTPException(503,"Authorize Google Contacts with contacts.readonly") from e
        raise HTTPException(502,f"Google Contacts HTTP {e.code}") from e
    except Exception as e: raise HTTPException(502,f"Google Contacts unavailable: {type(e).__name__}") from e
def _token():
    cid,secret,refresh=_config()
    if not all((cid,secret,refresh)): raise HTTPException(503,"Google Contacts OAuth is not configured")
    body=urllib.parse.urlencode({"client_id":cid,"client_secret":secret,"refresh_token":refresh,"grant_type":"refresh_token"}).encode()
    token=str(_http(TOKEN_URL,"POST",{"Content-Type":"application/x-www-form-urlencoded"},body).get("access_token") or "")
    if not token: raise HTTPException(502,"Google did not return an access token")
    return token
def _people(path): return _http(f"{PEOPLE_API}/{path}",headers={"Authorization":f"Bearer {_token()}"})
def _items(p,key): return [{"value":x.get("value"),"type":x.get("type") or x.get("formattedType"),"primary":bool((x.get("metadata") or {}).get("primary"))} for x in p.get(key) or [] if x.get("value")]
def _contact(p):
    names=p.get("names") or [{}]; orgs=p.get("organizations") or [{}]
    name=next((x for x in names if (x.get("metadata") or {}).get("primary")),names[0]); org=next((x for x in orgs if (x.get("metadata") or {}).get("primary")),orgs[0])
    return {"resource_name":p.get("resourceName"),"etag":p.get("etag"),"display_name":name.get("displayName") or "Unnamed contact","given_name":name.get("givenName"),"family_name":name.get("familyName"),"company":org.get("name"),"title":org.get("title"),"department":org.get("department"),"emails":_items(p,"emailAddresses"),"phones":_items(p,"phoneNumbers"),"addresses":[x.get("formattedValue") for x in p.get("addresses") or [] if x.get("formattedValue")],"birthdays":[x.get("date") for x in p.get("birthdays") or [] if x.get("date")],"notes":[x.get("value") for x in p.get("biographies") or [] if x.get("value")],"suggested_context":"business" if org.get("name") or org.get("title") else "personal","owner_private":True,"public_visibility":False,"crm_member":False}
def _connections(limit):
    out=[]; page=""
    while len(out)<limit:
        q={"personFields":FIELDS,"pageSize":str(min(1000,limit-len(out))),"sortOrder":"LAST_NAME_ASCENDING"}
        if page:q["pageToken"]=page
        data=_people("people/me/connections?"+urllib.parse.urlencode(q)); out += [_contact(x) for x in data.get("connections") or []]; page=str(data.get("nextPageToken") or "")
        if not page:break
    return out[:limit]
class Promote(BaseModel):
    context: Literal["personal","business"]
    consent_status: Literal["UNKNOWN","CONSENTED","TRANSACTIONAL_ONLY","REVOKED","DO_NOT_CONTACT"]="UNKNOWN"
@app.get("/communications-os/google-contacts/health")
def health(authorization:str|None=Header(None,alias="Authorization"),x_sofia_owner_secret:str|None=Header(None,alias="X-Sofia-Owner-Secret")):
    actor=_auth(authorization,x_sofia_owner_secret); configured=all(_config()); return {"status":"ok" if configured else "configuration_required","actor":actor,"provider":"google_people","oauth_configured":configured,"required_scope":"https://www.googleapis.com/auth/contacts.readonly","emails_included":True,"personal_contacts_private":True,"automatic_crm_import":False}
@app.get("/communications-os/google-contacts")
def contacts(search:str|None=Query(None,max_length=200),context:Literal["all","personal","business"]="all",limit:int=Query(500,ge=1,le=5000),authorization:str|None=Header(None,alias="Authorization"),x_sofia_owner_secret:str|None=Header(None,alias="X-Sofia-Owner-Secret")):
    actor=_auth(authorization,x_sofia_owner_secret); rows=_connections(limit)
    if context!="all": rows=[x for x in rows if x["suggested_context"]==context]
    if search: rows=[x for x in rows if search.casefold() in json.dumps(x,ensure_ascii=False).casefold()]
    return {"status":"ok","actor":actor,"count":len(rows),"contacts":rows,"owner_private":True,"public_visibility":False}
@app.get("/communications-os/google-contacts/{resource_id}")
def contact(resource_id:str,authorization:str|None=Header(None,alias="Authorization"),x_sofia_owner_secret:str|None=Header(None,alias="X-Sofia-Owner-Secret")):
    actor=_auth(authorization,x_sofia_owner_secret); rid=urllib.parse.quote(resource_id.removeprefix("people/"),safe=""); return {"status":"ok","actor":actor,"contact":_contact(_people(f"people/{rid}?"+urllib.parse.urlencode({"personFields":FIELDS})))}
@app.post("/communications-os/google-contacts/{resource_id}/promote")
async def promote(resource_id:str,payload:Promote,authorization:str|None=Header(None,alias="Authorization"),x_sofia_owner_secret:str|None=Header(None,alias="X-Sofia-Owner-Secret")):
    _auth(authorization,x_sofia_owner_secret,True)
    if payload.context!="business": raise HTTPException(409,"Personal contacts cannot be promoted to the business CRM")
    rid=urllib.parse.quote(resource_id.removeprefix("people/"),safe=""); source=_contact(_people(f"people/{rid}?"+urllib.parse.urlencode({"personFields":FIELDS})))
    created=await create_contact(ContactCreate(display_name=source["display_name"],company=source.get("company"),title=source.get("title"),notes="Owner-approved Google Contacts business import."),authorization); cid=created["contact"]["contact_id"]; endpoints=[]
    for channel,values in (("email",source["emails"]),("phone",source["phones"])):
        for i,value in enumerate(values):
            result=await add_endpoint(cid,EndpointCreate(channel=channel,destination=value["value"],label=value.get("type"),preferred=bool(value.get("primary") or i==0),verified=True,verification_source="google_people_owner_import",consent_status=payload.consent_status,consent_source="owner_classification"),authorization); endpoints.append(result["endpoint"])
    return {"status":"promoted","contact":created["contact"],"endpoints":endpoints,"owner_approved":True}
