from __future__ import annotations

import secrets
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from agency_owner_api import agency_actor, now
from insforge_backend import get_backend
from logistics_a_to_z_api import app as logistics_a_to_z_app
from logistics_go_to_business_api import app as logistics_go_to_business_app

app=FastAPI(title='SAHJONY Agency Freight Operations',version='1.1.0',docs_url=None,redoc_url=None)
Mode=Literal['AIR','SEA','MULTIMODAL']
DocType=str


DOCUMENT_CATALOG = {
    'PRO_FORMA_INVOICE': ('COMMERCIAL','CONDITIONAL'),
    'COMMERCIAL_INVOICE': ('COMMERCIAL','CORE'),
    'PACKING_LIST': ('COMMERCIAL','CORE'),
    'PURCHASE_ORDER': ('COMMERCIAL','CONDITIONAL'),
    'SALES_CONTRACT': ('COMMERCIAL','CONDITIONAL'),
    'SHIPPER_LETTER_OF_INSTRUCTION': ('COMMERCIAL','CONDITIONAL'),
    'LETTER_OF_CREDIT': ('FINANCIAL','CONDITIONAL'),
    'PAYMENT_RECEIPT': ('FINANCIAL','OPERATIONAL'),
    'AGENCY_INVOICE': ('FINANCIAL','OPERATIONAL'),
    'TRANSITARIA_INVOICE': ('FINANCIAL','OPERATIONAL'),
    'SETTLEMENT_REPORT': ('FINANCIAL','OPERATIONAL'),
    'HAWB': ('TRANSPORT','CONDITIONAL'), 'MAWB': ('TRANSPORT','CONDITIONAL'),
    'HBL': ('TRANSPORT','CONDITIONAL'), 'MBL': ('TRANSPORT','CONDITIONAL'),
    'AIR_WAYBILL': ('TRANSPORT','CONDITIONAL'), 'BILL_OF_LADING': ('TRANSPORT','CONDITIONAL'),
    'CARGO_MANIFEST': ('TRANSPORT','CORE'), 'CONSOLIDATION_MANIFEST': ('TRANSPORT','OPERATIONAL'),
    'DECONSOLIDATION_MANIFEST': ('TRANSPORT','OPERATIONAL'), 'DELIVERY_MANIFEST': ('TRANSPORT','OPERATIONAL'),
    'WAREHOUSE_RECEIPT': ('WAREHOUSE','OPERATIONAL'), 'CARGO_RECEIPT': ('WAREHOUSE','OPERATIONAL'),
    'PALLET_LIST': ('WAREHOUSE','OPERATIONAL'), 'CONTAINER_PACKING_LIST': ('WAREHOUSE','OPERATIONAL'),
    'CONTAINER_LOAD_PLAN': ('WAREHOUSE','OPERATIONAL'), 'SEAL_RECORD': ('WAREHOUSE','OPERATIONAL'),
    'WEIGHT_VERIFICATION': ('WAREHOUSE','OPERATIONAL'),
    'EEI_AES_PROOF': ('CUSTOMS','ORIGIN_REQUIRED_USA_CONDITIONAL'),
    'EEI_EXEMPTION_CITATION': ('CUSTOMS','ORIGIN_REQUIRED_USA_CONDITIONAL'),
    'CERS_EXPORT_DECLARATION': ('CUSTOMS','ORIGIN_REQUIRED_CANADA_CONDITIONAL'),
    'CERS_PROOF_OF_REPORT': ('CUSTOMS','ORIGIN_REQUIRED_CANADA_CONDITIONAL'),
    'EXPORT_LICENSE': ('COMPLIANCE','CONDITIONAL'), 'IMPORT_LICENSE': ('COMPLIANCE','CONDITIONAL'),
    'CERTIFICATE_OF_ORIGIN': ('COMPLIANCE','CONDITIONAL'), 'DESTINATION_CONTROL_STATEMENT': ('COMPLIANCE','CONDITIONAL'),
    'END_USE_STATEMENT': ('COMPLIANCE','CONDITIONAL'), 'END_USER_CERTIFICATE': ('COMPLIANCE','CONDITIONAL'),
    'SANCTIONS_KYB_KYC_RECORD': ('COMPLIANCE','OPERATIONAL'), 'HS_CLASSIFICATION_RECORD': ('COMPLIANCE','CORE'),
    'CUSTOMS_DECLARATION_CUBA': ('CUSTOMS','DESTINATION_REQUIRED_CONDITIONAL'),
    'CUSTOMS_RELEASE_CUBA': ('CUSTOMS','DESTINATION_REQUIRED_CONDITIONAL'),
    'CUSTOMS_HOLD_NOTICE': ('CUSTOMS','CONDITIONAL'), 'CUSTOMS_DUTY_TAX_RECEIPT': ('CUSTOMS','CONDITIONAL'),
    'VUCE_PERMIT_RECORD': ('CUSTOMS','CONDITIONAL'),
    'SDS': ('SPECIAL_CARGO','CONDITIONAL'), 'DANGEROUS_GOODS_DECLARATION': ('SPECIAL_CARGO','CONDITIONAL'),
    'IATA_DG_SHIPPERS_DECLARATION': ('SPECIAL_CARGO','CONDITIONAL'), 'IMDG_DG_DECLARATION': ('SPECIAL_CARGO','CONDITIONAL'),
    'BATTERY_TEST_SUMMARY_UN38_3': ('SPECIAL_CARGO','CONDITIONAL'), 'PHYTOSANITARY_CERTIFICATE': ('SPECIAL_CARGO','CONDITIONAL'),
    'HEALTH_CERTIFICATE': ('SPECIAL_CARGO','CONDITIONAL'), 'SANITARY_CERTIFICATE': ('SPECIAL_CARGO','CONDITIONAL'),
    'FUMIGATION_CERTIFICATE': ('SPECIAL_CARGO','CONDITIONAL'), 'INSPECTION_CERTIFICATE': ('SPECIAL_CARGO','CONDITIONAL'),
    'INSURANCE_CERTIFICATE': ('RISK','CONDITIONAL'),
    'CHAIN_OF_CUSTODY_REPORT': ('CUSTODY','OPERATIONAL'), 'SCAN_EVENT_REPORT': ('CUSTODY','OPERATIONAL'),
    'INCIDENT_REPORT': ('CLAIMS','CONDITIONAL'), 'CLAIM_FORM': ('CLAIMS','CONDITIONAL'),
    'DAMAGE_REPORT': ('CLAIMS','CONDITIONAL'), 'SHORTAGE_REPORT': ('CLAIMS','CONDITIONAL'),
    'PROOF_OF_DELIVERY': ('DELIVERY','CORE'), 'RECIPIENT_ACCEPTANCE': ('DELIVERY','CORE'),
    'FINAL_DELIVERY_REPORT': ('DELIVERY','CORE'), 'RETURN_RECEIPT': ('DELIVERY','CONDITIONAL'),
    'PHOTO_EVIDENCE_REPORT': ('DELIVERY','OPERATIONAL'),
    'EMPLOYEE_ACKNOWLEDGEMENT': ('AGENCY','OPERATIONAL'), 'AGENCY_SERVICE_AGREEMENT': ('AGENCY','CONDITIONAL'),
    'CUSTOMER_TERMS_ACCEPTANCE': ('AGENCY','OPERATIONAL'), 'PRIVACY_CONSENT': ('AGENCY','OPERATIONAL'),
}

class DocumentRequirementQuery(BaseModel):
    origin_country:Literal['USA','CANADA']; mode:Mode; cargo_type:Literal['COMMERCIAL','NON_COMMERCIAL']='NON_COMMERCIAL'; dangerous_goods:bool=False; insured:bool=False; export_filing_required:bool=False; export_license_required:bool=False; cuba_customs_document_required:bool=True

@app.get('/agency-freight/document-catalog')
async def document_catalog(x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    await agency_actor(x_agency_id,authorization)
    return {'documents':[{'document_type':k,'category':v[0],'requirement_class':v[1]} for k,v in DOCUMENT_CATALOG.items()],'paperless_default':True,'printable':True,'rules_dynamic':True}

@app.post('/agency-freight/document-requirements')
async def document_requirements(p:DocumentRequirementQuery,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    await agency_actor(x_agency_id,authorization)
    required={'COMMERCIAL_INVOICE','PACKING_LIST','CARGO_MANIFEST','HS_CLASSIFICATION_RECORD','PROOF_OF_DELIVERY','RECIPIENT_ACCEPTANCE','FINAL_DELIVERY_REPORT'}
    conditional=set()
    required.add('AIR_WAYBILL' if p.mode=='AIR' else 'BILL_OF_LADING' if p.mode=='SEA' else 'CARGO_MANIFEST')
    if p.export_filing_required: required.add('EEI_AES_PROOF' if p.origin_country=='USA' else 'CERS_EXPORT_DECLARATION')
    else: conditional.add('EEI_EXEMPTION_CITATION' if p.origin_country=='USA' else 'CERS_EXPORT_DECLARATION')
    if p.export_license_required: required.add('EXPORT_LICENSE')
    if p.cuba_customs_document_required: required.add('CUSTOMS_DECLARATION_CUBA')
    if p.dangerous_goods:
        required.update({'SDS','DANGEROUS_GOODS_DECLARATION'})
        required.add('IATA_DG_SHIPPERS_DECLARATION' if p.mode=='AIR' else 'IMDG_DG_DECLARATION' if p.mode=='SEA' else 'DANGEROUS_GOODS_DECLARATION')
    if p.insured: required.add('INSURANCE_CERTIFICATE')
    if p.cargo_type=='COMMERCIAL': conditional.update({'PURCHASE_ORDER','SALES_CONTRACT','CERTIFICATE_OF_ORIGIN'})
    return {'required':sorted(required),'conditional':sorted(conditional),'rule':'Shipment-specific requirements override generic catalog. Verify product, carrier, exporter, importer and customs requirements before release.'}

class ConsolidationIn(BaseModel):
    name:str=Field(min_length=2,max_length=180); mode:Mode; origin:str=Field(min_length=2,max_length=180); destination:str=Field(min_length=2,max_length=180); provider:str|None=Field(default=None,max_length=180); parent_reference:str|None=Field(default=None,max_length=180)
class ConsolidationItemIn(BaseModel):
    package_id:str=Field(min_length=4,max_length=180); pieces:int=Field(default=1,ge=1); weight_lb:float|None=Field(default=None,ge=0)
class DocumentIn(BaseModel):
    document_type:DocType; number:str=Field(min_length=2,max_length=180); consolidation_id:str|None=Field(default=None,max_length=180); carrier:str|None=Field(default=None,max_length=180); origin:str|None=Field(default=None,max_length=180); destination:str|None=Field(default=None,max_length=180); metadata:dict=Field(default_factory=dict)
class RouteIn(BaseModel):
    name:str=Field(min_length=2,max_length=180); destination_province:str=Field(min_length=2,max_length=120); driver_employee_id:str|None=Field(default=None,max_length=180); vehicle_reference:str|None=Field(default=None,max_length=180); package_ids:list[str]=Field(default_factory=list,max_length=500)
class TariffIn(BaseModel):
    name:str=Field(min_length=2,max_length=180); currency:Literal['USD','CAD']='USD'; basis:Literal['FLAT','PER_LB','PER_PIECE','PERCENT']='FLAT'; amount:float=Field(ge=0); applies_to:str=Field(default='SHIPMENT',max_length=80); destination_province:str|None=Field(default=None,max_length=120)
class AgencyInvoiceIn(BaseModel):
    billed_agency_reference:str=Field(min_length=2,max_length=180); consolidation_id:str|None=Field(default=None,max_length=180); currency:Literal['USD','CAD']='USD'; subtotal:float=Field(ge=0); fees:float=Field(default=0,ge=0); notes:str|None=Field(default=None,max_length=1000)

async def _exists(table:str, aid:str, key:str, value:str):
    rows=await get_backend().select(table,params={'agency_id':f'eq.{aid}',key:f'eq.{value}','limit':'1'}) or []
    if not rows: raise HTTPException(404,f'{table} record not found in this agency')
    return rows[0]

@app.get('/agency-freight/health')
async def health():
    return {'status':'ok','consolidations':True,'master_house_documents':True,'delivery_routes':True,'tariff_engine':True,'transitaria_billing':True,'carrier_neutral':True,'tenant_isolated':True,'a_to_z_control':True,'go_to_business_engine':True,'zero_own_money_policy':True}

@app.post('/agency-freight/consolidations')
async def create_consolidation(p:ConsolidationIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); ts=now(); cid='con_'+secrets.token_urlsafe(10)
    row={'consolidation_id':cid,'agency_id':a['agency_id'],**p.model_dump(),'status':'OPEN','package_count':0,'piece_count':0,'weight_lb':0,'created_at':ts,'updated_at':ts}
    await get_backend().insert('logistics_agency_consolidations',row); return {'consolidation':row}

@app.post('/agency-freight/consolidations/{cid}/items')
async def add_item(cid:str,p:ConsolidationItemIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); aid=a['agency_id']; await _exists('logistics_agency_consolidations',aid,'consolidation_id',cid); await _exists('logistics_agency_packages',aid,'package_id',p.package_id)
    existing=await get_backend().select('logistics_agency_consolidation_items',params={'agency_id':f'eq.{aid}','consolidation_id':f'eq.{cid}','package_id':f'eq.{p.package_id}','limit':'1'}) or []
    if existing: return {'item':existing[0],'created':False,'idempotent':True}
    row={'item_id':'coni_'+secrets.token_urlsafe(9),'agency_id':aid,'consolidation_id':cid,**p.model_dump(),'created_at':now()}; await get_backend().insert('logistics_agency_consolidation_items',row)
    items=await get_backend().select('logistics_agency_consolidation_items',params={'agency_id':f'eq.{aid}','consolidation_id':f'eq.{cid}'}) or []
    patch={'package_count':len(items),'piece_count':sum(int(x.get('pieces') or 0) for x in items),'weight_lb':round(sum(float(x.get('weight_lb') or 0) for x in items),2),'updated_at':now()}
    await get_backend().patch('logistics_agency_consolidations',patch,params={'agency_id':f'eq.{aid}','consolidation_id':f'eq.{cid}'})
    await get_backend().patch('logistics_agency_packages',{'stage':'CONSOLIDATED','updated_at':now()},params={'agency_id':f'eq.{aid}','package_id':f'eq.{p.package_id}'})
    return {'item':row,'created':True,'summary':patch}

@app.post('/agency-freight/documents')
async def create_document(p:DocumentIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); aid=a['agency_id']; ts=now()
    if p.consolidation_id: await _exists('logistics_agency_consolidations',aid,'consolidation_id',p.consolidation_id)
    dtype=p.document_type.upper().strip()
    if dtype not in DOCUMENT_CATALOG: raise HTTPException(422,'Unsupported document type; use /agency-freight/document-catalog')
    row={'freight_document_id':'fdoc_'+secrets.token_urlsafe(10),'agency_id':aid,**p.model_dump(),'document_type':dtype,'category':DOCUMENT_CATALOG[dtype][0],'requirement_class':DOCUMENT_CATALOG[dtype][1],'status':'ACTIVE','created_at':ts,'updated_at':ts}
    await get_backend().insert('logistics_agency_freight_documents',row); return {'document':row,'paperless':True,'printable':True}

@app.post('/agency-freight/routes')
async def create_route(p:RouteIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); aid=a['agency_id']; ts=now()
    for pid in p.package_ids: await _exists('logistics_agency_packages',aid,'package_id',pid)
    row={'route_id':'rte_'+secrets.token_urlsafe(10),'agency_id':aid,**p.model_dump(),'status':'PLANNED','stops':len(p.package_ids),'created_at':ts,'updated_at':ts}
    await get_backend().insert('logistics_agency_delivery_routes',row); return {'route':row}

@app.post('/agency-freight/tariffs')
async def create_tariff(p:TariffIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); row={'tariff_id':'tar_'+secrets.token_urlsafe(10),'agency_id':a['agency_id'],**p.model_dump(),'status':'ACTIVE','created_at':now(),'updated_at':now()}; await get_backend().insert('logistics_agency_tariffs',row); return {'tariff':row}

@app.post('/agency-freight/agency-invoices')
async def create_agency_invoice(p:AgencyInvoiceIn,x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    a=await agency_actor(x_agency_id,authorization); aid=a['agency_id']
    if p.consolidation_id: await _exists('logistics_agency_consolidations',aid,'consolidation_id',p.consolidation_id)
    total=round(p.subtotal+p.fees,2); row={'agency_invoice_id':'ainv_'+secrets.token_urlsafe(10),'agency_id':aid,**p.model_dump(),'total':total,'balance_due':total,'status':'OPEN','created_at':now(),'updated_at':now()}; await get_backend().insert('logistics_agency_invoices',row); return {'invoice':row,'paperless':True,'printable':True}

CUSTOMS_LINKS={
    'CUBA':[
        {'name':'Aduana General de la República de Cuba','url':'https://www.aduana.gob.cu/','purpose':'Customs rules, import/export, tariffs and official guidance'},
        {'name':'VUCE Cuba','url':'https://vuceregulaciones.mincex.gob.cu/','purpose':'Foreign-trade regulations, permits and procedures'},
    ],
    'CANADA':[
        {'name':'CBSA Exporting Commercial Goods','url':'https://www.cbsa-asfc.gc.ca/services/export/menu-eng.html','purpose':'Canadian export reporting requirements and guidance'},
        {'name':'CERS Portal','url':'https://www.cbsa-asfc.gc.ca/services/export/portal-portail/menu-eng.html','purpose':'Submit Canadian export declarations electronically'},
    ],
    'USA':[
        {'name':'AES / EEI Guidance','url':'https://www.trade.gov/filing-your-export-shipments-through-automated-export-system-aes','purpose':'Official U.S. guidance for EEI filing through AESDirect'},
        {'name':'ACE Exporter Account','url':'https://ace-accounts.cbp.gov/s/exporter-form','purpose':'CBP ACE exporter account access for AESDirect'},
    ],
}

@app.get('/agency-freight/customs-links')
async def customs_links(origin_country:str='USA',x_agency_id:str|None=Header(None,alias='X-Agency-Id'),authorization:str|None=Header(None,alias='Authorization')):
    await agency_actor(x_agency_id,authorization)
    origin=origin_country.upper()
    if origin in {'US','UNITED STATES','UNITED_STATES'}: origin='USA'
    if origin in {'CA','CAN'}: origin='CANADA'
    if origin not in {'USA','CANADA'}: raise HTTPException(422,'Customs hub currently supports USA or Canada origins to Cuba')
    return {'origin_country':origin,'destination_country':'CUBA','origin_customs':CUSTOMS_LINKS[origin],'destination_customs':CUSTOMS_LINKS['CUBA'],'official_links_only':True}

app.include_router(logistics_a_to_z_app.router)
app.include_router(logistics_go_to_business_app.router)
